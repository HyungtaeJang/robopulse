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
import threading
import time
try:
    from streamlit.runtime.scriptrunner.script_run_context import add_script_run_context, get_script_run_ctx
except ImportError:
    try:
        from streamlit.runtime.scriptrunner import add_script_run_context, get_script_run_ctx
    except ImportError:
        pass

# ---- AI 분석 전역 상태 매니저 (0/0 현상 근본 해결용) -----------
if "ANALYSIS_MANAGER" not in globals():
    globals()["ANALYSIS_MANAGER"] = {
        "active": False,
        "current": 0,
        "total": 0,
        "done": False,
        "lock": threading.Lock()
    }

def analysis_callback(current, total):
    """백그라운드 스레드에서 호출되어 전역 상태를 업데이트하는 콜백 (Streamlit 종속성 없음)"""
    mgr = globals()["ANALYSIS_MANAGER"]
    with mgr["lock"]:
        if current == -1: # 오류 발생
            mgr["active"] = False
            return
        
        mgr["current"] = current
        mgr["total"] = total
        
        if current >= total and total > 0:
            mgr["active"] = False
            mgr["done"] = True

def run_analysis_in_background():
    """AI 분석을 백그라운드 스레드에서 시작 (전역 상태 사용)"""
    mgr = globals()["ANALYSIS_MANAGER"]
    with mgr["lock"]:
        mgr["active"] = True
        mgr["current"] = 0
        mgr["total"] = 0
        mgr["done"] = False
    
    # 분석 스레드 생성 (인자만 전달, 컨텍스트 주입 불필요)
    thread = threading.Thread(target=job_analyze_unprocessed, args=(analysis_callback,))
    thread.daemon = True # 프로세스 종료 시 함께 종료
    thread.start()

try:
    from db.vector_store import (
        check_all_connections, get_pipeline_stats, get_latest_articles, 
        clear_all_data, get_all_relations, get_all_entities_for_graph,
        init_news_sources, get_news_sources, add_news_source, toggle_news_source, delete_news_source,
        get_youtube_sources, add_youtube_source, toggle_youtube_source, delete_youtube_source,
        get_recommended_sources, update_recommended_source_status,
        get_lms_client, semantic_search
    )
    from scheduler.pipeline_scheduler import (
        start_scheduler, get_scheduler_status, job_fetch_news, job_fetch_videos, 
        job_analyze_unprocessed, update_analysis_schedule
    )
    from engine.graph_builder import get_graph, rebuild_from_db, get_entity_stats
    is_live = True
except Exception as e:
    is_live = False

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
    page_title="RoboPulse",
    page_icon="",
    layout="wide",
)

# ---- CSS 디자인 --------------------------------------------
from ui.style import apply_global_styles
apply_global_styles()

# ---- 세션 스테이트 초기화 및 분석 알림 --------------------------
if "analysis_done_toast" not in st.session_state:
    st.session_state.analysis_done_toast = False
if "briefing_filter_tag" not in st.session_state:
    st.session_state.briefing_filter_tag = None
if "briefing_today_only" not in st.session_state:
    st.session_state.briefing_today_only = False
if "briefing_sort_by" not in st.session_state:
    st.session_state.briefing_sort_by = "date"
if "briefing_min_importance" not in st.session_state:
    st.session_state.briefing_min_importance = 0.0
if "system_status" not in st.session_state:
    st.session_state.system_status = None

# 전역 매니저에서 상태 읽어오기
mgr = globals()["ANALYSIS_MANAGER"]

# 분석 완료 시 세션별 토스트 알림 처리
if mgr["done"] and not st.session_state.analysis_done_toast:
    st.toast("✅ AI 심층 분석이 완료되었습니다. 결과가 대시보드에 반영되었습니다.")
    st.session_state.analysis_done_toast = True
elif not mgr["done"]:
    st.session_state.analysis_done_toast = False

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
    # 파라미터 기반 기사 로드
    articles = get_latest_articles(
        limit=50, 
        min_importance=st.session_state.briefing_min_importance, 
        today_only=st.session_state.briefing_today_only,
        tag_filter=st.session_state.briefing_filter_tag,
        sort_by=st.session_state.briefing_sort_by
    )
    scheduler_jobs = get_scheduler_status()
else:
    stats = DEMO_STATS
    articles = DEMO_ARTICLES
    scheduler_jobs = []

# ---- 사이드바 -----------------------------------------------
from ui.sidebar import render_sidebar
render_sidebar(
    is_live=is_live,
    conn_status=conn_status,
    scheduler_jobs=scheduler_jobs,
    mgr=mgr,
    run_analysis_callback=run_analysis_in_background,
    start_scheduler_callback=start_scheduler,
    job_fetch_news_callback=job_fetch_news,
    job_fetch_videos_callback=job_fetch_videos,
    LMS_MODEL_NAME=LMS_MODEL_NAME
)

# ---- 메인 헤더 ----------------------------------------------
col_h1, col_h2 = st.columns([8, 2])
with col_h1:
    st.markdown('<h1 class="hero-title">RoboPulse</h1>', unsafe_allow_html=True)
    st.markdown('<p class="hero-sub">홈로봇 관련 데이터 수집 자동화 엔진 — Powered by Local Gemma 4</p>', unsafe_allow_html=True)
with col_h2:
    st.markdown(f"<div style='text-align:right;color:#94a3b8;font-size:0.8rem;padding-top:14px'>{datetime.now().strftime('%m/%d %H:%M')}</div>", unsafe_allow_html=True)

st.markdown("")

# ---- 탭 구성 ------------------------------------------------
tab_briefing, tab_graph, tab_chat, tab_settings = st.tabs([
    "AI 브리핑", "지식 그래프", "AI Chat", "설정 및 제어"
])

# Tab 1: AI 브리핑
with tab_briefing:
    from ui.tabs.briefing import render_tab_briefing
    render_tab_briefing(stats=stats, articles=articles)

# Tab 3: 지식 그래프
with tab_graph:
    from ui.tabs.knowledge_graph import render_tab_graph
    # app.py에서는 is_live와 get_graph() 등을 인자로 넘김
    from engine.graph_builder import get_graph
    render_tab_graph(is_live=is_live, get_graph_func=get_graph)

# Tab 4: AI Chat
with tab_chat:
    from ui.tabs.chat import render_tab_chat
    render_tab_chat(is_live=is_live, LMS_MODEL_NAME=LMS_MODEL_NAME)

# Tab 5: 설정 및 제어 (위에 있던 tab_settings 처리)
# 실제 뷰 렌더링을 이곳에서 하므로 기존 위치 상관 없음
with tab_settings:
    from ui.tabs.settings import render_tab_settings
    render_tab_settings(is_live=is_live)
