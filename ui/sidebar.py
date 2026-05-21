import streamlit as st
import threading
from db.vector_store import get_domains

def render_sidebar(is_live, conn_status, scheduler_jobs, mgr, run_analysis_callback, start_scheduler_callback, job_fetch_news_callback, job_fetch_videos_callback, LMS_MODEL_NAME):
    with st.sidebar:
        if is_live:
            st.markdown('<div class="mode-badge" style="background:#dcfce7; color:#166534">Live Mode</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="mode-badge" style="background:#f1f5f9; color:#64748b">Demo Mode</div>', unsafe_allow_html=True)
        
        st.markdown("---")
        
        # 0. 도메인 선택 (다중 도메인 연동)
        if is_live:
            try:
                domains = get_domains()
            except Exception:
                domains = []
        else:
            domains = []
            
        if not domains:
            domains = [{"key": "home_robot", "name": "홈로봇"}]
            
        dom_keys = [d["key"] for d in domains]
        dom_names = [d["name"] for d in domains]
        
        # 세션 상태 안전하게 확인 및 동기화
        curr_key = st.session_state.get("selected_domain_key", "home_robot")
        if curr_key not in dom_keys:
            curr_key = dom_keys[0]
            st.session_state.selected_domain_key = curr_key
            
        default_idx = dom_keys.index(curr_key)
        
        st.markdown('<p style="font-size:0.85rem; font-weight:700; color:#475569; margin-bottom:5px;">수집 도메인 선택</p>', unsafe_allow_html=True)
        selected_name = st.selectbox(
            "도메인 선택",
            options=dom_names,
            index=default_idx,
            label_visibility="collapsed",
            key="sidebar_domain_select"
        )
        
        selected_key = dom_keys[dom_names.index(selected_name)]
        if selected_key != st.session_state.selected_domain_key:
            st.session_state.selected_domain_key = selected_key
            st.rerun()
            
        st.markdown("---")
        
        # 1. 시스템 상태
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
                    start_scheduler_callback()
                    st.rerun()
 
        # 2. 연결 상태
        all_connected = all(conn_status.values()) if conn_status else False
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
            if conn_status:
                status_row("PostgreSQL", conn_status.get("postgres", False))
                status_row("Redis", conn_status.get("redis", False))
                status_row("Local LLM", conn_status.get("lms", False))
                
                if is_live and not conn_status.get("lms", False):
                    st.warning("Local LLM 연결 확인 필요")
 
        # 3. AI 분석 진행 상태
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
 
        st.markdown("---")
        st.markdown('<p style="font-size:0.85rem; font-weight:700; color:#475569; margin-bottom:10px;">시스템 제어</p>', unsafe_allow_html=True)
        
        if st.session_state.get("system_status"):
            st.success(st.session_state.system_status)
            if st.button("상태 지우기", key="clear_status"):
                st.session_state.system_status = None
                st.rerun()
 
        sc_col1, sc_col2 = st.columns(2)
        with sc_col1:
            if st.button("뉴스 수집", use_container_width=True, type="primary"):
                if is_live:
                    with st.spinner("수집 중..."): job_fetch_news_callback(domain_key=st.session_state.selected_domain_key)
                    st.session_state.system_status = "뉴스 수집이 완료되었습니다."
                    st.rerun()
        with sc_col2:
            if st.button("영상 수집", use_container_width=True):
                if is_live:
                    with st.spinner("수집 중..."): job_fetch_videos_callback(domain_key=st.session_state.selected_domain_key)
                    st.session_state.system_status = "영상 수집이 완료되었습니다."
                    st.rerun()
        
        if not mgr["active"]:
            if st.button("AI 심층 분석 실행", use_container_width=True, type="primary"):
                if is_live:
                    run_analysis_callback(domain_key=st.session_state.selected_domain_key)
                    st.session_state.system_status = "AI 분석을 시작합니다 (백그라운드)."
                    st.rerun()
 
        st.caption(f"Model: {LMS_MODEL_NAME.split('/')[-1]}")
