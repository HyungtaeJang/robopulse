"""
app.py - RoboPulse 메인 Streamlit 대시보드 (데모 모드 지원)
DB/Redis가 없어도 샘플 데이터로 UI 확인 가능합니다.
"""
import logging
import os
import sys
from datetime import datetime, timedelta
import random

import streamlit as st
import plotly.graph_objects as go
import networkx as nx

from db.vector_store import (
    check_all_connections, get_pipeline_stats, get_latest_articles, 
    get_all_relations, semantic_search, get_all_entities_for_graph
)
from scheduler.pipeline_scheduler import (
    start_scheduler, get_scheduler_status, job_fetch_news, job_fetch_videos
)
from engine.graph_builder import get_graph, rebuild_from_db

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 모델 식별자 (사용자 지정)
LMS_MODEL_NAME = os.getenv("LMS_MODEL_NAME", "lmstudio-community/gemma-4-26b-a4b-it")

# ---- 데모 샘플 데이터 ----------------------------------------
DEMO_ARTICLES = [
    {
        "title": "Boston Dynamics, Spot 차세대 모델에 Tesla 센서 기술 탑재 예정",
        "url": "https://spectrum.ieee.org/boston-dynamics-spot-next-gen",
        "source": "ieee_spectrum", "sentiment": "positive", "importance": 9.2,
        "summary": "Boston Dynamics가 Spot 로봇의 차세대 모델에 Tesla의 FSD 카메라 센서를 탑재할 계획을 발표했다. 이는 홈로봇 SLAM 성능을 기존 대비 3배 향상 시킬 것으로 예상된다. 업계 전문가들은 이번 파트너십이 서비스 로봇 시장의 판도를 바꿀 것이라 전망한다.",
        "tags": ["SLAM", "센서 기술", "파트너십", "Humanoid"],
        "published_at": datetime.now() - timedelta(hours=2),
    },
    {
        "title": "삼성전자, 2027년 가정용 AI 로봇 '볼리' 양산 계획 확정",
        "url": "https://techcrunch.com/samsung-bali-home-robot-2027",
        "source": "techcrunch_robotics", "sentiment": "positive", "importance": 8.7,
        "summary": "삼성전자가 2024년 CES에서 공개한 가정용 로봇 '볼리'의 양산 일정을 2027년으로 확정했다. 초기 출시 가격은 300만원대로, B2C 홈로봇 시장 진출을 본격화할 것으로 보인다. 볼리는 온디바이스 AI와 삼성 스마트홈 생태계와 연동된다.",
        "tags": ["가정용 로봇", "삼성", "온디바이스 AI", "제품 출시"],
        "published_at": datetime.now() - timedelta(hours=5),
    },
    {
        "title": "MIT, 소프트 액추에이터 기반 의료용 로봇 팔 논문 발표",
        "url": "https://news.mit.edu/soft-actuator-medical-robot-2026",
        "source": "mit_news_robotics", "sentiment": "neutral", "importance": 7.1,
        "summary": "MIT CSAIL 연구팀이 소프트 공압 액추에이터를 활용한 새로운 의료 보조 로봇 팔 설계를 Nature에 게재했다. 기존 리지드 방식 대비 안전성이 40% 향상되었으며, 고령자 케어 로봇에 적용 가능성이 높다.",
        "tags": ["액추에이터", "소프트 로보틱스", "의료 로봇", "논문"],
        "published_at": datetime.now() - timedelta(hours=9),
    },
    {
        "title": "EU, 유럽 내 자율 로봇 규제 초안 발표 — 인증제 의무화",
        "url": "https://wired.com/eu-autonomous-robot-regulation-2026",
        "source": "wired_robots", "sentiment": "negative", "importance": 6.5,
        "summary": "EU 집행위원회가 자율 이동 로봇에 대한 CE 인증 의무화를 골자로 한 규제 초안을 공개했다. 2028년부터 발효 예정이며, 중소 로봇 기업의 시장 진입 장벽이 높아질 것으로 우려된다.",
        "tags": ["규제", "EU", "인증", "시장 영향"],
        "published_at": datetime.now() - timedelta(hours=14),
    },
    {
        "title": "Agility Robotics Digit 2.0, 아마존 물류센터 600대 배치 완료",
        "url": "https://therobotreport.com/agility-digit-amazon-600-units",
        "source": "the_robot_report", "sentiment": "positive", "importance": 9.5,
        "summary": "Agility Robotics의 Humanoid 로봇 Digit 2.0이 아마존 풀필먼트 센터 12개소에 총 600대 배치를 완료했다. 일 평균 처리량이 기존 대비 28% 향상되었으며, 2027년까지 추가 5,000대 발주 계획이 확정됐다.",
        "tags": ["Humanoid", "물류 자동화", "아마존", "대량 배치"],
        "published_at": datetime.now() - timedelta(hours=1),
    },
]

DEMO_GRAPH_NODES = [
    ("Boston Dynamics", "company"), ("Tesla", "company"), ("Samsung", "company"),
    ("Agility Robotics", "company"), ("Amazon", "company"), ("MIT", "institution"),
    ("SLAM", "technology"), ("소프트 액추에이터", "technology"), ("FSD 카메라", "technology"),
    ("온디바이스 AI", "technology"), ("Spot", "product"), ("Digit 2.0", "product"),
    ("볼리", "product"),
]

DEMO_GRAPH_EDGES = [
    ("Boston Dynamics", "Spot", "개발"), ("Boston Dynamics", "Tesla", "협력"),
    ("Tesla", "FSD 카메라", "개발"), ("FSD 카메라", "SLAM", "향상"),
    ("Samsung", "볼리", "개발"), ("볼리", "온디바이스 AI", "탑재"),
    ("Agility Robotics", "Digit 2.0", "개발"), ("Amazon", "Digit 2.0", "도입"),
    ("MIT", "소프트 액추에이터", "연구"),
]

DEMO_STATS = {
    "today_total": 23, "today_processed": 18, "pending": 5, "total": 342,
    "sources": [
        {"source": "ieee_spectrum", "count": 89, "last_collected": "2026-04-13 17:00"},
        {"source": "the_robot_report", "count": 74, "last_collected": "2026-04-13 16:00"},
        {"source": "techcrunch_robotics", "count": 61, "last_collected": "2026-04-13 17:00"},
        {"source": "mit_news_robotics", "count": 55, "last_collected": "2026-04-13 16:00"},
        {"source": "wired_robots", "count": 63, "last_collected": "2026-04-13 15:00"},
    ]
}

# ---- 페이지 설정 -------------------------------------------
st.set_page_config(
    page_title="RoboPulse | 홈로봇 인텔리전스 엔진",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---- CSS ---------------------------------------------------
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700;900&family=Noto+Sans+KR:wght@300;400;500;700;900&display=swap');

html, body, [class*="css"] { font-family: 'Inter', 'Noto Sans KR', sans-serif; }

/* 메인 배경 - 화이트 테마 */
.stApp { background: #f8fafc; color: #1e293b; }
.block-container { padding-top: 1.5rem; max-width: 1400px; }

/* 헤더 타이틀 */
.hero-title {
    font-size: 2.8rem; font-weight: 900; letter-spacing: -1px;
    background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 50%, #db2777 100%);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    background-clip: text; margin: 0;
}
.hero-sub { color: #64748b; font-size: 1rem; margin-top: 4px; font-weight: 500; }

/* 사이드바 - 다크 테마 유지 및 가독성 향상 */
[data-testid="stSidebar"] {
    background-color: #0f172a;
    border-right: 1px solid rgba(255,255,255,0.05);
}
[data-testid="stSidebar"] .stMarkdown p, [data-testid="stSidebar"] .stMarkdown span {
    color: #f1f5f9 !important; /* 사이드바 다크 배경 위에서 잘 보이도록 화이트 처리 */
}
[data-testid="stSidebar"] label {
    color: #94a3b8 !important;
}

.demo-badge {
    display: inline-block;
    background: #f1f5f9; border: 1px solid #e2e8f0;
    border-radius: 20px; padding: 4px 14px;
    color: #475569; font-size: 0.75rem; font-weight: 700;
}

/* 메인 카드 스타일 */
.metric-card {
    background: #ffffff;
    border: 1px solid #e2e8f0; border-radius: 16px;
    padding: 1.4rem 1.6rem;
    box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -1px rgba(0, 0, 0, 0.03);
    transition: transform 0.2s, box-shadow 0.2s;
}
.metric-card:hover { transform: translateY(-2px); box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.08); }
.metric-value { font-size: 2.2rem; font-weight: 800; color: #4f46e5; }
.metric-label { font-size: 0.85rem; color: #64748b; font-weight: 600; margin-top: 4px; }

/* 기사 카드 스타일 */
.article-card {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-left: 5px solid #6366f1;
    border-radius: 12px; padding: 1.4rem 1.6rem; margin-bottom: 1.2rem;
    box-shadow: 0 2px 4px rgba(0,0,0,0.02);
}
.article-card:hover { border-color: #6366f1; box-shadow: 0 4px 12px rgba(0,0,0,0.08); }
.article-card.positive { border-left-color: #22c55e; }
.article-card.negative { border-left-color: #ef4444; }
.article-card.neutral  { border-left-color: #6366f1; }

.article-title { font-size: 1.15rem; font-weight: 700; color: #1e293b; line-height: 1.4; }
.article-summary { color: #475569; font-size: 0.92rem; margin: 0.8rem 0; line-height: 1.7; }
.article-meta { font-size: 0.8rem; color: #94a3b8; font-weight: 500; }

.tag {
    display: inline-block;
    background: #f1f5f9; border: 1px solid #e2e8f0;
    border-radius: 6px; padding: 3px 10px; margin: 2px;
    color: #475569; font-size: 0.75rem; font-weight: 600;
}

/* 상태 인디케이터 */
.status-indicator {
    display: inline-flex; align-items: center; gap: 8px;
    background: rgba(34,197,94,0.1); border: 1px solid rgba(34,197,94,0.2);
    border-radius: 10px; padding: 8px 16px; font-size: 0.85rem; color: #15803d; font-weight: 600;
}
.pulse-dot {
    width: 10px; height: 10px; border-radius: 50%;
    background: #22c55e; animation: pulse 2s infinite;
}
@keyframes pulse { 0% { opacity: 1; transform: scale(1); } 50% { opacity: 0.5; transform: scale(0.8); } 100% { opacity: 1; transform: scale(1); } }

/* 채팅 스타일 */
.chat-user {
    background: #f1f5f9; border-radius: 12px 12px 2px 12px;
    padding: 1rem 1.2rem; margin: 0.6rem 0; color: #1e293b; border: 1px solid #e2e8f0;
}
.chat-bot {
    background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px 12px 12px 2px;
    padding: 1rem 1.2rem; margin: 0.6rem 0; color: #1e293b; line-height: 1.8; box-shadow: 0 2px 4px rgba(0,0,0,0.02);
}

div[data-testid="stTab"] button { font-size: 1rem !important; font-weight: 600 !important; }
</style>
""", unsafe_allow_html=True)

# ---- 상태 체크 및 데이터 로드 -----------------------------------
conn_status = check_all_connections()
is_live = conn_status["postgres"]

# 그래프 복원 (앱 시작 시 한 번)
if is_live and "graph_initialized" not in st.session_state:
    relations = get_all_relations()
    rebuild_from_db(relations)
    st.session_state.graph_initialized = True

# 데이터 로드
if is_live:
    stats = get_pipeline_stats()
    articles = get_latest_articles(limit=20)
    scheduler_jobs = get_scheduler_status()
else:
    stats = DEMO_STATS
    articles = DEMO_ARTICLES
    scheduler_jobs = []

# ---- 사이드바 -----------------------------------------------
with st.sidebar:
    st.markdown('<p class="hero-title" style="font-size:1.6rem">🤖 RoboPulse</p>', unsafe_allow_html=True)
    if is_live:
        st.markdown('<span class="demo-badge" style="background:rgba(104,211,145,0.1);border-color:rgba(104,211,145,0.4);color:#68d391">✦ Live Mode</span>', unsafe_allow_html=True)
    else:
        st.markdown('<span class="demo-badge">✦ Demo Mode</span>', unsafe_allow_html=True)
    st.markdown("---")

    st.markdown("**⚙️ 시스템 상태**")
    sched_running = any(j for j in scheduler_jobs)
    if sched_running:
        st.markdown('<div class="status-indicator"><span class="pulse-dot"></span>파이프라인 가동 중</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="status-indicator" style="background:rgba(113,128,150,0.1);border-color:rgba(113,128,150,0.3);color:#718096"><span class="pulse-dot" style="background:#718096;box-shadow:none"></span>스케줄러 대기 중</div>', unsafe_allow_html=True)
        if st.button("🚀 자동화 시작", use_container_width=True):
            start_scheduler()
            st.rerun()

    st.markdown("")
    st.markdown("**🔌 연결 상태**")
    
    def status_row(label, connected):
        color = "#68d391" if connected else "#fc8181"
        icon = "●"
        st.markdown(f"<div style='font-size:0.85rem; display:flex; justify-content:space-between; color:#e2e8f0'><span>{label}</span><span style='color:{color}'>{icon}</span></div>", unsafe_allow_html=True)

    status_row("PostgreSQL", conn_status["postgres"])
    status_row("Redis (Queue)", conn_status["redis"])
    status_row("LM Studio (AI)", conn_status["lms"])
    
    if not conn_status["lms"]:
        st.warning("⚠️ LM Studio 연결 확인 필요 (Server ON / CORS 체크)")

    st.markdown("---")
    st.caption(f"Model: {LMS_MODEL_NAME.split('/')[-1]}")
    st.caption("Engine: Gemma 4 26B (Local)")
# ---- 헤더 ---------------------------------------------------
col1, col2 = st.columns([8, 2])
with col1:
    st.markdown('<h1 class="hero-title">RoboPulse Intelligence</h1>', unsafe_allow_html=True)
    st.markdown('<p class="hero-sub">홈로봇 산업 지능형 인텔리전스 엔진 — Powered by Gemma 4 26B (Local)</p>', unsafe_allow_html=True)
with col2:
    now = datetime.now().strftime("%m/%d %H:%M")
    st.markdown(f"<div style='text-align:right;color:#718096;font-size:0.8rem;padding-top:12px'>🕐 {now} KST</div>", unsafe_allow_html=True)

st.markdown("")

# ---- 탭 구성 ------------------------------------------------
tab_monitor, tab_briefing, tab_graph, tab_chat = st.tabs([
    "⚙️  파이프라인 모니터링",
    "📋  인텔리전스 브리핑",
    "🕸️  지식 그래프",
    "💬  AI 챗봇 (RAG)",
])

# ==========================================
# Tab 1: 모니터링
# ==========================================
with tab_monitor:
    st.markdown("#### 오늘의 파이프라인 현황")

    c1, c2, c3, c4 = st.columns(4)
    metrics = [
        ("오늘 수집", stats["today_total"], "건", "#63b3ed"),
        ("분석 완료", stats["today_processed"], "건", "#68d391"),
        ("대기 중", stats["pending"], "건", "#f6ad55"),
        ("누적 기사", stats["total"], "건", "#9f7aea"),
    ]
    for col, (label, val, unit, color) in zip([c1, c2, c3, c4], metrics):
        with col:
            st.markdown(f"""
            <div class="metric-card">
                <div class="metric-value" style="color:{color}">{val}<span style="font-size:1rem;margin-left:4px;color:#718096">{unit}</span></div>
                <div class="metric-label">{label}</div>
            </div>
            """, unsafe_allow_html=True)

    st.markdown("")
    st.markdown("#### 소스별 수집 현황")

    import pandas as pd
    df = pd.DataFrame(stats["sources"])
    if not df.empty:
        df.columns = ["소스", "누적 수집", "마지막 수집"]

        # 막대 차트
        fig = go.Figure(go.Bar(
            x=df["소스"], y=df["누적 수집"],
            marker=dict(
                color=df["누적 수집"],
                colorscale=[[0, "rgba(99,179,237,0.4)"], [1, "rgba(99,179,237,0.9)"]],
            ),
            text=df["누적 수집"], textposition="outside",
        ))
        fig.update_layout(
            height=280, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color="#a0aec0", size=12),
            xaxis=dict(showgrid=False, tickfont=dict(size=11)),
            yaxis=dict(showgrid=True, gridcolor="rgba(255,255,255,0.05)"),
            margin=dict(t=20, b=10, l=0, r=0),
        )
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("수집된 소스 정보가 없습니다.")

    st.markdown("#### 예약된 파이프라인 작업")
    col_j1, col_j2 = st.columns(2)
    with col_j1:
        st.info("📰 **뉴스 RSS 수집** — 매 1시간마다\n\n다음 실행: `17:00` (약 28분 후)")
    with col_j2:
        st.info("🎬 **유튜브 자막 수집** — 매일 03:00\n\n다음 실행: `내일 03:00`")

    st.markdown("#### 수동 실행")
    col_b1, col_b2 = st.columns(2)
    with col_b1:
        if st.button("📰 뉴스 수집 지금 실행", use_container_width=True, type="primary"):
            if is_live:
                with st.spinner("뉴스 파이프라인 가동 중..."):
                    job_fetch_news()
                st.success("뉴스 수집 및 분석이 완료되었습니다.")
                st.rerun()
            else:
                st.warning("⚠️ PostgreSQL 서버 연결 후 사용 가능합니다.")
    with col_b2:
        if st.button("🎬 영상 수집 지금 실행", use_container_width=True):
            if is_live:
                with st.spinner("영상 파이프라인 가동 중..."):
                    job_fetch_videos()
                st.success("영상 수집 및 분석이 완료되었습니다.")
                st.rerun()
            else:
                st.warning("⚠️ DB 연결 후 사용 가능합니다.")

    # 실시간 로그 (데모)
    with st.expander("📜 파이프라인 로그 (데모)", expanded=False):
        st.code("""
[17:00:01] ✅ 뉴스 파이프라인 시작
[17:00:02] → ieee_spectrum: 수집 8건, 스킵 12건
[17:00:15] → the_robot_report: 수집 5건, 스킵 15건
[17:00:28] → techcrunch_robotics: 수집 6건, 스킵 14건
[17:00:41] → wired_robots: 수집 3건, 스킵 17건
[17:00:55] → mit_news_robotics: 수집 1건, 스킵 19건
[17:01:02] 🤖 Gemma 4 분석 시작: 23건
[17:02:48] ✅ 분석 완료: 18건 | 실패: 5건 (컨텍스트 초과)
[17:02:48] 💾 DB 저장 완료
        """, language="text")


# ==========================================
# Tab 2: 인텔리전스 브리핑
# ==========================================
with tab_briefing:
    col_top1, col_top2, col_top3 = st.columns([2, 2, 2])
    with col_top1:
        persona = st.selectbox("🎭 페르소나", [
            "전체 (기본)", "💼 투자자 — 재무·시장 중심", "⚙️ 엔지니어 — 기술 스펙 중심", "🛒 소비자 — 제품·출시 중심"
        ])
    with col_top2:
        sentiment_filter = st.multiselect("감성", ["positive", "neutral", "negative"],
                                           default=["positive", "neutral", "negative"])
    with col_top3:
        min_importance = st.slider("최소 중요도", 0.0, 10.0, 3.0, 0.5)

    st.markdown("---")

    filtered = [a for a in articles
                if a["sentiment"] in sentiment_filter and a["importance"] >= min_importance]
    filtered.sort(key=lambda x: x["importance"], reverse=True)

    if not filtered:
        st.info("조건에 맞는 기사가 없습니다.")
    else:
        for art in filtered:
            sentiment = art["sentiment"]
            imp = art["importance"]
            imp_icon = "🔴" if imp >= 9 else "🟠" if imp >= 7 else "🟡"
            tags_html = " ".join(f'<span class="tag">{t}</span>' for t in art["tags"])
            time_ago = datetime.now() - art["published_at"]
            hrs = int(time_ago.total_seconds() // 3600)
            time_str = f"{hrs}시간 전" if hrs < 24 else f"{hrs//24}일 전"

            st.markdown(f"""
<div class="article-card {sentiment}">
    <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:6px">
        <span class="article-title">{art['title']}</span>
        <span style="font-size:0.82rem;color:#a0aec0;white-space:nowrap;margin-left:12px">{imp_icon} {imp:.1f}</span>
    </div>
    <p class="article-summary">{art['summary']}</p>
    <div style="margin-bottom:8px">{tags_html}</div>
    <div class="article-meta">
        {art['source']} · {time_str} &nbsp;·&nbsp;
        <a href="{art['url']}" target="_blank" style="color:#63b3ed;text-decoration:none">원문 보기 →</a>
    </div>
</div>
""", unsafe_allow_html=True)


# ==========================================
# Tab 3: 지식 그래프
# ==========================================
with tab_graph:
    col_g1, col_g2 = st.columns([3, 1])

    with col_g2:
        st.markdown("**엔티티 현황**")
        type_colors = {"company": "🏢", "technology": "⚙️", "institution": "🎓", "product": "📦"}
        
        if is_live:
            db_entities = get_all_entities_for_graph()
            if db_entities:
                for name, etype in db_entities[:15]:  # 상위 15개만 표시
                    icon = type_colors.get(etype, "🔵")
                    st.markdown(f"<div style='font-size:0.82rem;padding:3px 0;color:#e2e8f0'>{icon} {name}</div>", unsafe_allow_html=True)
            else:
                st.caption("데이터 없음")
        else:
            for name, etype in DEMO_GRAPH_NODES:
                icon = type_colors.get(etype, "🔵")
                st.markdown(f"<div style='font-size:0.82rem;padding:3px 0;color:#e2e8f0'>{icon} {name}</div>", unsafe_allow_html=True)

    with col_g1:
        if is_live:
            G = get_graph()
        else:
            G = nx.DiGraph()
            for name, etype in DEMO_GRAPH_NODES:
                G.add_node(name, type=etype, color="#63b3ed")
            for src, tgt, label in DEMO_GRAPH_EDGES:
                G.add_edge(src, tgt, label=label)

        if G.number_of_nodes() == 0:
            st.info("그래프 데이터가 없습니다.")
        else:
            color_map = {"company": "#63b3ed", "technology": "#68d391", "institution": "#f6ad55", "product": "#9f7aea", "unknown": "#718096"}
            pos = nx.spring_layout(G, k=3.5, seed=42)

        edge_traces = []
        for (u, v, d) in G.edges(data=True):
            x0, y0 = pos[u]; x1, y1 = pos[v]
            mx, my = (x0+x1)/2, (y0+y1)/2
            edge_traces.append(go.Scatter(
                x=[x0, x1, None], y=[y0, y1, None], mode="lines",
                line=dict(width=1.5, color="rgba(160,174,192,0.25)"),
                hoverinfo="none", showlegend=False,
            ))
            edge_traces.append(go.Scatter(
                x=[mx], y=[my], mode="text",
                text=[d.get("label", "")], textfont=dict(size=9, color="#718096"),
                hoverinfo="none", showlegend=False,
            ))

        node_x = [pos[n][0] for n in G.nodes()]
        node_y = [pos[n][1] for n in G.nodes()]
        node_colors = [G.nodes[n]["color"] for n in G.nodes()]
        node_labels = list(G.nodes())

        node_trace = go.Scatter(
            x=node_x, y=node_y, mode="markers+text",
            text=node_labels, textposition="top center",
            textfont=dict(size=10, color="#e2e8f0"),
            marker=dict(size=20, color=node_colors, line=dict(width=2, color="rgba(255,255,255,0.3)")),
            hovertemplate="%{text}<extra></extra>",
        )

        fig = go.Figure(data=edge_traces + [node_trace])
        fig.update_layout(
            showlegend=False, height=520,
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(8,13,24,1)",
            font=dict(color="#e2e8f0"),
            xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            margin=dict(t=10, b=10, l=10, r=10),
        )
        st.plotly_chart(fig, use_container_width=True)

    # 범례
    st.markdown("""
    <div style="display:flex;gap:20px;font-size:0.8rem;color:#a0aec0;margin-top:4px">
        <span>🏢 기업</span><span>⚙️ 기술</span><span>🎓 기관</span><span>📦 제품</span>
    </div>
    """, unsafe_allow_html=True)


# ==========================================
# Tab 4: AI 챗봇 (RAG 데모)
# ==========================================
with tab_chat:
    st.caption("🤖 Gemma 4 26B + RAG 기반 질문응답 (LM Studio 연결 후 실제 동작)")

    if "chat_history" not in st.session_state:
        st.session_state.chat_history = [
            {"role": "assistant", "content": "안녕하세요! 저는 RoboPulse AI입니다. 홈로봇 산업에 대해 무엇이든 질문해주세요. (현재 데모 모드: LM Studio 연결 시 실제 Gemma 4 응답을 제공합니다)"},
        ]

    for msg in st.session_state.chat_history:
        css = "chat-user" if msg["role"] == "user" else "chat-bot"
        icon = "🧑" if msg["role"] == "user" else "🤖"
        st.markdown(f'<div class="{css}">{icon}&nbsp; {msg["content"]}</div>', unsafe_allow_html=True)

    user_input = st.chat_input("예: 최근 Humanoid 로봇 트렌드는?")

    DEMO_RESPONSES = {
        "default": """현재 수집된 데이터를 기반으로 분석한 결과입니다:

**🔍 주요 트렌드 (2026년 4월 기준)**

1. **Humanoid 로봇의 상업화 가속** — Agility Robotics의 Digit 2.0이 아마존 물류센터 600대 배치를 완료하며 본격적인 대규모 실증 단계에 진입했습니다.

2. **센서 기술 파트너십 확대** — Boston Dynamics × Tesla 협력처럼, 완성차/빅테크 기업의 센서 기술이 로봇 플랫폼에 이식되는 흐름이 강화되고 있습니다.

3. **소비자 시장 진출 임박** — 삼성 '볼리'를 필두로 2027~2028년 가정용 AI 로봇 양산 일정이 구체화되고 있습니다.

4. **규제 리스크** — EU 인증 의무화(2028년) 예정으로, 유럽 진출을 노리는 기업들의 컴플라이언스 부담이 증가할 전망입니다."""
    }

    if user_input:
        st.session_state.chat_history.append({"role": "user", "content": user_input})

        # LM Studio 실제 연결 시도
        answer = None
        try:
            from openai import OpenAI as OA
            client = OA(base_url=os.getenv("LMS_API_BASE", "http://localhost:1234/v1"), api_key="lm-studio")
            
            # RAG (의미론적 검색)
            if is_live:
                search_results = semantic_search(user_input, top_k=5)
                context = "\n\n".join([f"[{r['source']}] {r['title']}\n{r['summary']}" for r in search_results])
            else:
                context = "\n\n".join([f"[{a['source']}] {a['title']}\n{a['summary']}" for a in DEMO_ARTICLES[:3]])
                
            resp = client.chat.completions.create(
                model=LMS_MODEL_NAME,
                messages=[
                    {"role": "system", "content": "홈로봇 산업 전문 분석가입니다. 주어진 문서 기반으로 한국어로 답변하세요."},
                    {"role": "user", "content": f"참조 문서:\n{context}\n\n질문: {user_input}"},
                ],
                temperature=0.3, max_tokens=1024,
            )
            answer = resp.choices[0].message.content
        except Exception as e:
            logger.error(f"채팅 응답 실패: {e}")
            answer = DEMO_RESPONSES["default"]

        st.session_state.chat_history.append({"role": "assistant", "content": answer})
        st.rerun()
