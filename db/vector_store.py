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
from openai import OpenAI
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
        
        # Self-Healing: thumbnail_url 컬럼 자동 생성 및 백필
        try:
            with _engine.connect() as conn:
                conn.execute(text("ALTER TABLE articles ADD COLUMN IF NOT EXISTS thumbnail_url TEXT;"))
                conn.execute(text("ALTER TABLE articles ADD COLUMN IF NOT EXISTS key_points TEXT;"))
                
                # 새 기능: youtube_sources 및 recommended_sources 테이블 생성
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS youtube_sources (
                        id SERIAL PRIMARY KEY,
                        name TEXT UNIQUE NOT NULL,
                        channel_url TEXT NOT NULL,
                        label TEXT NOT NULL,
                        is_active BOOLEAN DEFAULT TRUE,
                        created_at TIMESTAMPTZ DEFAULT NOW()
                    );
                """))
                
                # 중복 데이터 자동 청소 (Migrate: 중복 제거)
                conn.execute(text("""
                    DELETE FROM youtube_sources a USING youtube_sources b 
                    WHERE a.id > b.id AND a.channel_url = b.channel_url;
                """))
                
                # 기존 테이블 대응: channel_url에 유니크 인덱스 추가
                conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS idx_youtube_sources_url ON youtube_sources(channel_url);"))
                
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS recommended_sources (
                        id SERIAL PRIMARY KEY,
                        url TEXT UNIQUE NOT NULL,
                        source_type TEXT NOT NULL,
                        label TEXT,
                        reason TEXT,
                        status TEXT DEFAULT 'pending',
                        created_at TIMESTAMPTZ DEFAULT NOW()
                    );
                """))
                
                # 기존 youtube_channels 하드코딩 데이터를 테이블로 이전 (최초 1회)
                conn.execute(text("""
                    INSERT INTO youtube_sources (name, channel_url, label)
                    VALUES 
                    ('youtube_boston_dynamics', 'https://www.youtube.com/@BostonDynamics', 'Boston Dynamics'),
                    ('youtube_agility_robotics', 'https://www.youtube.com/@AgilityRobotics', 'Agility Robotics'),
                    ('youtube_ieee_robotics', 'https://www.youtube.com/@IEEERobotics', 'IEEE Robotics & Automation'),
                    ('youtube_cnet', 'https://www.youtube.com/@cnet', 'CNET Technology')
                    ON CONFLICT DO NOTHING;
                """))

                # 기존 유튜브 영상 썸네일 일괄 복구
                conn.execute(text("""
                    UPDATE articles 
                    SET thumbnail_url = 'https://i.ytimg.com/vi/' || substring(url from 'v=([^&]+)') || '/hqdefault.jpg'
                    WHERE source_type = 'video' AND thumbnail_url IS NULL AND url LIKE '%v=%';
                """))
                
                # 아직 한국어로 번역되지 않은 영어 제목의 기사를 재분석 대기열로 돌림
                # (정규식을 통해 한글이 전혀 없는 제목의 is_processed를 FALSE로 변경)
                conn.execute(text("""
                    UPDATE articles 
                    SET is_processed = FALSE 
                    WHERE title !~ '[가-힣]' AND is_processed = TRUE;
                """))

                # [중요] 사용자의 요청에 따른 전체 재분석 트리거 (Key Points 생성을 위함)
                # 만약 key_points가 NULL인 기사들이 있다면(기존 기사들), re-analysis를 위해 is_processed를 다시 FALSE로 만듭니다.
                conn.execute(text("""
                    UPDATE articles 
                    SET is_processed = FALSE 
                    WHERE key_points IS NULL AND is_processed = TRUE;
                """))
                
                conn.commit()
        except Exception as e:
            logger.warning(f"DB 마이그레이션/백필 실패: {e}")
            
    return _engine


def _get_session():
    _get_engine()
    return _Session()


def get_lms_client() -> OpenAI:
    global _lms_client
    if _lms_client is None:
        # trust_env=False를 추가하여 시스템의 모든 프록시 설정을 완전히 무시하고 다이렉트 통신
        http_client = httpx.Client(proxy=None, trust_env=False)
        _lms_client = OpenAI(
            base_url=LMS_BASE_URL, 
            api_key="lm-studio",
            http_client=http_client
        )
    return _lms_client


def _generate_embedding(text: str) -> Optional[list[float]]:
    """LM Studio의 임베딩 API를 호출하여 벡터를 생성합니다."""
    try:
        client = get_lms_client()
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
                                  author, published_at, thumbnail_url, embedding)
            VALUES (:id, :url_hash, :url, :source, :source_type, :title, :content,
                    :author, :published_at, :thumbnail_url, CAST(:embedding AS vector))
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
            "thumbnail_url": getattr(article, "thumbnail_url", None),
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
                key_points = :key_points,
                sentiment = :sentiment,
                importance = :importance,
                is_processed = TRUE,
                processed_at = NOW(),
                title = COALESCE(:translated_title, title)
            WHERE id = :article_id
        """), {
            "summary": analysis.summary,
            "key_points": "\n".join(getattr(analysis, 'key_points', [])),
            "sentiment": analysis.sentiment,
            "importance": analysis.importance_score,
            "translated_title": getattr(analysis, 'translated_title', None),
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
                   1 - (embedding <=> CAST(:embedding AS vector)) AS similarity
            FROM articles
            WHERE is_processed = TRUE AND embedding IS NOT NULL
            ORDER BY embedding <=> CAST(:embedding AS vector)
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
        client = get_lms_client()
        client.models.list()
        results["lms"] = True
    except Exception:
        pass

    return results


def get_available_lms_models() -> list[str]:
    """LM Studio에서 현재 로드되어 사용 가능한 모델 목록을 가져옵니다."""
    try:
        client = get_lms_client()
        models = client.models.list()
        return [m.id for m in models.data]
    except Exception as e:
        logger.warning(f"LM Studio 모델 목록 가저오기 실패: {e}")
        return []


def get_all_relations() -> list[dict]:
    """지식 그래프 복원을 위해 모든 관계 데이터를 가져옵니다."""
    session = _get_session()
    try:
        result = session.execute(text("""
            SELECT 
                r.article_id, 
                s.name AS subject, s.type AS subj_type,
                r.predicate, 
                o.name AS object, o.type AS obj_type
            FROM relations r
            JOIN entities s ON r.subject_id = s.id
            JOIN entities o ON r.object_id = o.id
        """))
        return [dict(row._mapping) for row in result.fetchall()]
    finally:
        session.close()


def get_latest_articles(limit: int = 50, min_importance: float = 0.0, today_only: bool = False, tag_filter: str = None, sort_by: str = "date") -> list[dict]:
    """분석 완료된 최신 기사를 가져옵니다."""
    session = _get_session()
    try:
        where_clauses = ["a.is_processed = TRUE", "a.importance >= :min_imp"]
        params = {"limit": limit, "min_imp": min_importance}

        if today_only:
            where_clauses.append("a.collected_at >= NOW() - INTERVAL '24 hours'")
            
        where_sql = " AND ".join(where_clauses)
        
        # 태그 필터링 (HAVING 절에서 처리)
        having_sql = ""
        if tag_filter:
            having_sql = "HAVING :tag = ANY(array_agg(t.category))"
            params["tag"] = tag_filter

        # COALESCE를 사용하여 날짜 정보가 없는 기사도 적절한 위치에 정렬되도록 보완
        if sort_by == "date":
            order_sql = "COALESCE(a.published_at, a.collected_at) DESC"
        else:
            order_sql = "a.importance DESC, COALESCE(a.published_at, a.collected_at) DESC"

        query = f"""
            SELECT a.id, a.title, a.url, a.source, a.summary, a.key_points, a.sentiment, a.importance, 
                   a.published_at, a.collected_at, a.thumbnail_url,
                   array_agg(t.category) AS tags
            FROM articles a
            LEFT JOIN tags t ON a.id = t.article_id
            WHERE {where_sql}
            GROUP BY a.id
            {having_sql}
            ORDER BY {order_sql}
            LIMIT :limit
        """
        
        result = session.execute(text(query), params)
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


# ---- 시스템 관리 (Sources & Initialization) -------------------

def init_news_sources():
    """뉴스 수집 소스가 없을 경우 초기 기여 데이터를 삽입합니다."""
    session = _get_session()
    try:
        # 테이블이 이미 있는지 확인 (스키마 파일 외 인라인 체크)
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS news_sources (
                id SERIAL PRIMARY KEY,
                name TEXT UNIQUE NOT NULL,
                url TEXT NOT NULL,
                label TEXT NOT NULL,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """))
        
        # 중복 데이터 자동 청소 (Migrate: 중복 제거)
        session.execute(text("""
            DELETE FROM news_sources a USING news_sources b 
            WHERE a.id > b.id AND a.url = b.url;
        """))

        # 기존 테이블 대응: url에 유니크 인덱스 추가
        session.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS idx_news_sources_url ON news_sources(url);"))
        
        # 데이터가 하나도 없을 경우에만 초기 데이터 삽입
        count = session.execute(text("SELECT count(*) FROM news_sources")).scalar()
        if count == 0:
            initial_sources = [
                ("ieee_humanoids", "https://spectrum.ieee.org/feeds/topic/humanoid-robots.rss", "IEEE Spectrum - Humanoids"),
                ("robot_report_mobile", "https://www.therobotreport.com/category/robotics-topics/mobile-robots/feed/", "The Robot Report - Mobile"),
                ("techcrunch_robotics", "https://techcrunch.com/category/robotics/feed/", "TechCrunch - Robotics"),
                ("the_robot_report", "https://www.therobotreport.com/feed/", "The Robot Report"),
                ("mit_news_robotics", "https://news.mit.edu/topic/robotics/rss", "MIT News - Robotics")
            ]
            for name, url, label in initial_sources:
                session.execute(text("""
                    INSERT INTO news_sources (name, url, label) 
                    VALUES (:name, :url, :label)
                """), {"name": name, "url": url, "label": label})
            session.commit()
            logger.info("기본 뉴스 소스 초기화 완료")
    except Exception as e:
        logger.error(f"뉴스 소스 초기화 실패: {e}")
    finally:
        session.close()

def get_news_sources(active_only=False) -> list[dict]:
    """등록된 뉴스 소스 목록을 가져옵니다."""
    session = _get_session()
    try:
        query = "SELECT * FROM news_sources"
        if active_only:
            query += " WHERE is_active = TRUE"
        query += " ORDER BY id ASC"
        result = session.execute(text(query)).fetchall()
        return [dict(row._mapping) for row in result]
    finally:
        session.close()

def add_news_source(name: str, url: str, label: str):
    """새로운 뉴스 수집 소스를 추가합니다."""
    session = _get_session()
    try:
        session.execute(text("""
            INSERT INTO news_sources (name, url, label)
            VALUES (:name, :url, :label)
            ON CONFLICT (name) DO UPDATE SET url = EXCLUDED.url, label = EXCLUDED.label
        """), {"name": name, "url": url, "label": label})
        session.commit()
    finally:
        session.close()

def delete_news_source(source_id: int):
    """뉴스 수집 소스를 삭제합니다."""
    session = _get_session()
    try:
        session.execute(text("DELETE FROM news_sources WHERE id = :id"), {"id": source_id})
        session.commit()
    finally:
        session.close()

def toggle_news_source(source_id: int, is_active: bool):
    """뉴스 수집 소스의 활성화 상태를 변경합니다."""
    session = _get_session()
    try:
        session.execute(text("UPDATE news_sources SET is_active = :is_active WHERE id = :id"),
                        {"is_active": is_active, "id": source_id})
        session.commit()
    finally:
        session.close()

def clear_all_data(reset_sources=False):
    """DB의 모든 기사와 지식 관계 데이터를 초기화합니다. (주의!)"""
    session = _get_session()
    try:
        # 외래 키 제약 조건 등으로 인해 순서대로 삭제
        session.execute(text("TRUNCATE TABLE news_sources, articles, entities, article_entities, relations, tags, pipeline_logs RESTART IDENTITY CASCADE"))
        session.commit()
        
        # Redis 중복 방지 캐시도 비우기
        if redis.Redis:
            try:
                r = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
                r.flushdb()
                logger.info("Redis 듀플리케이터 초기화 완료")
            except Exception:
                pass
        
        # 소스 초기화가 필요한 경우 재등록
        if reset_sources:
            init_news_sources()
            
        logger.info("데이터베이스 전체 초기화 완료")
    except Exception as e:
        logger.error(f"데이터베이스 초기화 실패: {e}")
        session.rollback()
    finally:
        session.close()

# ---- 유튜브 소스 CRUD --------------------------------------
def get_youtube_sources() -> list[dict]:
    session = _get_session()
    try:
        result = session.execute(text("SELECT id, name, channel_url, label, is_active FROM youtube_sources ORDER BY id"))
        return [{"id": r[0], "name": r[1], "channel_url": r[2], "label": r[3], "is_active": r[4]} for r in result]
    finally:
        session.close()

def add_youtube_source(name: str, channel_url: str, label: str):
    session = _get_session()
    try:
        session.execute(text("""
            INSERT INTO youtube_sources (name, channel_url, label) 
            VALUES (:n, :u, :l) 
            ON CONFLICT(channel_url) DO UPDATE SET name = EXCLUDED.name, label = EXCLUDED.label
            ON CONFLICT(name) DO UPDATE SET channel_url = EXCLUDED.channel_url, label = EXCLUDED.label
        """), {"n": name, "u": channel_url, "l": label})
        session.commit()
    finally:
        session.close()

def toggle_youtube_source(source_id: int, is_active: bool):
    session = _get_session()
    try:
        session.execute(text("UPDATE youtube_sources SET is_active = :i WHERE id = :id"), {"i": is_active, "id": source_id})
        session.commit()
    finally:
        session.close()

def delete_youtube_source(source_id: int):
    session = _get_session()
    try:
        session.execute(text("DELETE FROM youtube_sources WHERE id = :id"), {"id": source_id})
        session.commit()
    finally:
        session.close()

# ---- 추천 소스(Auto-Discovery) CRUD --------------------------
def get_recommended_sources() -> list[dict]:
    session = _get_session()
    try:
        result = session.execute(text("SELECT id, url, source_type, label, reason, status FROM recommended_sources WHERE status='pending' ORDER BY id DESC"))
        return [{"id": r[0], "url": r[1], "source_type": r[2], "label": r[3], "reason": r[4], "status": r[5]} for r in result]
    finally:
        session.close()

def add_recommended_source(url: str, source_type: str, label: str, reason: str):
    session = _get_session()
    try:
        session.execute(text("""
            INSERT INTO recommended_sources (url, source_type, label, reason)
            VALUES (:u, :t, :l, :r) ON CONFLICT(url) DO NOTHING
        """), {"u": url, "t": source_type, "l": label, "r": reason})
        session.commit()
    finally:
        session.close()

def update_recommended_source_status(req_id: int, status: str):
    session = _get_session()
    try:
        session.execute(text("UPDATE recommended_sources SET status = :s WHERE id = :id"), {"s": status, "id": req_id})
        session.commit()
    finally:
        session.close()
