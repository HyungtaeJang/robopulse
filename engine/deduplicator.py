"""
engine/deduplicator.py
---------------------
Redis 기반 URL 중복 수집 방어 모듈.
SHA-256 해시를 키로 사용하며 설정 가능한 TTL 동안 보존합니다.
"""
import hashlib
import os
import redis

from dotenv import load_dotenv

load_dotenv()

_redis_client: redis.Redis | None = None


def _get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis.from_url(
            os.getenv("REDIS_URL", "redis://localhost:6379/0"),
            decode_responses=True,
        )
    return _redis_client


def _url_to_hash(url: str) -> str:
    return hashlib.sha256(url.strip().encode()).hexdigest()


def is_duplicate(url: str) -> bool:
    """해당 URL이 이미 수집된 적 있으면 True를 반환합니다."""
    r = _get_redis()
    key = f"robopulse:seen:{_url_to_hash(url)}"
    return r.exists(key) == 1


def mark_seen(url: str, ttl_days: int | None = None) -> None:
    """URL을 '수집 완료'로 표시합니다. ttl_days만큼 Redis에 보존됩니다."""
    if ttl_days is None:
        ttl_days = int(os.getenv("DEDUP_TTL_DAYS", "90"))
    r = _get_redis()
    key = f"robopulse:seen:{_url_to_hash(url)}"
    r.set(key, 1, ex=ttl_days * 86400)


def check_and_mark(url: str) -> bool:
    """
    중복 여부를 확인하고 신규 URL이면 바로 mark_seen()을 호출합니다.
    Returns:
        True  → 이미 존재 (스킵해야 함)
        False → 신규 (처리해야 함)
    """
    if is_duplicate(url):
        return True
    mark_seen(url)
    return False
