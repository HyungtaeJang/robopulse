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
import dateparser
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from dotenv import load_dotenv

from engine.deduplicator import check_and_mark
from db.vector_store import save_article, get_news_sources

load_dotenv()
logger = logging.getLogger(__name__)

MAX_PER_SOURCE = int(os.getenv("MAX_ARTICLES_PER_SOURCE", "20"))

IMAGE_BLACKLIST = [
    "favicon", "logo", "default_pic", "white_g.png", "logo-google", "nav_logo", 
    "gstatic.com", "google_news", "google-news", "avatar", "icon", "placeholder", "branding",
    "googleusercontent.com"
]

def is_valid_image(img_url: str) -> bool:
    """이미지가 유효한 기사 이미지인지 체크 (로고/아이콘 제외)"""
    if not img_url: return False
    low_url = img_url.lower()
    # 블랙리스트 포함 여부 확인
    if any(p in low_url for p in IMAGE_BLACKLIST):
        return False
    # 너무 작은 이미지나 아이콘 확장자 제외 (단순화)
    if low_url.endswith((".ico", ".gif")):
        return False
    return True


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
    # 제외할 이미지 패턴 (로고, 아이콘 등 기사와 무관한 것)
    IMAGE_BLACKLIST = ["favicon", "logo", "default_pic", "white_g.png", "logo-google", "nav_logo"]

    try:
        # 리다이렉션 허용(follow_redirects=True) 및 브라우저 User-Agent 설정
        with httpx.Client(proxy=None, trust_env=False, timeout=15.0, follow_redirects=True) as client:
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
                "Referer": "https://news.google.com/" # 구글 뉴스 유입 위장
            }
            resp = client.get(url, headers=headers)
            resp.raise_for_status()
            final_url = str(resp.url)
            soup = BeautifulSoup(resp.text, "lxml")
            
            final_url = str(resp.url)
            soup = BeautifulSoup(resp.text, "lxml")

        # 대표 이미지 추출 (순차적 탐색)
        thumbnail_url = None
        
        # 더 다양한 본문 컨테이너 정의 (항상 참조 가능하도록 상단 배치)
        selectors = [
            "article", "main", ".post-content", ".article-body", "#content", 
            ".entry-content", ".article_body", ".story-content", ".post_content", ".post-body",
            "#articleBodyContents", "#newsEndContents", ".news_end", "#articeBody", # 한국 뉴스 전용
            ".article_txt", ".article_view", ".viewer"
        ]
        
        # 1. Meta Tags (og, twitter, generic)
        for attr in ["property", "name"]:
            for tag_val in ["og:image", "twitter:image", "image", "thumbnail"]:
                meta = soup.find("meta", {attr: tag_val})
                if meta and meta.get("content"):
                    candidate = meta.get("content")
                    if is_valid_image(candidate):
                        thumbnail_url = candidate
                        break
            if thumbnail_url: break
            
        # 2. Body First Image (if meta fails or is invalid)
        if not thumbnail_url:
            for selector in selectors:
                container = soup.select_one(selector)
                if container:
                    # 모든 이미지를 검사하여 유효한 첫 번째 이미지를 선택
                    imgs = container.find_all("img")
                    for img in imgs:
                        # 레이지 로딩 및 고해상도 속성 총망라
                        src = (
                            img.get("src") or 
                            img.get("data-src") or 
                            img.get("data-original") or 
                            img.get("data-lazy-src") or 
                            img.get("data-hi-res") or
                            img.get("srcset")
                        )
                        if not src: continue
                        
                        # srcset 처리 (콤마로 구분된 목록 중 첫 번째 URL 선택)
                        if "," in src and " " in src:
                            src = src.split(",")[0].strip().split(" ")[0]
                        
                        abs_src = urljoin(final_url, src)
                        if is_valid_image(abs_src):
                            thumbnail_url = abs_src
                            break
                    if thumbnail_url: break

        # 3. Aggressive Fallback (컨테이너 밖 body 전체에서 찾기)
        if not thumbnail_url:
            body = soup.find("body")
            if body:
                for img in body.find_all("img"):
                    src = img.get("src") or img.get("data-src")
                    if not src: continue
                    abs_src = urljoin(final_url, src)
                    # 블랙리스트에 없고, 확장자가 유효하면 채택
                    if is_valid_image(abs_src):
                        thumbnail_url = abs_src
                        break

        # 주요 본문 태그 우선 탐색
        for selector in selectors:
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

def _extract_rss_image(entry) -> Optional[str]:
    """feedparser 엔트리에서 썸네일 이미지를 추출합니다."""
    # 1. media:content (구글 뉴스 등에서 많이 사용)
    media_content = entry.get("media_content")
    if media_content and len(media_content) > 0:
        return media_content[0].get("url")
    
    # 2. links (enclosures)
    for link in entry.get("links", []):
        if "image" in link.get("type", ""):
            return link.get("href")
            
    # 3. description 내의 img 태그 (HTML인 경우)
    summary = entry.get("summary", "")
    if summary and "<img" in summary:
        try:
            temp_soup = BeautifulSoup(summary, "lxml")
            img = temp_soup.find("img")
            if img and img.get("src"):
                return img.get("src")
        except:
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

            # 1. RSS 자체 이미지 우선 확인 (가장 확실함)
            rss_thumb = _extract_rss_image(entry)
            thumbnail_url = rss_thumb if is_valid_image(rss_thumb) else None
            
            # 2. 본문 및 이미지 크롤링 (웹페이지 방문)
            content, web_thumb = _extract_full_text_and_image(url)
            
            # 웹 크롤링 이미지가 유효하면 우선 사용 (보통 더 고화질), 없으면 RSS 이미지 사용
            if is_valid_image(web_thumb):
                thumbnail_url = web_thumb
            elif not thumbnail_url and is_valid_image(web_thumb): # 중복 검사지만 확실히
                thumbnail_url = web_thumb

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
