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
        
        # Self-Healing: 다중 도메인 지원 마이그레이션
        try:
            with _engine.connect() as conn:
                # 0. domains 테이블 및 기본 도메인(홈로봇) 자동 생성
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS domains (
                        key          TEXT PRIMARY KEY,
                        name         TEXT UNIQUE NOT NULL,
                        keywords     TEXT[],
                        system_prompt TEXT,
                        created_at   TIMESTAMPTZ DEFAULT NOW()
                    );
                """))
                
                conn.execute(text("""
                    INSERT INTO domains (key, name, keywords)
                    VALUES ('home_robot', '홈로봇', ARRAY['home robot', 'domestic robot', 'service robot', 'lg cloi', 'samsung robot'])
                    ON CONFLICT (key) DO NOTHING;
                """))

                # 기존 테이블들에 domain_key 컬럼 추가 및 백필
                tables_to_migrate = ["articles", "news_sources", "youtube_sources", "recommended_sources", "pipeline_logs"]
                for tbl in tables_to_migrate:
                    conn.execute(text(f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS domain_key TEXT DEFAULT 'home_robot';"))
                    conn.execute(text(f"UPDATE {tbl} SET domain_key = 'home_robot' WHERE domain_key IS NULL;"))

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
                
                # 새 기능: 시스템 설정 테이블 생성
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS system_settings (
                        key TEXT PRIMARY KEY,
                        value TEXT
                    );
                """))
                
                # 초기 설정값 삽입
                conn.execute(text("""
                    INSERT INTO system_settings (key, value)
                    VALUES ('analysis_batch_limit', '100')
                    ON CONFLICT (key) DO NOTHING;
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


def get_active_model_name() -> str:
    """현재 LM Studio에 실제로 로드되어 있는 모델명을 반환하여 중복 로딩 에러를 방지합니다."""
    try:
        available = get_available_lms_models()
        if available:
            # 현재 서버에 로드된 첫 번째 모델명을 반환
            return available[0]
    except Exception as e:
        logger.debug(f"서버 모델 목록 확인 실패 (폴백 사용): {e}")
        
    # 서버 확인 실패 시 환경변수 또는 기본값 사용
    return os.getenv("LMS_MODEL_NAME", "gemma-4-26b")


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
    domain_key = getattr(article, "domain_key", "home_robot")

    # 1. 시맨틱 중복 체크 (선택 사항)
    is_dedup_enabled = get_system_setting("semantic_dedup_enabled", "True") == "True"
    if is_dedup_enabled and embedding:
        # 최근 3일 이내의 유사 기사 검색
        threshold_str = get_system_setting("semantic_dedup_threshold", "0.95")
        threshold = float(threshold_str) if threshold_str else 0.95
        
        dup_article = _check_semantic_duplicate(embedding, threshold=threshold, days=3, domain_key=domain_key)
        if dup_article:
            logger.info(f"[스킵] 유사 기사 발견: '{article.title}' <-> '{dup_article['title']}' (유사도: {dup_article['similarity']:.3f})")
            return None

    session = _get_session()
    try:
        article_id = str(uuid.uuid4())
        embedding_str = f"[{','.join(str(v) for v in embedding)}]" if embedding else None

        session.execute(text("""
            INSERT INTO articles (id, domain_key, url_hash, url, source, source_type, title, content,
                                  author, published_at, thumbnail_url, embedding)
            VALUES (:id, :domain_key, :url_hash, :url, :source, :source_type, :title, :content,
                    :author, :published_at, :thumbnail_url, CAST(:embedding AS vector))
            ON CONFLICT (url_hash) DO NOTHING
        """), {
            "id": article_id,
            "domain_key": domain_key,
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


def _check_semantic_duplicate(embedding: list[float], threshold: float = 0.95, days: int = 3, domain_key: str = "home_robot") -> Optional[dict]:
    """
    주어진 임베딩과 유사한 기사가 최근 N일 이내에 존재하는지 확인합니다.
    """
    if not embedding: return None
    
    session = _get_session()
    try:
        # 코사인 유사도를 사용하여 중복 체크 (1 - distance)
        # pgvector의 <=> 연산자는 코사인 거리를 의미하므로, 1 - 거리 = 유사도
        query = text(f"""
            SELECT title, 1 - (embedding <=> :embedding) as similarity
            FROM articles
            WHERE domain_key = :domain_key
            AND created_at >= NOW() - INTERVAL '{days} days'
            AND 1 - (embedding <=> :embedding) >= :threshold
            ORDER BY similarity DESC
            LIMIT 1
        """)
        
        result = session.execute(query, {
            "embedding": f"[{','.join(str(v) for v in embedding)}]",
            "threshold": threshold,
            "domain_key": domain_key
        }).fetchone()
        
        if result:
            return {"title": result[0], "similarity": result[1]}
        return None
    except Exception as e:
        logger.error(f"중복 체크 중 오류: {e}")
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


def semantic_search(query: str, top_k: int = 10, domain_key: str = "home_robot") -> list[dict]:
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
            SELECT a.id, a.title, a.url, a.source, a.summary, a.key_points, a.sentiment, a.importance, 
                   a.published_at, a.collected_at, a.thumbnail_url,
                   array_agg(t.category) AS tags,
                   1 - (a.embedding <=> CAST(:embedding AS vector)) AS similarity
            FROM articles a
            LEFT JOIN tags t ON a.id = t.article_id
            WHERE a.domain_key = :domain_key AND a.is_processed = TRUE AND a.embedding IS NOT NULL
            GROUP BY a.id
            ORDER BY a.embedding <=> CAST(:embedding AS vector)
            LIMIT :top_k
        """), {"embedding": embedding_str, "top_k": top_k, "domain_key": domain_key})

        rows = result.fetchall()
        return [dict(row._mapping) for row in rows]
    finally:
        session.close()


def get_system_setting(key: str, default: str = None) -> str:
    """시스템 설정값을 가져옵니다."""
    session = _get_session()
    try:
        result = session.execute(text("SELECT value FROM system_settings WHERE key = :key"), {"key": key})
        row = result.fetchone()
        return row[0] if row else default
    except Exception:
        return default
    finally:
        session.close()


def set_system_setting(key: str, value: str) -> None:
    """시스템 설정값을 저장합니다."""
    session = _get_session()
    try:
        session.execute(text("""
            INSERT INTO system_settings (key, value)
            VALUES (:key, :value)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """), {"key": key, "value": str(value)})
        session.commit()
    except Exception as e:
        logger.error(f"설정 저장 실패: {e}")
        session.rollback()
    finally:
        session.close()


def get_unprocessed_articles(limit: int = 100, domain_key: str = None) -> list[dict]:
    """LLM 분석이 아직 안 된 기사 목록을 반환합니다."""
    session = _get_session()
    try:
        query = """
            SELECT id, title, content, source
            FROM articles
            WHERE is_processed = FALSE
        """
        params = {}
        if domain_key:
            query += " AND domain_key = :domain_key"
            params["domain_key"] = domain_key
            
        query += " ORDER BY collected_at ASC"
        if limit is not None:
            query += " LIMIT :limit"
            params["limit"] = limit
        
        result = session.execute(text(query), params)
        return [dict(row._mapping) for row in result.fetchall()]
    finally:
        session.close()


def get_pipeline_stats(domain_key: str = "home_robot") -> dict:
    """모니터링 대시보드용 파이프라인 통계를 반환합니다."""
    session = _get_session()
    try:
        stats = {}

        result = session.execute(text("""
            SELECT
                COUNT(*) FILTER (WHERE collected_at::date = CURRENT_DATE) AS today_total,
                COUNT(*) FILTER (WHERE is_processed = TRUE AND processed_at::date = CURRENT_DATE) AS today_processed,
                COUNT(*) FILTER (WHERE is_processed = TRUE) AS total_processed,
                COUNT(*) FILTER (WHERE is_processed = FALSE) AS pending,
                COUNT(*) AS total
            FROM articles
            WHERE domain_key = :domain_key
        """), {"domain_key": domain_key})
        row = result.fetchone()
        stats.update(dict(row._mapping))

        result2 = session.execute(text("""
            SELECT source, COUNT(*) AS count, MAX(collected_at) AS last_collected
            FROM articles
            WHERE domain_key = :domain_key
            GROUP BY source
            ORDER BY last_collected DESC
        """), {"domain_key": domain_key})
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
        import httpx
        lms_api_base = os.getenv("LMS_API_BASE", "http://localhost:1234/v1")
        # 가벼운 HTTP GET 요청으로 모델 목록 엔드포인트 확인 (3초 타임아웃)
        with httpx.Client(timeout=3.0) as client:
            resp = client.get(f"{lms_api_base}/models")
            if resp.status_code == 200:
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


def get_all_relations(domain_key: str = "home_robot") -> list[dict]:
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
            JOIN articles a ON r.article_id = a.id
            WHERE a.domain_key = :domain_key
        """), {"domain_key": domain_key})
        return [dict(row._mapping) for row in result.fetchall()]
    finally:
        session.close()


def get_latest_articles(limit: int = 50, min_importance: float = 0.0, today_only: bool = False, tag_filter: str = None, sort_by: str = "date", domain_key: str = "home_robot") -> list[dict]:
    """분석 완료된 최신 기사를 가져옵니다."""
    session = _get_session()
    try:
        where_clauses = ["a.is_processed = TRUE", "a.importance >= :min_imp", "a.domain_key = :domain_key"]
        params = {"limit": limit, "min_imp": min_importance, "domain_key": domain_key}

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

def get_news_sources(active_only=False, domain_key: str = "home_robot") -> list[dict]:
    """등록된 뉴스 소스 목록을 가져옵니다."""
    session = _get_session()
    try:
        query = "SELECT * FROM news_sources WHERE domain_key = :domain_key"
        if active_only:
            query += " AND is_active = TRUE"
        query += " ORDER BY id ASC"
        result = session.execute(text(query), {"domain_key": domain_key}).fetchall()
        return [dict(row._mapping) for row in result]
    finally:
        session.close()

def add_news_source(name: str, url: str, label: str, domain_key: str = "home_robot"):
    """새로운 뉴스 수집 소스를 추가합니다."""
    session = _get_session()
    try:
        session.execute(text("""
            INSERT INTO news_sources (domain_key, name, url, label)
            VALUES (:domain_key, :name, :url, :label)
            ON CONFLICT (name) DO UPDATE SET url = EXCLUDED.url, label = EXCLUDED.label, domain_key = EXCLUDED.domain_key
        """), {"name": name, "url": url, "label": label, "domain_key": domain_key})
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
def get_youtube_sources(domain_key: str = "home_robot") -> list[dict]:
    session = _get_session()
    try:
        result = session.execute(text("SELECT id, name, channel_url, label, is_active FROM youtube_sources WHERE domain_key = :domain_key ORDER BY id"), {"domain_key": domain_key})
        return [{"id": r[0], "name": r[1], "channel_url": r[2], "label": r[3], "is_active": r[4]} for r in result]
    finally:
        session.close()

def add_youtube_source(name: str, channel_url: str, label: str, domain_key: str = "home_robot"):
    session = _get_session()
    try:
        session.execute(text("""
            INSERT INTO youtube_sources (domain_key, name, channel_url, label) 
            VALUES (:domain_key, :n, :u, :l) 
            ON CONFLICT(channel_url) DO UPDATE SET name = EXCLUDED.name, label = EXCLUDED.label, domain_key = EXCLUDED.domain_key
            ON CONFLICT(name) DO UPDATE SET channel_url = EXCLUDED.channel_url, label = EXCLUDED.label, domain_key = EXCLUDED.domain_key
        """), {"n": name, "u": channel_url, "l": label, "domain_key": domain_key})
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
def get_recommended_sources(domain_key: str = "home_robot") -> list[dict]:
    session = _get_session()
    try:
        result = session.execute(text("SELECT id, url, source_type, label, reason, status FROM recommended_sources WHERE domain_key = :domain_key AND status='pending' ORDER BY id DESC"), {"domain_key": domain_key})
        return [{"id": r[0], "url": r[1], "source_type": r[2], "label": r[3], "reason": r[4], "status": r[5]} for r in result]
    finally:
        session.close()

def add_recommended_source(url: str, source_type: str, label: str, reason: str, domain_key: str = "home_robot"):
    session = _get_session()
    try:
        session.execute(text("""
            INSERT INTO recommended_sources (domain_key, url, source_type, label, reason)
            VALUES (:domain_key, :u, :t, :l, :r) ON CONFLICT(url) DO NOTHING
        """), {"domain_key": domain_key, "u": url, "t": source_type, "l": label, "r": reason})
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


# ---- 도메인 CRUD API -----------------------------------------
def get_domains() -> list[dict]:
    """등록된 모든 도메인 목록을 가져옵니다."""
    session = _get_session()
    try:
        result = session.execute(text("SELECT key, name, keywords, system_prompt, created_at FROM domains ORDER BY created_at ASC"))
        return [{"key": r[0], "name": r[1], "keywords": r[2] or [], "system_prompt": r[3], "created_at": r[4]} for r in result.fetchall()]
    finally:
        session.close()


def get_domain(key: str) -> Optional[dict]:
    """특정 도메인의 정보를 가져옵니다."""
    session = _get_session()
    try:
        result = session.execute(text("SELECT key, name, keywords, system_prompt, created_at FROM domains WHERE key = :key"), {"key": key}).fetchone()
        if result:
            return {"key": result[0], "name": result[1], "keywords": result[2] or [], "system_prompt": result[3], "created_at": result[4]}
        return None
    finally:
        session.close()


def add_domain(key: str, name: str, keywords: list[str], system_prompt: str = None):
    """새로운 도메인을 추가합니다."""
    session = _get_session()
    try:
        session.execute(text("""
            INSERT INTO domains (key, name, keywords, system_prompt)
            VALUES (:key, :name, :keywords, :system_prompt)
            ON CONFLICT (key) DO UPDATE 
            SET name = EXCLUDED.name, keywords = EXCLUDED.keywords, system_prompt = EXCLUDED.system_prompt
        """), {"key": key.strip(), "name": name.strip(), "keywords": keywords, "system_prompt": system_prompt})
        session.commit()
    finally:
        session.close()


def delete_domain(key: str):
    """도메인을 삭제합니다. 연쇄 삭제 처리를 함께 진행합니다."""
    session = _get_session()
    try:
        session.execute(text("DELETE FROM news_sources WHERE domain_key = :key"), {"key": key})
        session.execute(text("DELETE FROM youtube_sources WHERE domain_key = :key"), {"key": key})
        session.execute(text("DELETE FROM recommended_sources WHERE domain_key = :key"), {"key": key})
        session.execute(text("DELETE FROM pipeline_logs WHERE domain_key = :key"), {"key": key})
        session.execute(text("DELETE FROM articles WHERE domain_key = :key"), {"key": key})
        session.execute(text("DELETE FROM domains WHERE key = :key"), {"key": key})
        session.commit()
    finally:
        session.close()


def discover_rss_feed_static(url: str) -> Optional[str]:
    """
    등록 이관 시점에 한해 1회성으로 일반 HTML 내의 메타태그 및 피드 링크에서 표준 XML RSS 주소를 역추적하고 자동 변환합니다.
    표준 RSS를 식별할 수 없을 경우 None을 반환하여 차단합니다.
    """
    if not url:
        return None
        
    low_url = url.lower()
    # 이미 명시적인 피드 주소 형식인 경우 즉시 그대로 사용
    if low_url.endswith((".xml", ".rss", ".atom")) or "/feed" in low_url or ("rss" in low_url and "feed" in low_url):
        return url

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
    }

    try:
        from bs4 import BeautifulSoup
        from urllib.parse import urljoin
        
        with httpx.Client(headers=headers, proxy=None, trust_env=False, timeout=10.0, follow_redirects=True) as client:
            resp = client.get(url)
            if resp.status_code != 200:
                return None
            
            # 이미 피드 XML 내용이라면 그대로 반환
            content_type = resp.headers.get("content-type", "").lower()
            if "xml" in content_type or "rss" in content_type or "atom" in content_type:
                return url
                
            soup = BeautifulSoup(resp.text, "lxml")
            
            # 1. <link rel="alternate" ...> 메타태그 탐색
            for link in soup.find_all("link", rel="alternate"):
                ltype = link.get("type", "").lower()
                if "rss+xml" in ltype or "atom+xml" in ltype or "xml" in ltype:
                    href = link.get("href")
                    if href:
                        discovered_url = urljoin(url, href)
                        logger.info(f"   💡 [RSS Auto-Discovery Static] 등록 시점 진짜 RSS 피드 발견: {discovered_url}")
                        return discovered_url
            
            # 2. <a> 태그 중 href에 'rss' 또는 'feed'가 포함된 명시적 피드 링크 탐색
            for a in soup.find_all("a", href=True):
                href = a.get("href")
                low_href = href.lower()
                if "rss" in low_href or "feed" in low_href or low_href.endswith(".xml"):
                    if "feedly.com" not in low_href and "feedburner.com" not in low_href:
                        discovered_url = urljoin(url, href)
                        logger.info(f"   💡 [RSS Auto-Discovery Static] a 태그에서 RSS 피드 발견: {discovered_url}")
                        return discovered_url
                        
    except Exception as e:
        logger.warning(f"등록 시점 RSS 피드 자동 발견 중 예외 발생 ({url}): {e}")

    return None


def inject_recommended_sources(domain_key: str, selected_urls: list[str]) -> tuple[int, int]:
    """
    추천 소스 중 사용자가 선택한 URL들을 실제 수집 소스 테이블로 일괄 이관합니다.
    이관 시 'news' 소스에 한해 진짜 RSS XML 피드 주소로 1회 정제하여 DB에 안전하게 적재합니다.
    Returns: (news_added, youtube_added)
    """
    if not selected_urls:
        return 0, 0
    
    session = _get_session()
    news_added = 0
    youtube_added = 0
    try:
        # 선택된 URL에 해당하는 추천 소스 조회
        result = session.execute(text("""
            SELECT url, source_type, label, reason 
            FROM recommended_sources 
            WHERE domain_key = :domain_key AND url IN :urls AND status = 'pending'
        """), {"domain_key": domain_key, "urls": tuple(selected_urls)})
        
        sources = result.fetchall()
        
        for url, source_type, label, reason in sources:
            label = label or "추천 소스"
            
            # 중복 방지를 위한 name 생성 (소문자, 알파벳/숫자 외 제거)
            import re
            name_clean = re.sub(r'[^a-zA-Z0-9]', '_', label.lower()).strip('_')
            if not name_clean:
                name_clean = "discovered_source_" + str(uuid.uuid4())[:8]
                
            if source_type == 'news':
                # 1회성 진짜 RSS 피드 URL 역추적 변환 및 검증
                rss_url = discover_rss_feed_static(url)
                if not rss_url:
                    logger.warning(f"⚠️ [RSS 검증 실패] '{label}' 소스에서 유효한 RSS 피드를 역추적할 수 없어 등록을 차단합니다: {url}")
                    # 승인 대기 목록에서 제외하며 거절(rejected) 상태로 이관 실패 기록
                    session.execute(text("""
                        UPDATE recommended_sources 
                        SET status = 'rejected', reason = CONCAT(reason, ' (이관 실패: RSS XML 피드 전무)')
                        WHERE domain_key = :domain_key AND url = :url
                    """), {"domain_key": domain_key, "url": url})
                    continue
                
                # news_sources에 존재 여부 체크 (변환된 rss_url 기준)
                dup = session.execute(text("SELECT id FROM news_sources WHERE domain_key = :dk AND (url = :url OR name = :name)"), 
                                      {"dk": domain_key, "url": rss_url, "name": name_clean}).fetchone()
                if not dup:
                    session.execute(text("""
                        INSERT INTO news_sources (domain_key, name, url, label, is_active)
                        VALUES (:domain_key, :name, :url, :label, TRUE)
                    """), {"domain_key": domain_key, "name": name_clean, "url": rss_url, "label": label})
                    news_added += 1
            else:
                # youtube_sources에 존재 여부 체크
                dup = session.execute(text("SELECT id FROM youtube_sources WHERE domain_key = :dk AND (channel_url = :url OR name = :name)"), 
                                      {"dk": domain_key, "url": url, "name": name_clean}).fetchone()
                if not dup:
                    session.execute(text("""
                        INSERT INTO youtube_sources (domain_key, name, channel_url, label, is_active)
                        VALUES (:domain_key, :name, :url, :label, TRUE)
                    """), {"domain_key": domain_key, "name": name_clean, "url": url, "label": label})
                    youtube_added += 1
                    
            # 상태를 approved로 업데이트
            session.execute(text("""
                UPDATE recommended_sources 
                SET status = 'approved' 
                WHERE domain_key = :domain_key AND url = :url
            """), {"domain_key": domain_key, "url": url})
            
        session.commit()
        return news_added, youtube_added
    except Exception as e:
        session.rollback()
        logger.error(f"추천 소스 이관 실패: {e}")
        return 0, 0
    finally:
        session.close()


def get_instant_seed_sources(domain_key: str) -> list[dict]:
    """
    인터넷 실시간 검색 및 LLM을 사용하여 현재 도메인 전용 시드 소스들을 즉석에서 발굴하고 반환합니다.
    """
    from engine.source_explorer import discover_sources
    try:
        # AI 자율 소스 발굴 프로세스 즉각 구동
        discover_sources(domain_key=domain_key)
    except Exception as e:
        logger.error(f"실시간 AI 소스 탐색 구동 실패: {e}")
        
    # 방금 수집된 추천 소스 반환
    return get_recommended_sources(domain_key=domain_key)

