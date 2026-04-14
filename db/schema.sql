-- pgvector 확장 활성화
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS vector;

-- ============================
-- 수집된 원문 기사 / 영상
-- ============================
CREATE TABLE IF NOT EXISTS articles (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    url_hash        TEXT UNIQUE NOT NULL,           -- SHA-256(url), 중복 방지 키
    url             TEXT NOT NULL,
    source          TEXT NOT NULL,                  -- 예: "ieee_spectrum", "youtube_boston_dynamics"
    source_type     TEXT NOT NULL,                  -- "news" | "video"
    title           TEXT NOT NULL,
    content         TEXT,                           -- 원문 본문 또는 자막
    author          TEXT,
    published_at    TIMESTAMPTZ,
    collected_at    TIMESTAMPTZ DEFAULT NOW(),

    -- LLM 분석 결과
    summary         TEXT,                           -- 3줄 요약 (한국어)
    sentiment       TEXT CHECK (sentiment IN ('positive', 'neutral', 'negative')),
    importance      FLOAT CHECK (importance BETWEEN 0 AND 10),
    is_processed    BOOLEAN DEFAULT FALSE,          -- LLM 처리 완료 여부
    processed_at    TIMESTAMPTZ,

    -- 벡터 임베딩 (pgvector)
    embedding       VECTOR(768)
);

CREATE INDEX IF NOT EXISTS idx_articles_source ON articles(source);
CREATE INDEX IF NOT EXISTS idx_articles_published ON articles(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_articles_processed ON articles(is_processed);
CREATE INDEX IF NOT EXISTS idx_articles_embedding ON articles USING ivfflat (embedding vector_cosine_ops);

-- ============================
-- 추출된 엔티티 (기업, 기술, 기관)
-- ============================
CREATE TABLE IF NOT EXISTS entities (
    id      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name    TEXT UNIQUE NOT NULL,
    type    TEXT NOT NULL CHECK (type IN ('company', 'technology', 'institution', 'product')),
    aliases TEXT[],                                 -- 동의어/약어 목록
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(type);
CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name);

-- ============================
-- 기사-엔티티 연결 (N:M)
-- ============================
CREATE TABLE IF NOT EXISTS article_entities (
    article_id  UUID REFERENCES articles(id) ON DELETE CASCADE,
    entity_id   UUID REFERENCES entities(id) ON DELETE CASCADE,
    PRIMARY KEY (article_id, entity_id)
);

-- ============================
-- 엔티티 간 관계 (지식 그래프 엣지)
-- ============================
CREATE TABLE IF NOT EXISTS relations (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    article_id  UUID REFERENCES articles(id) ON DELETE CASCADE,
    subject_id  UUID REFERENCES entities(id),
    predicate   TEXT NOT NULL,                      -- 예: "개발", "인수", "탑재", "협력", "발표"
    object_id   UUID REFERENCES entities(id),
    confidence  FLOAT DEFAULT 1.0,                  -- LLM 확신도 (0.0~1.0)
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_relations_subject ON relations(subject_id);
CREATE INDEX IF NOT EXISTS idx_relations_object ON relations(object_id);
CREATE INDEX IF NOT EXISTS idx_relations_predicate ON relations(predicate);

-- ============================
-- 기사 다차원 태그
-- ============================
CREATE TABLE IF NOT EXISTS tags (
    article_id  UUID REFERENCES articles(id) ON DELETE CASCADE,
    category    TEXT NOT NULL,                      -- 예: "SLAM", "배터리", "AI 모델", "규제"
    PRIMARY KEY (article_id, category)
);

CREATE INDEX IF NOT EXISTS idx_tags_category ON tags(category);

-- ============================
-- 파이프라인 실행 로그 (모니터링)
-- ============================
CREATE TABLE IF NOT EXISTS pipeline_logs (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_at      TIMESTAMPTZ DEFAULT NOW(),
    source      TEXT,                               -- 어떤 소스를 수집했는지
    status      TEXT CHECK (status IN ('success', 'failure', 'partial')),
    fetched     INT DEFAULT 0,                      -- 수집 시도 건수
    skipped     INT DEFAULT 0,                      -- 중복 스킵 건수
    saved       INT DEFAULT 0,                      -- DB 저장 건수
    error_msg   TEXT
);
-- ============================
-- 뉴스 수집 소스 관리
-- ============================
CREATE TABLE IF NOT EXISTS news_sources (
    id          SERIAL PRIMARY KEY,
    name        TEXT UNIQUE NOT NULL,               -- 시스템 내부 식별자 (예: "techcrunch")
    url         TEXT NOT NULL,                      -- RSS 피드 주소
    label       TEXT NOT NULL,                      -- UI 표시용 이름 (예: "TechCrunch - Robotics")
    is_active   BOOLEAN DEFAULT TRUE,               -- 수집 활성화 여부
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_news_sources_active ON news_sources(is_active);
