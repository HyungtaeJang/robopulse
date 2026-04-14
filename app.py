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
.tag-badge { background: #eff6ff; color: #1d4ed8; padding: 1px 6px; border-radius: 4px; font-size: 0.7rem; font-weight: 600; margin-right: 4px; border: 1px solid #dbeafe; }

/* 상태 인디케이터 Dot */
.status-dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; margin-right: 8px; }

div[data-testid="stTab"] button { font-size: 1rem !important; font-weight: 600 !important; }
</style>
""", unsafe_allow_html=True)

# ---- 세션 스테이트 초기화 및 분석 알림 --------------------------
if "analysis_done_toast" not in st.session_state:
    st.session_state.analysis_done_toast = False

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
    articles = get_latest_articles(limit=20)
    scheduler_jobs = get_scheduler_status()
else:
    stats = DEMO_STATS
    articles = DEMO_ARTICLES
    scheduler_jobs = []

# ---- 사이드바 -----------------------------------------------
with st.sidebar:
    st.markdown('<p class="hero-title" style="font-size:2rem; margin-top:-20px; text-shadow: 0 2px 4px rgba(0,0,0,0.1);">RoboPulse</p>', unsafe_allow_html=True)
    st.markdown('<p style="font-size:0.8rem; color:#64748b; font-weight:600; margin-bottom:15px; margin-top:-5px; letter-spacing:1px;">INTELLIGENCE ENGINE</p>', unsafe_allow_html=True)
    
    if is_live:
        st.markdown('<div class="mode-badge" style="background:#dcfce7; color:#166534">Live Mode</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="mode-badge" style="background:#f1f5f9; color:#64748b">Demo Mode</div>', unsafe_allow_html=True)
    
    st.markdown("---")
    
    # 1. 시스템 상태 (Expander + Status Dot)
    sched_running = any(j for j in scheduler_jobs)
    sys_dot = "🟢" if sched_running else "🔴"
    
    with st.expander(f"시스템 상태 &nbsp;&nbsp;{sys_dot}", expanded=not sched_running):
        if sched_running:
            st.markdown('<p style="font-size:0.8rem; font-weight:600; color:#475569; margin-top:5px; margin-bottom:5px;">향후 실행 일정</p>', unsafe_allow_html=True)
            
            job_map = {
                "news_pipeline": "뉴스 수집",
                "video_pipeline": "영상 수집",
                "analysis_pipeline": "심층 분석"
            }
            
            for job in scheduler_jobs:
                name = job_map.get(job['id'], job['name'])
                st.markdown(f"""
                <div style="display:flex; justify-content:space-between; font-size:0.8rem; padding:2px 0; color:#1e293b;">
                    <span>{name}</span>
                    <span style="font-weight:600; color:#4338ca;">{job['next_run']}</span>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.info("수집이 중단되었습니다. 실시간 정보를 위해 자동화를 시작하세요.")
            if st.button("자동화 시작", use_container_width=True, type="primary"):
                start_scheduler()
                st.rerun()

    # 2. 연결 상태 (Expander + Status Dot)
    all_connected = all(conn_status.values())
    conn_dot = "🟢" if all_connected else "🔴"
    
    with st.expander(f"연결 상태 &nbsp;&nbsp;{conn_dot}", expanded=not all_connected):
        def status_row(label, connected):
            color = "#22c55e" if connected else "#ef4444"
            icon_svg = f'<svg width="10" height="10"><circle cx="5" cy="5" r="5" fill="{color}" /></svg>'
            st.markdown(f"""
            <div style="display:flex; justify-content:space-between; align-items:center; padding:4px 0;">
                <span style="color:#475569; font-size:0.85rem;">{label}</span>
                {icon_svg}
            </div>
            """, unsafe_allow_html=True)
        status_row("PostgreSQL", conn_status["postgres"])
        status_row("Redis", conn_status["redis"])
        status_row("Local LLM", conn_status["lms"])
        
        if is_live and not conn_status["lms"]:
            st.warning("Local LLM 연결 확인 필요")

    st.markdown("---")
    
    # AI 분석 진행 상태 (전역 ANALYSIS_MANAGER 참조)
    if mgr["active"]:
        st.markdown("**AI 분석 진행 중...**")
        prog_val = 0
        with mgr["lock"]:
            curr, tot = mgr["current"], mgr["total"]
        
        if tot > 0:
            prog_val = curr / tot
        
        st.progress(prog_val)
        st.caption(f"처리 중: {curr} / {tot}")
        if st.button("새로고침", key="analysis_refresh"):
            st.rerun()

    st.caption(f"Model: {LMS_MODEL_NAME.split('/')[-1]}")

# ---- 메인 헤더 ----------------------------------------------
col_h1, col_h2 = st.columns([8, 2])
with col_h1:
    st.markdown('<h1 class="hero-title">RoboPulse Intelligence</h1>', unsafe_allow_html=True)
    st.markdown('<p class="hero-sub">홈로봇 관련 데이터 수집 자동화 엔진 — Powered by Local Gemma 4</p>', unsafe_allow_html=True)
with col_h2:
    st.markdown(f"<div style='text-align:right;color:#94a3b8;font-size:0.8rem;padding-top:14px'>{datetime.now().strftime('%m/%d %H:%M')}</div>", unsafe_allow_html=True)

st.markdown("")

# ---- 탭 구성 ------------------------------------------------
tab_monitor, tab_briefing, tab_graph, tab_chat, tab_settings = st.tabs([
    "자동화 모니터링", "AI 브리핑", "지식 그래프", "AI Chat", "설정 및 제어"
])

# Tab 1: 자동화 모니터링
with tab_monitor:
    st.info("수집 단계: 지정된 RSS 소스나 유튜브 채널에서 실시간으로 관련 데이터를 수집합니다.")
    c1, c2, c3, c4 = st.columns(4)
    for col, (label, val, unit) in zip([c1, c2, c3, c4], [
        ("오늘 수집", stats["today_total"], "건"),
        ("분석 완료", stats["today_processed"], "건"),
        ("대기 중", stats["pending"], "건"),
        ("누적 기사", stats["total"], "건")
    ]):
        with col:
            st.markdown(f'<div class="metric-card"><div class="metric-value">{val}</div><div class="metric-label">{label} ({unit})</div></div>', unsafe_allow_html=True)

    st.markdown("### 데이터 수집 현황")
    if stats["sources"]:
        import pandas as pd
        df = pd.DataFrame(stats["sources"])
        df.columns = ["소스", "수집량", "최근수집"]
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("수집된 데이터 소스가 없습니다.")

    st.markdown("### 데이터 수집")
    cb1, cb2 = st.columns(2)
    with cb1:
        if st.button("뉴스 수집 실행", use_container_width=True, type="primary"):
            if is_live:
                with st.spinner("뉴스 수집 중..."): job_fetch_news()
                st.rerun()
            else: st.warning("DB 연결이 필요합니다.")
    with cb2:
        if st.button("영상 수집 실행", use_container_width=True):
            if is_live:
                with st.spinner("영상 수집 중..."): job_fetch_videos()
                st.rerun()
            else: st.warning("DB 연결이 필요합니다.")
                
    st.markdown("### AI 분석")
    ca1, ca2 = st.columns(2)
    with ca1:
        if mgr["active"]:
            st.button("AI 분석 진행 중...", use_container_width=True, type="secondary", disabled=True)
        else:
            if st.button("미처리 데이터 AI 분석", use_container_width=True, type="primary"):
                if is_live:
                    run_analysis_in_background()
                    st.toast("AI 분석을 백그라운드에서 시작합니다.")
                    st.rerun()
                else: 
                    st.warning("DB 연결이 필요합니다.")
    with ca2:
        st.caption("수집은 되었으나 아직 AI 분석(요약, 엔티티 추출 등)이 완료되지 않은 기사들을 처리합니다.")

    # 로그 섹션
    log_label = "LOGS" if is_live else "파이프라인 로그 (데모)"
    with st.expander(log_label, expanded=is_live):
        if is_live:
            st.info("상세 로그는 서버 터미널을 확인해 주세요.")
        else:
            st.code("[10:00:01] 뉴스 수집 시작...\n[10:02:15] 분석 완료 및 DB 저장", language="text")

# Tab 5: 설정 및 제어
with tab_settings:
    sub_tab_sources, sub_tab_system = st.tabs(["수집 소스 관리", "시스템 제어"])
    
    # --- 서브 탭 1: 수집 소스 관리 ---
    with sub_tab_sources:
        st.markdown("#### 데이터 수집 루트 (RSS)")
        st.caption("시스템이 정기적으로 방문하여 로봇 뉴스를 수집할 사이트 목록입니다.")
        
        # 소스 추가 폼
        with st.expander("➕ 신규 수집 소스 추가", expanded=False):
            with st.form("add_source_form"):
                new_label = st.text_input("사이트 이름", placeholder="예: Robotics Business Review")
                new_url = st.text_input("RSS 피드 URL", placeholder="https://example.com/feed")
                new_name = "".join(filter(str.isalnum, new_label.lower())).replace(" ", "_")
                if st.form_submit_button("소스 등록"):
                    if new_label and new_url:
                        # 중복 체크
                        if any(s['url'] == new_url for s in sources):
                            st.warning("⚠️ 이미 등록된 뉴스 소스 URL입니다.")
                        else:
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
        
        st.markdown("#### 유튜브 채널 관리")
        st.caption("AI가 영상을 시청하고 자막을 분석할 공식 유튜브 채널 목록입니다.")
        
        with st.expander("➕ 신규 유튜브 채널 추가", expanded=False):
            with st.form("add_yt_form"):
                yt_label = st.text_input("채널 이름", placeholder="예: Figure AI")
                yt_url = st.text_input("채널 홈 URL", placeholder="https://www.youtube.com/@FigureAI")
                yt_name = "youtube_" + "".join(filter(str.isalnum, yt_label.lower())).replace(" ", "_")
                if st.form_submit_button("채널 등록"):
                    if yt_label and yt_url:
                        # 중복 체크
                        if any(s['channel_url'] == yt_url for s in yt_sources):
                            st.warning("⚠️ 이미 등록된 유튜브 채널 URL입니다.")
                        else:
                            add_youtube_source(yt_name, yt_url, yt_label)
                            st.success(f"'{yt_label}' 채널이 등록되었습니다.")
                            st.rerun()
                    else:
                        st.error("이름과 URL을 모두 입력해주세요.")

        yt_sources = get_youtube_sources() if is_live else []
        if yt_sources:
            for src in yt_sources:
                sc1, sc2, sc3, sc4 = st.columns([3, 4, 1, 1])
                with sc1: st.write(f"**{src['label']}**")
                with sc2: st.caption(src['channel_url'])
                with sc3:
                    is_active = st.toggle("활성", value=src['is_active'], key=f"yt_tog_{src['id']}")
                    if is_active != src['is_active']:
                        toggle_youtube_source(src['id'], is_active)
                        st.rerun()
                with sc4:
                    if st.button("삭제", key=f"yt_del_{src['id']}", type="secondary"):
                        delete_youtube_source(src['id'])
                        st.rerun()
                st.markdown("---")

        st.markdown("#### AI 기반 소스 추천")
        st.caption("로컬 LLM이 검색 엔진을 통해 유망한 로봇/기술 기업의 채널이나 RSS를 추천합니다.")
        st.info("이미 수집 중이거나 이전에 거절된 URL은 중복 추천되지 않습니다.")
        
        col_a1, col_a2 = st.columns([8, 2])
        with col_a2:
            if st.button("새 소스 탐색하기", help="DB의 최신 엔티티를 활용해 백그라운드 탐색을 시작합니다.", use_container_width=True):
                with st.spinner("Gemma 4가 신규 소스를 탐색 중..."):
                    from engine.source_explorer import discover_sources
                    discover_sources()
                st.success("자율 탐색 완료!")
                st.rerun()
                
        rec_sources = get_recommended_sources() if is_live else []
        if not rec_sources:
            st.info("현재 대기 중인 추천 소스가 없습니다.")
        else:
            for rec in rec_sources:
                st.markdown(f"**{rec['label']}** (`{rec['source_type']}`)")
                st.caption(f"추천 사유: {rec['reason']} | 링크: {rec['url']}")
                bt1, bt2, _, _ = st.columns([2, 2, 6, 1])
                with bt1:
                    if st.button("✅ 승인", key=f"rec_ok_{rec['id']}", type="primary", use_container_width=True):
                        # 승인 전 중복 체크
                        is_duplicate = False
                        if rec['source_type'] in ['video', 'youtube']:
                            if any(s['channel_url'] == rec['url'] for s in yt_sources):
                                is_duplicate = True
                        else:
                            if any(s['url'] == rec['url'] for s in sources):
                                is_duplicate = True
                        
                        if is_duplicate:
                            st.warning("⚠️ 이미 동일한 URL의 소스가 등록되어 있습니다.")
                            update_recommended_source_status(rec['id'], "rejected") # 중복인 경우 거절 처리하여 목록에서 제거
                        else:
                            update_recommended_source_status(rec['id'], "approved")
                            new_name = "".join(filter(str.isalnum, rec['label'].lower())).replace(" ", "_")
                            if rec['source_type'] in ['video', 'youtube']:
                                add_youtube_source("youtube_" + new_name, rec['url'], rec['label'])
                            else:
                                add_news_source(new_name, rec['url'], rec['label'])
                            st.toast(f"{rec['label']} 등록 완료!")
                        st.rerun()
                with bt2:
                    if st.button("거절", key=f"rec_no_{rec['id']}", use_container_width=True):
                        update_recommended_source_status(rec['id'], "rejected")
                        st.rerun()
                st.markdown("---")

    # --- 서브 탭 2: 시스템 제어 ---
    with sub_tab_system:
        st.markdown("#### AI 분석 스케줄링")
        st.caption("서버 부하가 적은 시간에 대규모 AI 분석(요약, 지식그래프 구성)을 일괄 수행합니다.")
        
        current_analysis_hour = int(os.getenv("ANALYSIS_CRON_HOUR", "2"))
        if "analysis_hour" not in st.session_state:
            st.session_state.analysis_hour = current_analysis_hour
            
        def on_hour_change():
            new_hr = st.session_state.analysis_hour
            success = update_analysis_schedule(new_hr)
            if success:
                st.toast(f"✅ AI 분석 스케줄이 '매일 새벽 {new_hr:02d}:30'으로 변경되었습니다.")
            else:
                st.toast("⚠️ 스케줄러가 활성화되지 않았습니다.", icon="⚠️")

        st.selectbox(
            "분석 시작 시간 (0~23시)", 
            options=list(range(24)), 
            format_func=lambda x: f"매일 {x:04d}시 30분",
            key="analysis_hour",
            on_change=on_hour_change
        )
        
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.markdown('<div style="background-color: #fff1f2; padding: 20px; border-radius: 10px; border: 1px solid #fda4af;">', unsafe_allow_html=True)
        st.markdown("<h4 style='color: #be123c; margin-top: 0;'>데이터 초기화</h4>", unsafe_allow_html=True)
        st.markdown("<p style='color: #9f1239; font-size: 0.9rem;'>초기화 시 모든 기사와 지식 그래프 데이터가 영구 삭제됩니다.</p>", unsafe_allow_html=True)
        
        if st.button("전체 데이터 초기화", type="primary", use_container_width=False):
            if is_live:
                with st.spinner("시스템 초기화 중..."):
                    clear_all_data(reset_sources=True)
                st.toast("✅ 모든 데이터가 삭제되었습니다.")
                import time
                time.sleep(1)
                st.rerun()
            else:
                st.error("DB가 연결되지 않았습니다.")
        st.markdown('</div>', unsafe_allow_html=True)

# Tab 2: AI 브리핑
with tab_briefing:
    st.info("심층 분석: Gemma 4 모델이 각 소스의 중요도를 평가하고 3줄 핵심 요약을 제공하는 인텔리전스 보고서입니다.")
    col_f1, col_f2 = st.columns([2, 2])
    with col_f1: 
        sentiment_options = {"positive": "긍정", "neutral": "중립", "negative": "부정"}
        selected_labels = st.multiselect("감성 필터", list(sentiment_options.values()), default=list(sentiment_options.values()))
        sentiment_filter = [k for k, v in sentiment_options.items() if v in selected_labels]
    with col_f2:
        min_importance = st.slider("최소 중요도", 0.0, 10.0, 3.0)

    st.markdown("---")
    filtered = [a for a in articles if a.get("sentiment", "neutral") in sentiment_filter and a.get("importance", 0) >= min_importance]
    if not filtered:
        st.info("조건에 맞는 결과가 없습니다.")
    else:
        for art in filtered:
            sentiment = art.get("sentiment", "neutral")
            thumbnail = art.get("thumbnail_url")
            img_tag = f'<img src="{thumbnail}" class="article-thumb" alt="thumbnail">' if thumbnail else ''
            importance = art.get("importance", 0.0)
            pub_date = art.get('published_at')
            pub_date_str = pub_date.strftime("%Y-%m-%d %H:%M") if hasattr(pub_date, "strftime") else (pub_date or "날짜 정보 없음")
            
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
                        <div style="margin-top: 8px; margin-bottom: 8px;">
                            {''.join([f'<span class="tag-badge">{t}</span>' for t in art.get('tags', []) if t and t != 'None'])}
                        </div>
                    </div>
                    <div class="article-meta" style="font-size: 0.8rem; color: #94a3b8; display: flex; justify-content: space-between;">
                        <span>🏢 {art.get('source')}</span>
                        <span>🕒 {pub_date_str}</span>
                    </div>
                </div>
            </div>
            """)

# Tab 3: 지식 그래프
with tab_graph:
    st.info("추출 단계: 뉴스 본문에서 기업, 기술, 관계를 추출하여 산업 지형도를 시각화합니다.")
    
    col_g1, col_g2 = st.columns([3, 1])
    
    with col_g1:
        G_full = get_graph() if is_live else nx.DiGraph()
        
    with col_g2:
        st.markdown("### 그래프 필터")
        top_n = st.slider("최대 표시 노드 수", 10, 100, 30)
        
        node_options = ["전체 보기"] + (sorted(list(G_full.nodes())) if G_full else [])
        focus_node = st.selectbox("특정 노드 집중 보기", options=node_options, 
                                  help="선택한 노드와 직접 연결된 이웃들만 시각화합니다.")
        st.markdown("---")
        st.markdown("**범례 (Legend)**")
        st.markdown("🔵 기업 (Company)")
        st.markdown("🟠 기술 (Technology)")
        st.markdown("🟢 제품 (Product)")
        st.markdown("🔴 기관 (Institution)")

    with col_g1:
        if G_full.number_of_nodes() == 0:
            st.info("그래프 데이터가 없습니다.")
        else:
            # 상위 노드 또는 특정 노드 필터링
            if focus_node and focus_node != "전체 보기":
                neighbors = list(G_full.neighbors(focus_node)) + list(G_full.predecessors(focus_node))
                sub_nodes = set(neighbors + [focus_node])
                subG = G_full.subgraph(sub_nodes)
            else:
                nodes_sorted = sorted(G_full.nodes(data=True), key=lambda x: x[1].get("mention_count", 0), reverse=True)[:top_n]
                subG = G_full.subgraph([n[0] for n in nodes_sorted])

            pos = nx.spring_layout(subG, k=1.0, seed=42)
            color_map = {"company": "#4338ca", "technology": "#f97316", "product": "#22c55e", "institution": "#ef4444", "unknown": "#94a3b8"}
            translate_type = {"company": "기업", "technology": "기술", "product": "제품", "institution": "기관", "unknown": "기타"}

            # 엣지(관계선) 생성 및 툴팁을 위한 마커 추적
            edge_traces = []
            mid_x, mid_y, edge_hover_texts = [], [], []
            
            for edge in subG.edges(data=True):
                x0, y0 = pos[edge[0]]
                x1, y1 = pos[edge[1]]
                weight = edge[2].get("weight", 1)
                preds = ", ".join(edge[2].get("predicates", []))
                
                # 가중치에 비례하여 두께(Width)를 다르게 선을 그림 (최대 5)
                lw = min(5.0, max(1.0, weight))
                edge_traces.append(go.Scatter(
                    x=[x0, x1, None], y=[y0, y1, None],
                    line=dict(width=lw, color='#CBD5E1' if weight == 1 else '#94A3B8'),
                    hoverinfo='none', mode='lines'
                ))
                
                # 정중앙 좌표 및 툴팁 텍스트 세팅
                mid_x.append((x0 + x1) / 2)
                mid_y.append((y0 + y1) / 2)
                edge_hover_texts.append(f"<b>{edge[0]} ↔ {edge[1]}</b><br>관계: {preds}<br>빈도: {weight}")

            # 엣지용 투명 툴팁 마커
            edge_tooltip_trace = go.Scatter(
                x=mid_x, y=mid_y,
                mode='markers',
                hoverinfo='text',
                hovertext=edge_hover_texts,
                marker=dict(size=12, color='rgba(0,0,0,0)'),
                showlegend=False
            )

            # 노드 생성
            node_x, node_y, node_colors, node_sizes, node_texts = [], [], [], [], []
            for node in subG.nodes():
                x, y = pos[node]
                node_x.append(x)
                node_y.append(y)
                attrs = subG.nodes[node]
                
                # LLM이 간혹 대문자(Company)로 출력할 경우를 대비해 소문자화
                ntype = str(attrs.get("type", "unknown")).strip().lower()
                
                mcount = attrs.get("mention_count", 1)
                kor_type = translate_type.get(ntype, "기타")
                degree = subG.degree(node)
                
                node_colors.append(color_map.get(ntype, color_map["unknown"]))
                node_sizes.append(max(15, min(65, 15 + mcount * 8)))
                node_texts.append(f"<b>{node}</b><br>분류: {kor_type}<br>연결 수: {degree}<br>언급 수: {mcount}")

            node_trace = go.Scatter(x=node_x, y=node_y, mode='markers+text', text=list(subG.nodes()), 
                                    textfont=dict(size=11, color='#1e293b'),
                                    textposition="top center", hoverinfo='text', hovertext=node_texts,
                                    marker=dict(color=node_colors, size=node_sizes, line_width=2, line_color='white'))

            fig = go.Figure(data=edge_traces + [edge_tooltip_trace, node_trace],
                         layout=go.Layout(showlegend=False, hovermode='closest', margin=dict(b=0, l=0, r=0, t=0),
                                          xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                                          yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
                                          height=600, plot_bgcolor='white'))
            st.plotly_chart(fig, use_container_width=True)

# Tab 4: AI Chat
with tab_chat:
    st.info("활용 단계: 수집된 최신 지식을 바탕으로 AI 분석가와 대화하며 인사이트를 얻습니다.")
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
