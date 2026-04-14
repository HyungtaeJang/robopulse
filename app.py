"""
app.py - RoboPulse 메인 Streamlit 대시보드
개선된 라이트 모드 테마 및 간결한 UI (No Emojis)
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

LMS_MODEL_NAME = os.getenv("LMS_MODEL_NAME", "lmstudio-community/gemma-4-26b-a4b-it")

# ---- 데모 샘플 데이터 (폴백용) -----------------------------------
DEMO_ARTICLES = [
    {
        "title": "Boston Dynamics, Spot 차세대 모델에 Tesla 센서 기술 탑재 예정",
        "url": "https://spectrum.ieee.org/boston-dynamics-spot-next-gen",
        "source": "ieee_spectrum", "sentiment": "positive", "importance": 9.2,
        "summary": "Boston Dynamics가 Spot 로봇의 차세대 모델에 Tesla의 센서를 탑재하여 SLAM 성능을 대폭 개선할 예정입니다.",
        "tags": ["SLAM", "센서", "파트너십"],
        "published_at": datetime.now() - timedelta(hours=2),
    }
]

DEMO_STATS = {
    "today_total": 0, "today_processed": 0, "pending": 0, "total": 0,
    "sources": []
}

# ---- 페이지 설정 -------------------------------------------
st.set_page_config(
    page_title="RoboPulse Intelligence",
    page_icon="🤖",
    layout="wide",
)

# ---- CSS 디자인 --------------------------------------------
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;900&family=Noto+Sans+KR:wght@400;500;700&display=swap');

html, body, [class*="css"] { font-family: 'Inter', 'Noto Sans KR', sans-serif; }

/* 메인 배경 - 화이트 테마 */
.stApp { background: #ffffff; color: #1e293b; }
.block-container { padding-top: 2rem; max-width: 1400px; }

/* 헤더 타이틀 */
.hero-title {
    font-size: 2.5rem; font-weight: 900; letter-spacing: -1px;
    background: linear-gradient(135deg, #4338ca 0%, #7c3aed 100%);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    background-clip: text; margin: 0;
}
.hero-sub { color: #64748b; font-size: 1rem; margin-top: 6px; font-weight: 500; }

/* 사이드바 - 연그레이 테마 */
[data-testid="stSidebar"] {
    background-color: #f1f5f9;
    border-right: 1px solid #e2e8f0;
}
[data-testid="stSidebar"] .stMarkdown p, [data-testid="stSidebar"] .stMarkdown span {
    color: #1e293b !important;
    font-size: 0.95rem;
    font-weight: 500;
}
[data-testid="stSidebar"] label { color: #475569 !important; }

.mode-badge {
    display: inline-block;
    padding: 4px 12px; border-radius: 6px; font-size: 0.75rem; font-weight: 800;
    margin-bottom: 1rem; text-transform: uppercase;
}

/* 메트릭 카드 */
.metric-card {
    background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px;
    padding: 1.5rem; box-shadow: 0 1px 3px rgba(0,0,0,0.1);
}
.metric-value { font-size: 2rem; font-weight: 800; color: #4338ca; }
.metric-label { font-size: 0.85rem; color: #64748b; font-weight: 600; margin-top: 4px; }

/* 기사 카드 */
.article-card {
    background: #ffffff; border: 1px solid #e2e8f0; border-left: 4px solid #6366f1;
    border-radius: 8px; padding: 1.2rem; margin-bottom: 1rem;
}
.article-card.positive { border-left-color: #22c55e; }
.article-card.negative { border-left-color: #ef4444; }
.article-title { font-size: 1.1rem; font-weight: 700; color: #1e293b; }
.article-summary { color: #475569; font-size: 0.9rem; margin: 0.6rem 0; line-height: 1.6; }

/* 상태 인디케이터 Dot */
.status-dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; margin-right: 8px; }

div[data-testid="stTab"] button { font-size: 1rem !important; font-weight: 600 !important; }
</style>
""", unsafe_allow_html=True)

# ---- 데이터 로드 --------------------------------------------
conn_status = check_all_connections()
is_live = conn_status["postgres"]

# 그래프 복원
if is_live and "graph_initialized" not in st.session_state:
    relations = get_all_relations()
    rebuild_from_db(relations)
    st.session_state.graph_initialized = True

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
    st.markdown('<p class="hero-title" style="font-size:1.6rem">RoboPulse</p>', unsafe_allow_html=True)
    if is_live:
        st.markdown('<div class="mode-badge" style="background:#dcfce7; color:#166534">Live Mode</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="mode-badge" style="background:#f1f5f9; color:#64748b">Demo Mode</div>', unsafe_allow_html=True)
    
    st.markdown("---")
    st.markdown("**시스템 상태**")
    sched_running = any(j for j in scheduler_jobs)
    if sched_running:
        st.success("파이프라인 가동 중")
    else:
        st.info("스케줄러 대기 중")
        if st.button("자동화 시작", use_container_width=True):
            start_scheduler()
            st.rerun()

    st.markdown("")
    st.markdown("**연결 상태**")
    
    def status_row(label, connected):
        color = "#22c55e" if connected else "#ef4444"
        icon_svg = f'<svg width="10" height="10"><circle cx="5" cy="5" r="5" fill="{color}" /></svg>'
        st.markdown(f"""
        <div style="display:flex; justify-content:space-between; align-items:center; padding:4px 0;">
            <span style="color:#475569">{label}</span>
            {icon_svg}
        </div>
        """, unsafe_allow_html=True)

    status_row("PostgreSQL", conn_status["postgres"])
    status_row("Redis (Queue)", conn_status["redis"])
    status_row("LM Studio (AI)", conn_status["lms"])
    
    if is_live and not conn_status["lms"]:
        st.warning("LM Studio 연결 확인 필요 (CORS/Server)")

    st.markdown("---")
    st.caption(f"Model: {LMS_MODEL_NAME.split('/')[-1]}")
    st.caption("Local Gemma 4 Engine")

# ---- 메인 헤더 ----------------------------------------------
col_h1, col_h2 = st.columns([8, 2])
with col_h1:
    st.markdown('<h1 class="hero-title">RoboPulse Intelligence</h1>', unsafe_allow_html=True)
    st.markdown('<p class="hero-sub">홈로봇 산업 인텔리전스 엔진 — Powered by Local Gemma 4</p>', unsafe_allow_html=True)
with col_h2:
    st.markdown(f"<div style='text-align:right;color:#94a3b8;font-size:0.8rem;padding-top:14px'>{datetime.now().strftime('%m/%d %H:%M')}</div>", unsafe_allow_html=True)

st.markdown("")

# ---- 탭 구성 ------------------------------------------------
tab_monitor, tab_briefing, tab_graph, tab_chat = st.tabs([
    "파이프라인 모니터링", "인텔리전스 브리핑", "지식 그래프", "AI 챗봇"
])

# Tab 1: 모니터링
with tab_monitor:
    c1, c2, c3, c4 = st.columns(4)
    for col, (label, val, unit) in zip([c1, c2, c3, c4], [
        ("오늘 수집", stats["today_total"], "건"),
        ("분석 완료", stats["today_processed"], "건"),
        ("대기 중", stats["pending"], "건"),
        ("누적 기사", stats["total"], "건")
    ]):
        with col:
            st.markdown(f'<div class="metric-card"><div class="metric-value">{val}</div><div class="metric-label">{label} ({unit})</div></div>', unsafe_allow_html=True)

    st.markdown("### 소스별 수집 현황")
    if stats["sources"]:
        import pandas as pd
        df = pd.DataFrame(stats["sources"])
        df.columns = ["소스", "수집량", "최근수집"]
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("수집된 데이터 소스가 없습니다.")

    st.markdown("### 수동 조작")
    cb1, cb2 = st.columns(2)
    with cb1:
        if st.button("뉴스 수집 실행", use_container_width=True, type="primary"):
            if is_live:
                with st.spinner("뉴스 파이프라인 가동..."): job_fetch_news()
                st.rerun()
            else: st.warning("DB 연결이 필요합니다.")
    with cb2:
        if st.button("영상 수집 실행", use_container_width=True):
            if is_live:
                with st.spinner("영상 파이프라인 가동..."): job_fetch_videos()
                st.rerun()
            else: st.warning("DB 연결이 필요합니다.")

    # 로그 섹션
    log_label = "실시간 파이프라인 로그" if is_live else "파이프라인 로그 (데모)"
    with st.expander(log_label, expanded=is_live):
        if is_live:
            st.info("상세 로그는 서버 터미널을 확인해 주세요.")
        else:
            st.code("[10:00:01] 뉴스 수집 시작...\n[10:02:15] 분석 완료 및 DB 저장", language="text")

# Tab 2: 브리핑
with tab_briefing:
    col_f1, col_f2 = st.columns([2, 2])
    with col_f1: 
        sentiment_filter = st.multiselect("감성 필터", ["positive", "neutral", "negative"], default=["positive", "neutral", "negative"])
    with col_f2:
        min_importance = st.slider("최소 중요도", 0.0, 10.0, 3.0)

    st.markdown("---")
    filtered = [a for a in articles if a.get("sentiment") in sentiment_filter and a.get("importance", 0) >= min_importance]
    if not filtered:
        st.info("조건에 맞는 결과가 없습니다.")
    else:
        for art in filtered:
            sentiment = art.get("sentiment", "neutral")
            st.markdown(f"""
            <div class="article-card {sentiment}">
                <div class="article-title">{art['title']}</div>
                <p class="article-summary">{art.get('summary', '요약 정보가 없습니다.')}</p>
                <div class="article-meta">{art.get('source')} · {art.get('published_at')}</div>
            </div>
            """, unsafe_allow_html=True)

# Tab 3: 지식 그래프
with tab_graph:
    col_g1, col_g2 = st.columns([3, 1])
    with col_g1:
        G = get_graph() if is_live else nx.DiGraph()
        if G.number_of_nodes() == 0:
            st.info("그래프 데이터가 없습니다.")
        else:
            pos = nx.spring_layout(G, k=1.5, seed=42)
            node_x = [pos[n][0] for n in G.nodes()]
            node_y = [pos[n][1] for n in G.nodes()]
            node_trace = go.Scatter(x=node_x, y=node_y, mode='markers+text', text=list(G.nodes()), 
                                    textposition="top center", marker=dict(size=12, color='#4338ca'))
            fig = go.Figure(data=[node_trace])
            fig.update_layout(showlegend=False, height=600, margin=dict(t=0, b=0, l=0, r=0))
            st.plotly_chart(fig, use_container_width=True)
    with col_g2:
        st.markdown("**핵심 엔티티**")
        if is_live:
            db_entities = get_all_entities_for_graph()
            for name, etype in db_entities[:20]:
                st.write(f"- {name} ({etype})")
        else:
            st.write("데모 모드에서는 엔티티 목록이 표시되지 않습니다.")

# Tab 4: AI 챗봇
with tab_chat:
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = [{"role": "assistant", "content": "로봇 산업에 대해 질문해 주세요."}]

    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])

    user_input = st.chat_input("질문을 입력하세요.")
    if user_input:
        st.session_state.chat_history.append({"role": "user", "content": user_input})
        with st.chat_message("user"): st.write(user_input)
        
        with st.chat_message("assistant"):
            if is_live:
                try:
                    from openai import OpenAI as OA
                    import httpx
                    client = OA(base_url=os.getenv("LMS_API_BASE"), api_key="lm-studio", http_client=httpx.Client(proxies={}))
                    results = semantic_search(user_input, top_k=3)
                    context = "\n".join([f"- {r['title']}: {r['summary']}" for r in results])
                    resp = client.chat.completions.create(
                        model=LMS_MODEL_NAME,
                        messages=[{"role": "system", "content": "산업 분석가입니다. 문맥 기반 답변하세요."}, {"role": "user", "content": f"문맥: {context}\n질문: {user_input}"}],
                        temperature=0.3
                    )
                    answer = resp.choices[0].message.content
                except Exception as e: answer = f"연결 오류: {e}"
            else:
                answer = "데모 모드에서는 사전 정의된 응답만 가능합니다."
            st.write(answer)
            st.session_state.chat_history.append({"role": "assistant", "content": answer})
