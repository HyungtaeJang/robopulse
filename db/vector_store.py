"""
db/vector_store.py
-------------------
PostgreSQL + pgvector 연동 모듈.
기사 저장, 임베딩 생성, 의미론적 검색(RAG)을 지원합니다.
"""
import logging
import os
import uuid
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv
import httpx
import redis
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.orm import sessionmaker

load_dotenv()
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:password@localhost:5432/robopulse")
LMS_BASE_URL = os.getenv("LMS_API_BASE", "http://localhost:1234/v1")

_engine = None
_Session = None
_lms_client: OpenAI | None = None


def _get_engine():
    global _engine, _Session
    if _engine is None:
        _engine = create_engine(DATABASE_URL, pool_pre_ping=True)
        _Session = sessionmaker(bind=_engine)
    return _engine


def _get_session():
    _get_engine()
    return _Session()


def _get_lms_client() -> OpenAI:
    global _lms_client
    if _lms_client is None:
        # 기업망 환경(프록시) 충돌 방지를 위해 빈 httpx.Client 사용
        http_client = httpx.Client(proxies={})
        _lms_client = OpenAI(
            base_url=LMS_BASE_URL, 
            api_key="lm-studio",
            http_client=http_client
        )
    return _lms_client


def _generate_embedding(text: str) -> Optional[list[float]]:
    """LM Studio의 임베딩 API를 호출하여 벡터를 생성합니다."""
    try:
        client = _get_lms_client()
        response = client.embeddings.create(
            model="text-embedding-nomic-embed-text-v1.5",  # LM Studio에 로드된 임베딩 모델
            input=text[:2000],  # 임베딩 입력 길이 제한
        )
        return response.data[0].embedding
    except Exception as e:
        logger.warning(f"임베딩 생성 실패: {e}")
        return None


def init_db() -> None:
    """schema.sql을 실행하여 테이블을 초기화합니다."""
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    with open(schema_path, encoding="utf-8") as f:
        sql = f.read()

    engine = _get_engine()
    with engine.connect() as conn:
        conn.execute(text(sql))
        conn.commit()
    logger.info("DB 스키마 초기화 완료")


def save_article(article) -> Optional[str]:
    """
    RawArticle 객체를 articles 테이블에 저장합니다.
    임베딩은 title + content 앞부분을 합쳐서 생성합니다.

    Returns:
        저장된 기사의 UUID 문자열, 실패 시 None
    """
    import hashlib

    url_hash = hashlib.sha256(article.url.strip().encode()).hexdigest()
    embed_text = f"{article.title}\n\n{article.content[:1500]}"
    embedding = _generate_embedding(embed_text)

    session = _get_session()
    try:
        article_id = str(uuid.uuid4())
        embedding_str = f"[{','.join(str(v) for v in embedding)}]" if embedding else None

        session.execute(text("""
            INSERT INTO articles (id, url_hash, url, source, source_type, title, content,
                                  author, published_at, embedding)
            VALUES (:id, :url_hash, :url, :source, :source_type, :title, :content,
                    :author, :published_at, CAST(:embedding AS vector))
            ON CONFLICT (url_hash) DO NOTHING
        """), {
            "id": article_id,
            "url_hash": url_hash,
            "url": article.url,
            "source": article.source,
            "source_type": getattr(article, "source_type", "news"),
            "title": article.title,
            "content": article.content,
            "author": getattr(article, "author", None),
            "published_at": getattr(article, "published_at", None),
            "embedding": embedding_str,
        })
        session.commit()
        return article_id
    except Exception as e:
        session.rollback()
        logger.error(f"기사 저장 실패: {e}")
        return None
    finally:
        session.close()


def save_analysis_result(article_id: str, analysis) -> None:
    """
    LLM 분석 결과(ArticleAnalysis)를 DB에 반영합니다.
    - articles 테이블 업데이트 (summary, sentiment, importance)
    - entities / relations / tags 테이블 삽입
    """
    session = _get_session()
    try:
        # 1. articles 업데이트
        session.execute(text("""
            UPDATE articles
            SET summary = :summary,
                sentiment = :sentiment,
                importance = :importance,
                is_processed = TRUE,
                processed_at = NOW()
            WHERE id = :article_id
        """), {
            "summary": analysis.summary,
            "sentiment": analysis.sentiment,
            "importance": analysis.importance_score,
            "article_id": article_id,
        })

        # 2. 엔티티 저장 + article_entities 연결
        entity_ids: dict[str, str] = {}
        for entity in analysis.entities:
            name = entity.name.strip()
            if not name:
                continue
            ent_id = str(uuid.uuid4())
            result = session.execute(text("""
                INSERT INTO entities (id, name, type)
                VALUES (:id, :name, :type)
                ON CONFLICT (name) DO UPDATE SET type = EXCLUDED.type
                RETURNING id
            """), {"id": ent_id, "name": name, "type": entity.type})
            real_id = str(result.fetchone()[0])
            entity_ids[name] = real_id

            session.execute(text("""
                INSERT INTO article_entities (article_id, entity_id)
                VALUES (:article_id, :entity_id)
                ON CONFLICT DO NOTHING
            """), {"article_id": article_id, "entity_id": real_id})

        # 3. 관계 저장
        for rel in analysis.relations:
            subj_id = entity_ids.get(rel.subject)
            obj_id = entity_ids.get(rel.object)
            if subj_id and obj_id:
                session.execute(text("""
                    INSERT INTO relations (id, article_id, subject_id, predicate, object_id)
                    VALUES (:id, :article_id, :subject_id, :predicate, :object_id)
                """), {
                    "id": str(uuid.uuid4()),
                    "article_id": article_id,
                    "subject_id": subj_id,
                    "predicate": rel.predicate,
                    "object_id": obj_id,
                })

        # 4. 태그 저장
        for tag in analysis.tags:
            session.execute(text("""
                INSERT INTO tags (article_id, category)
                VALUES (:article_id, :category)
                ON CONFLICT DO NOTHING
            """), {"article_id": article_id, "category": tag.strip()})

        session.commit()
        logger.info(f"분석 결과 저장 완료: {article_id}")

    except Exception as e:
        session.rollback()
        logger.error(f"분석 결과 저장 실패: {e}")
    finally:
        session.close()


def semantic_search(query: str, top_k: int = 10) -> list[dict]:
    """
    자연어 쿼리를 벡터로 변환하여 의미론적으로 유사한 기사를 검색합니다 (RAG).
    """
    embedding = _generate_embedding(query)
    if not embedding:
        return []

    embedding_str = f"[{','.join(str(v) for v in embedding)}]"
    session = _get_session()
    try:
        result = session.execute(text("""
            SELECT id, title, source, summary, sentiment, importance, published_at,
                   1 - (embedding <=> :embedding::vector) AS similarity
            FROM articles
            WHERE is_processed = TRUE AND embedding IS NOT NULL
            ORDER BY embedding <=> :embedding::vector
            LIMIT :top_k
        """), {"embedding": embedding_str, "top_k": top_k})

        rows = result.fetchall()
        return [dict(row._mapping) for row in rows]
    finally:
        session.close()


def get_unprocessed_articles(limit: int = 50) -> list[dict]:
    """LLM 분석이 아직 안 된 기사 목록을 반환합니다."""
    session = _get_session()
    try:
        result = session.execute(text("""
            SELECT id, title, content, source
            FROM articles
            WHERE is_processed = FALSE
            ORDER BY collected_at ASC
            LIMIT :limit
        """), {"limit": limit})
        return [dict(row._mapping) for row in result.fetchall()]
    finally:
        session.close()


def get_pipeline_stats() -> dict:
    """모니터링 대시보드용 파이프라인 통계를 반환합니다."""
    session = _get_session()
    try:
        stats = {}

        result = session.execute(text("""
            SELECT
                COUNT(*) FILTER (WHERE collected_at::date = CURRENT_DATE) AS today_total,
                COUNT(*) FILTER (WHERE is_processed = TRUE AND processed_at::date = CURRENT_DATE) AS today_processed,
                COUNT(*) FILTER (WHERE is_processed = FALSE) AS pending,
                COUNT(*) AS total
            FROM articles
        """))
        row = result.fetchone()
        stats.update(dict(row._mapping))

        result2 = session.execute(text("""
            SELECT source, COUNT(*) AS count, MAX(collected_at) AS last_collected
            FROM articles
            GROUP BY source
            ORDER BY last_collected DESC
        """))
        stats["sources"] = [dict(r._mapping) for r in result2.fetchall()]

        return stats
    finally:
        session.close()


def check_all_connections() -> dict:
    """PostgreSQL, Redis, LM Studio의 연결 상태를 체크합니다."""
    results = {"postgres": False, "redis": False, "lms": False}

    # 1. Postgres
    try:
        engine = _get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        results["postgres"] = True
    except Exception:
        pass

    # 2. Redis
    try:
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        r = redis.from_url(redis_url, socket_connect_timeout=1)
        if r.ping():
            results["redis"] = True
    except Exception:
        pass

    # 3. LM Studio
    try:
        client = _get_lms_client()
        # 가벼운 모델 리스트 조회로 테스트
        client.models.list()
        results["lms"] = True
    except Exception:
        pass

    return results


def get_all_relations() -> list[dict]:
    """지식 그래프 복원을 위해 모든 관계 데이터를 가져옵니다."""
    session = _get_session()
    try:
        result = session.execute(text("""
            SELECT r.article_id, s.name AS subject, r.predicate, o.name AS object
            FROM relations r
            JOIN entities s ON r.subject_id = s.id
            JOIN entities o ON r.object_id = o.id
        """))
        return [dict(row._mapping) for row in result.fetchall()]
    finally:
        session.close()


def get_latest_articles(limit: int = 20, min_importance: float = 0.0) -> list[dict]:
    """분석 완료된 최신 기사를 가져옵니다."""
    session = _get_session()
    try:
        result = session.execute(text("""
            SELECT a.id, a.title, a.url, a.source, a.summary, a.sentiment, a.importance, a.published_at,
                   array_agg(t.category) AS tags
            FROM articles a
            LEFT JOIN tags t ON a.id = t.article_id
            WHERE a.is_processed = TRUE AND a.importance >= :min_imp
            GROUP BY a.id
            ORDER BY a.published_at DESC
            LIMIT :limit
        """), {"limit": limit, "min_imp": min_importance})
        return [dict(row._mapping) for row in result.fetchall()]
    finally:
        session.close()


def get_all_entities_for_graph() -> list[tuple[str, str]]:
    """모든 엔티티 노드 데이터를 가져옵니다."""
    session = _get_session()
    try:
        result = session.execute(text("SELECT name, type FROM entities"))
        return [raw for raw in result.fetchall()]
    finally:
        session.close()
