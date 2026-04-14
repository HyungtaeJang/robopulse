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
    get_all_relations, semantic_search, get_all_entities_for_graph,
    init_news_sources, get_news_sources, add_news_source, 
    delete_news_source, toggle_news_source, clear_all_data, get_lms_client
)
from scheduler.pipeline_scheduler import (
    start_scheduler, get_scheduler_status, job_fetch_news, job_fetch_videos, job_analyze_unprocessed
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
.article-title { font-size: 1.1rem; font-weight: 700; color: #1e293b; text-decoration: none; display: inline-block; }
.article-title:hover { color: #4338ca; text-decoration: underline; }
.article-summary { color: #475569; font-size: 0.9rem; margin: 0.6rem 0; line-height: 1.6; }
.article-thumb { width: 140px; height: 90px; border-radius: 6px; object-fit: cover; border: 1px solid #e2e8f0; flex-shrink: 0; }
.badge-importance { background: #fdf6b2; color: #723b13; padding: 2px 8px; border-radius: 4px; font-weight: 700; font-size: 0.8rem; }

/* 상태 인디케이터 Dot */
.status-dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; margin-right: 8px; }

div[data-testid="stTab"] button { font-size: 1rem !important; font-weight: 600 !important; }
</style>
""", unsafe_allow_html=True)

# ---- 데이터 로드 및 초기화 ------------------------------------
conn_status = check_all_connections()
is_live = conn_status["postgres"]

# DB 초기화 (뉴스 소스 테이블 등)
if is_live:
    init_news_sources()

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
tab_monitor, tab_briefing, tab_graph, tab_chat, tab_settings = st.tabs([
    "파이프라인 모니터링", "인텔리전스 브리핑", "지식 그래프", "AI 챗봇", "설정 및 제어"
])

# Tab 1: 모니터링
with tab_monitor:
    st.info("💡 **수집 단계**: 지정된 RSS 소스에서 실시간으로 로봇 산업 뉴스를 수집합니다.")
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
                
    st.markdown("### 인텔리전스 엔진 제어")
    ca1, ca2 = st.columns(2)
    with ca1:
        if st.button("미처리 데이터 AI 분석", use_container_width=True, type="secondary"):
            if is_live:
                with st.spinner("Gemma 4가 기사를 분석 중입니다..."):
                    job_analyze_unprocessed()
                st.rerun()
            else: st.warning("DB 연결이 필요합니다.")
    with ca2:
        st.caption("수집은 되었으나 아직 AI 분석(요약, 엔티티 추출 등)이 완료되지 않은 기사들을 처리합니다.")

    # 로그 섹션
    log_label = "실시간 파이프라인 로그" if is_live else "파이프라인 로그 (데모)"
    with st.expander(log_label, expanded=is_live):
        if is_live:
            st.info("상세 로그는 서버 터미널을 확인해 주세요.")
        else:
            st.code("[10:00:01] 뉴스 수집 시작...\n[10:02:15] 분석 완료 및 DB 저장", language="text")
# Tab 5: 설정 및 제어
with tab_settings:
    st.markdown("### 데이터 수집 루트(RSS) 관리")
    st.caption("시스템이 정기적으로 방문하여 로봇 뉴스를 수집할 사이트 목록입니다.")
    
    # 소스 추가 폼
    with st.expander("신규 수집 소스 추가", expanded=False):
        with st.form("add_source_form"):
            new_label = st.text_input("사이트 이름", placeholder="예: Robotics Business Review")
            new_url = st.text_input("RSS 피드 URL", placeholder="https://example.com/feed")
            new_name = "".join(filter(str.isalnum, new_label.lower())).replace(" ", "_")
            if st.form_submit_button("소스 등록"):
                if new_label and new_url:
                    add_news_source(new_name, new_url, new_label)
                    st.success(f"'{new_label}' 소스가 등록되었습니다.")
                    st.rerun()
                else:
                    st.error("이름과 URL을 모두 입력해주세요.")

    # 소스 목록 표시
    sources = get_news_sources()
    if sources:
        for src in sources:
            sc1, sc2, sc3, sc4 = st.columns([3, 4, 1, 1])
            with sc1: st.write(f"**{src['label']}**")
            with sc2: st.caption(src['url'])
            with sc3:
                is_active = st.toggle("활성", value=src['is_active'], key=f"tog_{src['id']}")
                if is_active != src['is_active']:
                    toggle_news_source(src['id'], is_active)
                    st.rerun()
            with sc4:
                if st.button("삭제", key=f"del_{src['id']}", type="secondary"):
                    delete_news_source(src['id'])
                    st.rerun()
            st.markdown("---")
    
    st.markdown("### 시스템 초기화")
    st.warning("주의: 초기화 시 수집된 모든 기사와 분석 데이터가 영구적으로 삭제됩니다.")
    
    reset_col1, reset_col2 = st.columns([2, 8])
    with reset_col1:
        if st.button("전체 데이터 초기화", type="primary", use_container_width=True):
            if is_live:
                with st.spinner("시스템 초기화 중..."):
                    clear_all_data(reset_sources=True)
                st.toast("✅ 데이터베이스가 깨끗하게 비워졌습니다.", icon="🗑️")
                import time
                time.sleep(1) # 사용자가 메시지를 읽을 시간을 줍니다.
                st.rerun()
            else:
                st.error("DB가 연결되지 않았습니다.")

# Tab 2: 인텔리전스 브리핑
with tab_briefing:
    st.info("💡 **심층 분석**: Gemma 4 모델이 각 소스의 중요도를 평가하고 3줄 핵심 요약을 제공하는 인텔리전스 보고서입니다.")
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
            thumbnail = art.get("thumbnail_url")
            img_tag = f'<img src="{thumbnail}" class="article-thumb" alt="thumbnail">' if thumbnail else ''
            importance = art.get("importance", 0.0)
            
            st.html(f"""
            <div class="article-card {sentiment}" style="display: flex; gap: 20px; align-items: stretch;">
                {img_tag}
                <div style="flex: 1; display: flex; flex-direction: column; justify-content: space-between;">
                    <div>
                        <div style="display: flex; justify-content: space-between; align-items: flex-start;">
                            <a href="{art['url']}" target="_blank" class="article-title">{art['title']}</a>
                            <span class="badge-importance">⭐ {importance:.1f}</span>
                        </div>
                        <p class="article-summary">{art.get('summary', '요약 정보가 없습니다.')}</p>
                    </div>
                    <div class="article-meta" style="font-size: 0.8rem; color: #94a3b8; display: flex; justify-content: space-between;">
                        <span>🏢 {art.get('source')}</span>
                        <span>🕒 {art.get('published_at')}</span>
                    </div>
                </div>
            </div>
            """)

# Tab 3: 지식 그래프
with tab_graph:
    st.info("💡 **추출 단계**: 뉴스 본문에서 기업, 기술, 관계를 추출하여 산업 지형도를 시각화합니다.")
    col_g1, col_g2 = st.columns([3, 1])

    with col_g2:
        st.markdown("### 그래프 필터")
        top_n = st.slider("표시 노드 수", 10, 100, 30)
        st.markdown("---")
        st.markdown("**범례 (Legend)**")
        st.markdown("🔵 기업 (Company)")
        st.markdown("🟠 기술 (Technology)")
        st.markdown("🟢 제품 (Product)")
        st.markdown("🔴 기관 (Institution)")

    with col_g1:
        G = get_graph() if is_live else nx.DiGraph()
        if G.number_of_nodes() == 0:
            st.info("그래프 데이터가 없습니다.")
        else:
            # 상위 노드 필터링
            nodes_sorted = sorted(G.nodes(data=True), key=lambda x: x[1].get("mention_count", 0), reverse=True)[:top_n]
            top_node_names = [n[0] for n in nodes_sorted]
            subG = G.subgraph(top_node_names)

            pos = nx.spring_layout(subG, k=1.0, seed=42)
            color_map = {"company": "#4338ca", "technology": "#f97316", "product": "#22c55e", "institution": "#ef4444", "unknown": "#94a3b8"}

            # 엣지(관계선) 생성
            edge_x, edge_y = [], []
            for edge in subG.edges():
                x0, y0 = pos[edge[0]]
                x1, y1 = pos[edge[1]]
                edge_x.extend([x0, x1, None])
                edge_y.extend([y0, y1, None])

            edge_trace = go.Scatter(x=edge_x, y=edge_y, line=dict(width=1, color='#CBD5E1'), hoverinfo='none', mode='lines')

            # 노드 생성
            node_x, node_y, node_colors, node_sizes, node_texts = [], [], [], [], []
            for node in subG.nodes():
                x, y = pos[node]
                node_x.append(x)
                node_y.append(y)
                attrs = subG.nodes[node]
                ntype = attrs.get("type", "unknown")
                mcount = attrs.get("mention_count", 1)
                node_colors.append(color_map.get(ntype, color_map["unknown"]))
                node_sizes.append(max(15, min(50, 15 + mcount * 5)))
                node_texts.append(f"<b>{node}</b><br>Type: {ntype}<br>Mentions: {mcount}")

            node_trace = go.Scatter(x=node_x, y=node_y, mode='markers+text', text=list(subG.nodes()), 
                                    textposition="top center", hoverinfo='text', hovertext=node_texts,
                                    marker=dict(color=node_colors, size=node_sizes, line_width=2, line_color='white'))

            fig = go.Figure(data=[edge_trace, node_trace],
                         layout=go.Layout(showlegend=False, hovermode='closest', margin=dict(b=0, l=0, r=0, t=0),
                                          xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                                          yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                                          height=600, plot_bgcolor='white'))
            st.plotly_chart(fig, use_container_width=True)

# Tab 4: AI 챗봇
with tab_chat:
    st.info("💡 **활용 단계**: 수집된 최신 지식을 바탕으로 AI 분석가와 대화하며 인사이트를 얻습니다.")
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
                    results = semantic_search(user_input, top_k=3)
                    context = "\n".join([f"- {r['title']}: {r['summary']}" for r in results])
                    
                    # 공용 클라이언트 사용 (프록시 우회 자동 적용)
                    client = get_lms_client()
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
