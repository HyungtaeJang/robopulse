"""
ingestion/video_processor.py
-----------------------------
유튜브 채널에서 yt-dlp를 활용해 영상 자막(자동생성 포함)을 수집합니다.
수집된 자막은 articles 테이블에 저장되고 LLM 분석 큐에 올라갑니다.
"""
import logging
import os
import subprocess
import json
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from engine.deduplicator import check_and_mark
from db.vector_store import save_article
from ingestion.news_scraper import RawArticle

load_dotenv_safe = None
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logger = logging.getLogger(__name__)

MAX_PER_CHANNEL = int(os.getenv("MAX_ARTICLES_PER_SOURCE", "10"))

# ---- 수집 채널 목록 (현재는 DB에서 동적으로 관리됨) ----


def _fetch_channel_videos(channel_url: str, max_count: int = MAX_PER_CHANNEL) -> list[dict]:
    """yt-dlp로 채널의 최신 영상 메타데이터를 가져옵니다."""
    cmd = [
        "yt-dlp",
        "--flat-playlist",
        "--playlist-end", str(max_count),
        "--dump-json",
        "--no-warnings",
        channel_url,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        videos = []
        for line in result.stdout.strip().split("\n"):
            if line.strip():
                try:
                    videos.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return videos
    except Exception as e:
        logger.error(f"채널 조회 실패 ({channel_url}): {e}")
        return []


def _download_subtitle(video_id: str) -> Optional[str]:
    """
    영상 자막(한국어 우선, 없으면 영어)을 다운로드하여 텍스트로 반환합니다.
    yt-dlp의 --write-auto-subs 옵션으로 자동 생성 자막도 수집합니다.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        cmd = [
            "yt-dlp",
            f"https://www.youtube.com/watch?v={video_id}",
            "--write-auto-subs",
            "--sub-langs", "ko,en",
            "--skip-download",
            "--convert-subs", "srt",
            "-o", f"{tmpdir}/%(id)s.%(ext)s",
            "--no-warnings",
        ]
        try:
            subprocess.run(cmd, capture_output=True, timeout=60)
            # 다운로드된 .srt 파일 탐색
            srt_files = list(Path(tmpdir).glob("*.srt"))
            if not srt_files:
                return None
            # SRT → 순수 텍스트 변환
            raw = srt_files[0].read_text(encoding="utf-8", errors="ignore")
            lines = []
            for line in raw.split("\n"):
                stripped = line.strip()
                # 타임코드, 인덱스 번호 제거
                if stripped.isdigit() or "-->" in stripped or not stripped:
                    continue
                lines.append(stripped)
            return " ".join(lines)[:8000]
        except Exception as e:
            logger.warning(f"자막 다운로드 실패 ({video_id}): {e}")
            return None


def fetch_channel(channel: dict) -> tuple[int, int, int]:
    """
    단일 유튜브 채널을 처리합니다.
    Returns: (fetched, skipped, saved)
    """
    fetched = skipped = saved = 0
    videos = _fetch_channel_videos(channel["channel_url"])
    fetched = len(videos)

    for video in videos:
        video_id = video.get("id", "")
        url = f"https://www.youtube.com/watch?v={video_id}"
        if not video_id:
            skipped += 1
            continue

        if check_and_mark(url):
            skipped += 1
            logger.debug(f"[스킵] 중복 영상: {url}")
            continue

        subtitle = _download_subtitle(video_id)
        if not subtitle:
            logger.warning(f"자막 없음, 설명란으로 대체: {video_id}")
            # description이 None일 경우를 대비해 'or ""' 추가
            subtitle = (video.get("description") or "")[:4000]

        # 발행일 파싱
        upload_date = video.get("upload_date", "")
        published_at = None
        if upload_date and len(upload_date) == 8:
            try:
                published_at = datetime(
                    int(upload_date[:4]), int(upload_date[4:6]), int(upload_date[6:]),
                    tzinfo=timezone.utc,
                )
            except ValueError:
                pass

        thumbnail_url = video.get("thumbnail") or f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"

        article = RawArticle(
            url=url,
            source=channel["name"],
            source_type="video",
            title=video.get("title", ""),
            content=subtitle,
            published_at=published_at,
            thumbnail_url=thumbnail_url,
        )

        save_article(article)
        saved += 1
        logger.info(f"[저장] {article.title[:60]}...")

    return fetched, skipped, saved


def run_all_channels() -> dict:
    """모든 유튜브 채널을 순차적으로 수집합니다."""
    from db.vector_store import get_youtube_sources
    
    total = {"fetched": 0, "skipped": 0, "saved": 0}
    
    active_channels = [ch for ch in get_youtube_sources() if ch["is_active"]]

    for channel in active_channels:
        logger.info(f"채널 수집 시작: {channel['label']}")
        f, sk, sv = fetch_channel(channel)
        total["fetched"] += f
        total["skipped"] += sk
        total["saved"] += sv
        logger.info(f"  → 수집: {f}, 스킵: {sk}, 저장: {sv}")

    return total


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = run_all_channels()
    print(f"\n✅ 완료 - 총 수집: {result['fetched']}, 스킵: {result['skipped']}, 저장: {result['saved']}")
