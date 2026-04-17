import streamlit as st
import os
from db.vector_store import (
    get_news_sources, add_news_source, toggle_news_source, delete_news_source,
    get_youtube_sources, add_youtube_source, toggle_youtube_source, delete_youtube_source,
    get_recommended_sources, update_recommended_source_status, clear_all_data
)
from scheduler.pipeline_scheduler import update_analysis_schedule

def render_tab_settings(is_live):
    sub_tab_sources, sub_tab_system = st.tabs(["수집 소스 관리", "시스템 제어"])
    
    # --- 서브 탭 1: 수집 소스 관리 ---
    with sub_tab_sources:
        st.markdown("#### 데이터 수집 루트 (RSS)")
        st.caption("시스템이 정기적으로 방문하여 로봇 뉴스를 수집할 사이트 목록입니다.")
        
        with st.expander("➕ 신규 수집 소스 추가", expanded=False):
            with st.form("add_source_form"):
                new_label = st.text_input("사이트 이름", placeholder="예: Robotics Business Review")
                new_url = st.text_input("RSS 또는 기본 URL", placeholder="https://www.roboticsbusinessreview.com/feed/")
                source_type = st.selectbox("종류", ["news (뉴스 사이트)", "youtube (유튜브 채널)"])
                submitted = st.form_submit_button("추가하기")
                if submitted:
                    if not new_label or not new_url:
                        st.warning("이름과 URL을 모두 입력해주세요.")
                    else:
                        new_name = "".join(filter(str.isalnum, new_label.lower())).replace(" ", "_")
                        if "youtube" in source_type:
                            add_youtube_source("youtube_" + new_name, new_url, new_label)
                        else:
                            add_news_source(new_name, new_url, new_label)
                        st.toast(f"{new_label} 추가 완료!")
                        st.rerun()

        col_ns, col_ys = st.columns(2)
        with col_ns:
            st.markdown("##### 📰 뉴스 소스 목록")
            sources = get_news_sources() if is_live else []
            for src in sources:
                c1, c2, c3 = st.columns([6, 2, 2])
                with c1:
                    status = "✅" if src['is_active'] else "⛔"
                    st.markdown(f"{status} **{src['label']}**<br><span style='font-size:0.75rem;color:#94a3b8;'>{src['url']}</span>", unsafe_allow_html=True)
                with c2:
                    btn_text = "비활성" if src['is_active'] else "활성"
                    if st.button(btn_text, key=f"tgl_{src['id']}"):
                        toggle_news_source(src['id'], not src['is_active'])
                        st.rerun()
                with c3:
                    if st.button("삭제", key=f"del_{src['id']}", type="secondary"):
                        delete_news_source(src['id'])
                        st.toast("삭제되었습니다.")
                        st.rerun()
                st.markdown("---")
        
        with col_ys:
            st.markdown("##### 📺 유튜브 채널 목록")
            yt_sources = get_youtube_sources() if is_live else []
            for src in yt_sources:
                c1, c2, c3 = st.columns([6, 2, 2])
                with c1:
                    status = "✅" if src.get('is_active', True) else "⛔"
                    st.markdown(f"{status} **{src['label']}**<br><span style='font-size:0.75rem;color:#94a3b8;'>{src['channel_url']}</span>", unsafe_allow_html=True)
                with c2:
                    btn_text = "비활성" if src.get('is_active', True) else "활성"
                    if st.button(btn_text, key=f"tglyt_{src['id']}"):
                        toggle_youtube_source(src['id'], not src.get('is_active', True))
                        st.rerun()
                with c3:
                    if st.button("삭제", key=f"delyt_{src['id']}", type="secondary"):
                        delete_youtube_source(src['id'])
                        st.toast("채널이 삭제되었습니다.")
                        st.rerun()
                st.markdown("---")

        st.markdown("#### 💡 사용자 제안 수집 소스")
        st.caption("시스템 사용자들이 제안한 유용한 수집 소스(웹사이트 또는 유튜브 채널)입니다. 승인 시 자동 추가됩니다.")
        
        recommendations = get_recommended_sources() if is_live else []
        pending_recs = [r for r in recommendations if r['status'] == 'pending']
        
        if not pending_recs:
            st.info("현재 대기 중인 추천 소스가 없습니다.")
        else:
            for rec in pending_recs:
                rc1, rc2, rc3 = st.columns([6, 2, 2])
                with rc1:
                    type_icon = "📺" if rec['source_type'] in ['video', 'youtube'] else "📰"
                    st.markdown(f"{type_icon} **{rec['label']}**<br><span style='font-size:0.75rem;color:#94a3b8;'>{rec['url']}</span><br><span style='font-size:0.8rem;color:#64748b;'>추천 이유: {rec['reason']}</span>", unsafe_allow_html=True)
                with rc2:
                    if st.button("✅ 승인", key=f"rec_ok_{rec['id']}", type="primary", use_container_width=True):
                        is_duplicate = False
                        if rec['source_type'] in ['video', 'youtube']:
                            if any(s['channel_url'] == rec['url'] for s in yt_sources):
                                is_duplicate = True
                        else:
                            if any(s['url'] == rec['url'] for s in sources):
                                is_duplicate = True
                        
                        if is_duplicate:
                            st.warning("⚠️ 이미 동일한 URL의 소스가 등록되어 있습니다.")
                            update_recommended_source_status(rec['id'], "rejected")
                        else:
                            update_recommended_source_status(rec['id'], "approved")
                            new_name = "".join(filter(str.isalnum, rec['label'].lower())).replace(" ", "_")
                            if rec['source_type'] in ['video', 'youtube']:
                                add_youtube_source("youtube_" + new_name, rec['url'], rec['label'])
                            else:
                                add_news_source(new_name, rec['url'], rec['label'])
                            st.toast(f"{rec['label']} 등록 완료!")
                        st.rerun()
                with rc3:
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
