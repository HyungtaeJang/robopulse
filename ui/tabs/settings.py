import streamlit as st
import os
from db.vector_store import (
    get_news_sources, add_news_source, toggle_news_source, delete_news_source,
    get_youtube_sources, add_youtube_source, toggle_youtube_source, delete_youtube_source,
    get_recommended_sources, update_recommended_source_status, clear_all_data,
    get_available_lms_models, get_system_setting, set_system_setting,
    get_domains, add_domain, delete_domain,
    get_instant_seed_sources, inject_recommended_sources
)
from scheduler.pipeline_scheduler import update_analysis_schedule
from engine.source_explorer import discover_sources

def render_tab_settings(is_live):
    sub_tab_domains, sub_tab_sources, sub_tab_system = st.tabs(["도메인 설정 및 관리", "수집 소스 관리", "시스템 제어"])
    
    # --- 서브 탭 0: 도메인 설정 및 관리 ---
    with sub_tab_domains:
        st.markdown("#### 🌐 도메인 설정 및 관리")
        st.caption("새로운 분석 도메인(예: 전기자동차, 자율주행 등)을 추가하거나 기존 도메인을 삭제할 수 있습니다.")
        
        # 신규 도메인 추가 양식
        with st.expander("➕ 신규 도메인 추가", expanded=False):
            with st.form("add_domain_form"):
                new_dom_key = st.text_input("도메인 고유 영문 키", placeholder="예: ev")
                new_dom_name = st.text_input("도메인 한글 이름", placeholder="예: 전기자동차")
                new_dom_keywords_str = st.text_input("수집 관심 키워드 (쉼표로 구분)", placeholder="예: electric vehicle, ev, tesla, ionic")
                new_dom_prompt = st.text_area("커스텀 AI 시스템 프롬프트 (생략 시 기본 템플릿 사용)", placeholder="이 도메인의 기사를 분석하거나 AI Chat 시 유도할 전용 지침을 적어주세요.")
                
                dom_submitted = st.form_submit_button("추가하기")
                if dom_submitted:
                    if not new_dom_key or not new_dom_name:
                        st.warning("영문 키와 한글 이름을 모두 입력해주세요.")
                    elif not new_dom_key.strip().isalnum():
                        st.warning("영문 키는 숫자와 알파벳으로만 구성되어야 합니다.")
                    else:
                        keywords = [k.strip() for k in new_dom_keywords_str.split(",") if k.strip()]
                        if not keywords:
                            keywords = [new_dom_name]
                        
                        add_domain(new_dom_key.strip().lower(), new_dom_name.strip(), keywords, new_dom_prompt.strip() if new_dom_prompt else None)
                        st.toast(f"✅ '{new_dom_name}' 도메인이 추가되었습니다.")
                        st.session_state.selected_domain_key = new_dom_key.strip().lower()
                        st.rerun()
                        
        # 등록된 도메인 목록 표시
        st.markdown("##### 📋 등록된 도메인 목록")
        domains = get_domains() if is_live else [{"key": "home_robot", "name": "홈로봇", "keywords": ["home robot"]}]
        for dom in domains:
            d_col1, d_col2 = st.columns([8, 2])
            with d_col1:
                kw_str = ", ".join(dom["keywords"])
                st.markdown(f"**{dom['name']}** (`{dom['key']}`)<br><span style='font-size:0.75rem;color:#64748b;'>키워드: {kw_str}</span>", unsafe_allow_html=True)
                if dom.get("system_prompt"):
                    st.markdown("<span style='font-size:0.75rem;color:#1e3a8a;background-color:#eff6ff;padding:2px 6px;border-radius:4px;'>커스텀 시스템 프롬프트 있음</span>", unsafe_allow_html=True)
            with d_col2:
                if dom["key"] == "home_robot":
                    st.button("삭제", key=f"del_dom_{dom['key']}", disabled=True, help="기본 도메인은 삭제할 수 없습니다.")
                else:
                    if st.button("삭제", key=f"del_dom_{dom['key']}", type="secondary"):
                        delete_domain(dom["key"])
                        st.toast(f"🗑️ '{dom['name']}' 도메인 및 수집 소스, 기사 데이터가 연쇄 삭제되었습니다.")
                        if st.session_state.selected_domain_key == dom["key"]:
                            st.session_state.selected_domain_key = "home_robot"
                        st.rerun()
            st.markdown("---")
            
    # --- 서브 탭 1: 수집 소스 관리 ---
    with sub_tab_sources:
        selected_domain_key = st.session_state.selected_domain_key
        dom_name = "현재"
        if is_live:
            dom_info = next((d for d in domains if d["key"] == selected_domain_key), None)
            if dom_info:
                dom_name = dom_info["name"]
                
        st.markdown(f"#### 🌐 [ {dom_name} ] 도메인 수집 소스 관리")
        st.caption(f"선택한 '{dom_name}' 도메인에 대한 뉴스 RSS 및 유튜브 채널을 관리합니다.")
        
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
                            add_youtube_source("youtube_" + new_name, new_url, new_label, domain_key=selected_domain_key)
                        else:
                            add_news_source(new_name, new_url, new_label, domain_key=selected_domain_key)
                        st.toast(f"{new_label} 추가 완료!")
                        st.rerun()
 
        col_ns, col_ys = st.columns(2)
        with col_ns:
            st.markdown("##### 📰 뉴스 소스 목록")
            sources = get_news_sources(domain_key=selected_domain_key) if is_live else []
            if not sources:
                st.info("등록된 뉴스 소스가 없습니다.")
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
            yt_sources = get_youtube_sources(domain_key=selected_domain_key) if is_live else []
            if not yt_sources:
                st.info("등록된 유튜브 채널이 없습니다.")
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
 
        st.markdown("#### 🤖 AI 실시간 소스 발굴 및 즉석 추천")
        st.caption(f"'{dom_name}' 도메인을 완벽히 모니터링하기 위해 AI가 실시간으로 웹에서 전문 매체, 뉴스레터 RSS, 유튜브 채널을 발굴합니다.")
        
        # AI 실시간 자율 탐색 트리거
        if st.button("✨ 실시간 AI 소스 발굴 개시 (1분 소요)", use_container_width=True, type="primary"):
            if is_live:
                with st.spinner(f"AI가 현재 도메인('{dom_name}')의 성격을 심층 분석하고 실시간 쿼리를 동적 생성하여 인터넷을 탐색 중입니다..."):
                    get_instant_seed_sources(domain_key=selected_domain_key)
                st.success("✅ AI 실시간 소스 발굴 및 검증이 완료되었습니다! 아래에서 승인 후 등록해 주세요.")
                st.rerun()
            else:
                st.error("DB 연결이 필요합니다.")
 
        recommendations = get_recommended_sources(domain_key=selected_domain_key) if is_live else []
        pending_recs = [r for r in recommendations if r['status'] == 'pending']
        
        if not pending_recs:
            st.info("💡 대기 중인 추천 소스가 없습니다. 위 버튼을 눌러 AI에게 실시간 자율 발굴을 지시해 보세요!")
        else:
            st.markdown(f"##### 🎯 발굴된 추천 소스 목록 ({len(pending_recs)}건)")
            st.markdown("체크박스를 선택한 후 하단의 일괄 등록 버튼을 클릭하여 소스 수집에 즉시 투입하세요.")
            
            # 다중 선택 UI
            selected_urls = []
            
            for idx, rec in enumerate(pending_recs):
                type_icon = "📺" if rec['source_type'] in ['video', 'youtube'] else "📰"
                type_label = "유튜브 채널" if rec['source_type'] in ['video', 'youtube'] else "뉴스/RSS"
                
                # 가독성이 높은 Card Style Container 렌더링
                with st.container(border=True):
                    col_chk, col_info = st.columns([1, 19])
                    with col_chk:
                        is_selected = st.checkbox("", value=True, key=f"chk_rec_{rec['id']}_{idx}")
                        if is_selected:
                            selected_urls.append(rec['url'])
                    with col_info:
                        st.markdown(
                            f"**{type_icon} {rec['label']}** <span style='font-size:0.75rem;color:#3b82f6;background-color:#eff6ff;padding:2px 6px;border-radius:4px;'>{type_label}</span><br>"
                            f"<span style='font-size:0.75rem;color:#64748b;'>{rec['url']}</span><br>"
                            f"<span style='font-size:0.85rem;color:#1e293b;font-weight:500;'>💡 AI 추천 이유: {rec['reason']}</span>", 
                            unsafe_allow_html=True
                        )
            
            # 일괄 등록 버튼
            st.markdown("<br>", unsafe_allow_html=True)
            col_act1, col_act2 = st.columns(2)
            with col_act1:
                if st.button("🚀 선택한 소스 일괄 등록", use_container_width=True, type="primary"):
                    if selected_urls:
                        news_add, yt_add = inject_recommended_sources(selected_domain_key, selected_urls)
                        st.success(f"✅ 뉴스 {news_add}개, 유튜브 {yt_add}개 채널이 수집 소스에 정상 등록되었습니다!")
                        import time
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.warning("선택된 소스가 없습니다.")
            with col_act2:
                if st.button("❌ 대기 중인 추천 모두 거절", use_container_width=True, type="secondary"):
                    for rec in pending_recs:
                        update_recommended_source_status(rec['id'], "rejected")
                    st.toast("추천 목록이 거절 및 정리되었습니다.")
                    import time
                    time.sleep(1)
                    st.rerun()
 
    # --- 서브 탭 2: 시스템 제어 ---
    with sub_tab_system:
        st.markdown("#### AI 분석 스케줄링")
        st.caption("서버 부하가 적은 시간에 대규모 AI 분석(요약, 지식그래프 구성)을 일괄 수행합니다.")
        
        current_analysis_hour = int(os.getenv("ANALYSIS_CRON_HOUR", "4"))
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
            format_func=lambda x: f"매일 {x:02d}시 30분",
            key="analysis_hour",
            on_change=on_hour_change
        )
        
        # --- 추가된 기능: 분석 배치 크기 설정 ---
        st.markdown("<br>", unsafe_allow_html=True)
        current_batch_limit = int(get_system_setting("analysis_batch_limit", "100"))
        
        def on_batch_limit_change():
            new_limit = st.session_state.analysis_batch_limit_input
            set_system_setting("analysis_batch_limit", str(new_limit))
            st.toast(f"✅ AI 분석 배치 크기가 {new_limit}건으로 변경되었습니다.")
 
        st.number_input(
            "AI 분석 배치 크기 (한 번에 분석할 개수)",
            min_value=1, max_value=1000,
            value=current_batch_limit,
            step=10,
            key="analysis_batch_limit_input",
            on_change=on_batch_limit_change,
            help="수동/자동 분석 시 한 번에 처리할 기사의 최대 개수입니다."
        )
 
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("#### 중복 기사 필터링 (Semantic Dedup)")
        
        # 중복 제거 활성화 토글
        is_dedup_enabled = get_system_setting("semantic_dedup_enabled", "True") == "True"
        def on_dedup_toggle():
            val = st.session_state.semantic_dedup_toggle
            set_system_setting("semantic_dedup_enabled", str(val))
            st.toast(f"✅ 유사 기사 중복 필터링이 {'활성화' if val else '비활성화'}되었습니다.")
 
        st.toggle(
            "유사 기사 중복 필터링 사용",
            value=is_dedup_enabled,
            key="semantic_dedup_toggle",
            on_change=on_dedup_toggle,
            help="내용이 유사한 기사를 자동으로 걸러냅니다."
        )
 
        # 유사도 임계값 설정
        current_threshold = float(get_system_setting("semantic_dedup_threshold", "0.95"))
        def on_threshold_change():
            val = st.session_state.semantic_dedup_threshold_slider
            set_system_setting("semantic_dedup_threshold", f"{val:.2f}")
            st.toast(f"✅ 중복 판단 임계값이 {val:.2f}로 설정되었습니다.")
 
        st.slider(
            "중복 판단 유사도 임계값",
            min_value=0.70, max_value=0.99,
            value=current_threshold,
            step=0.01,
            key="semantic_dedup_threshold_slider",
            on_change=on_threshold_change,
            help="높을수록(1.0에 가까울수록) 아주 똑같은 기사만 걸러내고, 낮을수록 비슷한 주제도 모두 걸러냅니다. 권장값: 0.95"
        )
        
        st.markdown("---")
        st.markdown("#### Local LLM 모델 설정")
        st.caption("AI 분석 및 챗에 사용할 모델을 선택합니다. LM Studio에 로드된 모델만 표시됩니다.")
        
        available_models = get_available_lms_models()
        if available_models:
            # 현재 세팅된 모델이 리스트에 없으면 첫 번째 선택
            current_idx = 0
            if st.session_state.get("lms_model") in available_models:
                current_idx = available_models.index(st.session_state.lms_model)
            
            def on_model_change():
                st.session_state.lms_model = st.session_state.model_selector
                st.toast(f"✅ 사용 모델이 '{st.session_state.lms_model}'로 변경되었습니다.")
 
            st.selectbox(
                "로드된 모델 목록",
                options=available_models,
                index=current_idx,
                key="model_selector",
                on_change=on_model_change
            )
        else:
            st.error("⚠️ 로드된 모델을 찾을 수 없습니다. LM Studio를 확인하세요.")
            if st.button("모델 목록 새로고침"):
                st.rerun()
 
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
