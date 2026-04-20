"""
ingestion/news_scraper.py
--------------------------
홈로봇 관련 RSS 피드 및 뉴스 사이트 크롤링 엔진.
수집된 기사를 DB에 저장하고 LLM 분석 큐에 올립니다.
"""
import os
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import feedparser
import httpx
from bs4 import BeautifulSoup
from dateutil import parser as dateparser
from dotenv import load_dotenv

from engine.deduplicator import check_and_mark
from db.vector_store import save_article, get_news_sources

load_dotenv()
logger = logging.getLogger(__name__)

MAX_PER_SOURCE = int(os.getenv("MAX_ARTICLES_PER_SOURCE", "20"))


# ---- 데이터 구조 -------------------------------------------
@dataclass
class RawArticle:
    url: str
    source: str
    source_type: str = "news"
    title: str = ""
    content: str = ""
    author: Optional[str] = None
    published_at: Optional[datetime] = None
    thumbnail_url: Optional[str] = None


# ---- 본문 추출 ---------------------------------------------
def _extract_full_text_and_image(url: str) -> tuple[str, Optional[str]]:
    """URL에서 본문 텍스트와 대표 이미지(og:image) URL을 추출합니다 (BeautifulSoup4)."""
    try:
        # 리다이렉션 허용(follow_redirects=True) 및 브라우저 User-Agent 설정
        with httpx.Client(proxy=None, trust_env=False, timeout=15.0, follow_redirects=True) as client:
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7"
            }
            resp = client.get(url, headers=headers)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")
            
        # 대표 이미지(og:image) 추출
        thumbnail_url = None
        og_image = soup.find("meta", property="og:image")
        if og_image:
            thumbnail_url = og_image.get("content")
        else:
            # 폴백 1: twitter:image
            twitter_image = soup.find("meta", property="twitter:image")
            if twitter_image:
                thumbnail_url = twitter_image.get("content")
            else:
                # 폴백 2: 기사 본문 내 첫 번째 이미지 (일정 크기 이상 가정)
                first_img = soup.find("img", src=True)
                if first_img:
                    thumbnail_url = first_img.get("src")

        # 주요 본문 태그 우선 탐색
        for selector in ["article", "main", ".post-content", ".article-body", "#content"]:
            container = soup.select_one(selector)
            if container:
                return container.get_text(separator="\n", strip=True)[:8000], thumbnail_url

        # 폴백: body 전체
        body = soup.find("body")
        return (body.get_text(separator="\n", strip=True)[:8000] if body else ""), thumbnail_url
    except Exception as e:
        logger.warning(f"본문/이미지 추출 실패 ({url}): {e}")
        return "", None


def _parse_date(entry) -> Optional[datetime]:
    """feedparser 엔트리에서 발행일을 파싱합니다."""
    for attr in ("published", "updated", "created"):
        raw = getattr(entry, attr, None)
        if raw:
            try:
                return dateparser.parse(raw).astimezone(timezone.utc)
            except Exception:
                pass
    return None


# ---- 핵심 수집 함수 -----------------------------------------
def fetch_rss_source(source: dict) -> tuple[int, int, int]:
    """
    단일 RSS 소스를 수집하여 DB에 저장합니다.

    Returns:
        (fetched, skipped, saved) 튜플
    """
    fetched = skipped = saved = 0

    try:
        feed = feedparser.parse(source["url"])
        entries = feed.entries[:MAX_PER_SOURCE]
        fetched = len(entries)

        for entry in entries:
            url = entry.get("link", "")
            if not url:
                skipped += 1
                continue

            # 중복 체크
            if check_and_mark(url):
                skipped += 1
                logger.debug(f"[스킵] 중복 URL: {url}")
                continue

            # 본문 수집
            content, thumbnail_url = _extract_full_text_and_image(url)

            article = RawArticle(
                url=url,
                source=source["name"],
                title=entry.get("title", ""),
                content=content or entry.get("summary", ""),
                author=entry.get("author"),
                published_at=_parse_date(entry),
                thumbnail_url=thumbnail_url,
            )

            save_article(article)
            saved += 1
            logger.info(f"[저장] {article.title[:60]}...")

    except Exception as e:
        logger.error(f"RSS 수집 오류 ({source['name']}): {e}")

    return fetched, skipped, saved


def run_all_sources() -> dict:
    """모든 RSS 소스를 DB에서 조회하여 순차적으로 수집합니다."""
    total = {"fetched": 0, "skipped": 0, "saved": 0}
    
    # DB에서 활성화된 소스 목록 가져오기
    sources = get_news_sources(active_only=True)
    max_per = int(os.getenv("MAX_ARTICLES_PER_SOURCE", "20"))

    for source in sources:
        logger.info(f"수집 시작: {source['label']}")
        f, sk, sv = fetch_rss_source(source)
        total["fetched"] += f
        total["skipped"] += sk
        total["saved"] += sv
        logger.info(f"  → 수집: {f}, 스킵: {sk}, 저장: {sv}")

    return total


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = run_all_sources()
    print(f"\n✅ 완료 - 총 수집: {result['fetched']}, 스킵: {result['skipped']}, 저장: {result['saved']}")
