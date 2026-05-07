import streamlit as st

def render_tab_briefing(stats, articles):
    # 1. 상단 통계 메트릭
    st.markdown("### 오늘의 통계")
    c1, c2, c3, c4 = st.columns(4)
    for col, (label, val, unit) in zip([c1, c2, c3, c4], [
        ("오늘 수집", stats["today_total"], "건"),
        ("분석 완료", stats["today_processed"], "건"),
        ("대기 중", stats["pending"], "건"),
        ("누적 기사", stats["total"], "건")
    ]):
        with col:
            st.markdown(f'<div class="metric-card"><div class="metric-value">{val}</div><div class="metric-label">{label} ({unit})</div></div>', unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    
    # --- 상단 필터 바 ---
    # 여백 제거를 위해 4칸으로 재조정 (전체 너비 가득 채움)
    f_col1, f_col2, f_col3, f_col5 = st.columns([1.5, 1.5, 4, 3])
    
    with f_col1:
        # 체크박스 변경 시 즉시 반영을 위해 value와 session_state 비교 후 rerun
        t_only = st.checkbox("오늘 정보만", value=st.session_state.briefing_today_only)
        if t_only != st.session_state.briefing_today_only:
            st.session_state.briefing_today_only = t_only
            st.rerun()
    
    with f_col2:
        prev_sort = st.session_state.briefing_sort_by
        st.selectbox(
            "정렬", 
            options=["date", "importance"], 
            format_func=lambda x: "최신순" if x == "date" else "중요도순",
            key="briefing_sort_by"
        )
        if st.session_state.briefing_sort_by != prev_sort:
            st.rerun()
    
    with f_col3:
        # 감성 필터 레이블 변경: Sentiment
        sentiment_options = {"positive": "긍정", "neutral": "중립", "negative": "부정"}
        selected_sentiments = st.multiselect("Sentiment", list(sentiment_options.values()), default=list(sentiment_options.values()), key="sentiment_multiselect")
        sentiment_filter = [k for k, v in sentiment_options.items() if v in selected_sentiments]
 
    with f_col5:
        # 슬라이더 변경 시 즉시 반영
        prev_imp = st.session_state.briefing_min_importance
        st.session_state.briefing_min_importance = st.slider(
            "최소 별점(중요도)", 
            min_value=0.0, max_value=10.0, step=0.5,
            value=st.session_state.briefing_min_importance,
            help="이 점수 이상의 기사만 표시합니다."
        )
        if st.session_state.briefing_min_importance != prev_imp:
            st.rerun()
 
    # 태그 필터가 있을 때만 안내창과 함께 초기화 버튼 표시 (여백 문제 해결)
    if st.session_state.briefing_filter_tag:
        i_col1, i_col2 = st.columns([8.5, 1.5])
        with i_col1:
            st.info(f"선택된 태그 필터: **#{st.session_state.briefing_filter_tag}**")
        with i_col2:
            st.markdown("<div style='margin-top: 25px;'>", unsafe_allow_html=True) # 레이블 높이 맞춤용
            if st.button("필터 초기화 🔄", use_container_width=True):
                st.session_state.briefing_filter_tag = None
                st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("---")
    
    # 필터링 적용 (감성 필터는 메모리에서 수동 필터링)
    filtered = [a for a in articles if a.get("sentiment", "neutral") in sentiment_filter]
    
    if not filtered:
        if st.session_state.briefing_today_only and stats["pending"] > 0:
            st.warning(f"💡 현재 **{stats['pending']}건**의 데이터가 분석 대기 중입니다. 분석이 완료되면 여기에 표시됩니다.")
        else:
            st.info("조건에 맞는 결과가 없습니다.")
    else:
        for art in filtered:
            sentiment = art.get("sentiment", "neutral")
            thumbnail = art.get("thumbnail_url")
            # 소스 아이콘 결정 로직
            source_name = art.get('source', '알 수 없음')
            url_str = art.get('url', '')
            source_icon = "🏢" 
            
            if "google.com" in url_str or "구글" in source_name:
                source_icon = '<img src="https://www.google.com/s2/favicons?domain=google.com&sz=32" style="width:14px; height:14px; vertical-align:middle; margin-right:4px; margin-bottom:2px;">'
            elif "youtube.com" in url_str or "youtu.be" in url_str or "유튜브" in source_name:
                source_icon = '<img src="https://www.google.com/s2/favicons?domain=youtube.com&sz=32" style="width:14px; height:14px; vertical-align:middle; margin-right:4px; margin-bottom:2px;">'
            elif "techcrunch.com" in url_str:
                source_icon = '<img src="https://www.google.com/s2/favicons?domain=techcrunch.com&sz=32" style="width:14px; height:14px; vertical-align:middle; margin-right:4px; margin-bottom:2px;">'
            elif "ieee.org" in url_str:
                source_icon = '<img src="https://www.google.com/s2/favicons?domain=ieee.org&sz=32" style="width:14px; height:14px; vertical-align:middle; margin-right:4px; margin-bottom:2px;">'
            else:
                source_icon = f'<span style="margin-right:4px;">{source_icon}</span>'

            # 썸네일도 클릭 시 새 탭으로 연결되도록 링크 씌우기
            img_tag = f'<a href="{art["url"]}" target="_blank" rel="noopener noreferrer"><img src="{thumbnail}" class="article-thumb" alt="thumbnail"></a>' if thumbnail else ''
            importance = art.get("importance", 0.0)
            
            # 날짜 보완: published_at이 없으면 collected_at(수집일) 사용
            pub_date = art.get('published_at')
            if pub_date:
                # 발행일이 있는 경우 (📅 아이콘으로 강조)
                date_label = "📅 발행"
                date_val = pub_date.strftime("%Y-%m-%d %H:%M") if hasattr(pub_date, "strftime") else str(pub_date)
            else:
                # 없는 경우 수집일 표시
                date_label = "📥 수집"
                coll_date = art.get('collected_at')
                date_val = coll_date.strftime("%Y-%m-%d %H:%M") if hasattr(coll_date, "strftime") else str(coll_date)
            
            # Key Points (불릿포인트) 구성
            key_points_html = ""
            raw_points = art.get('key_points')
            if raw_points:
                points_list = raw_points.split('\n')
                points_li = "".join([f"<li style='margin-bottom:4px;'>{p.strip()}</li>" for p in points_list if p.strip()])
                key_points_html = f"""
                <div style="margin-top: 10px; padding: 10px; background: #f8fafc; border-radius: 6px; border-left: 3px solid #cbd5e1;">
                    <p style="font-size: 0.85rem; font-weight: 700; color: #475569; margin-bottom: 5px;">핵심 요점 (Key Points)</p>
                    <ul style="font-size: 0.85rem; color: #334155; padding-left: 20px; margin: 0;">{points_li}</ul>
                </div>
                """
            
            tags = art.get('tags', [])
            tag_html = ""
            if tags and tags[0] is not None:
                valid_tags = [t for t in tags if t and t != 'None'][:8]
                if valid_tags:
                    tags_spans = "".join([f'<span class="tag-badge">#{tag}</span>' for tag in valid_tags])
                    tag_html = f'<div style="margin-top: 5px;">{tags_spans}</div>'

            # HTML 코드가 노출되지 않도록 들여쓰기를 제거한 한 줄 형태로 결합하여 렌더링 (target="_blank" 호환성 확보)
            card_html = (
                f'<div class="article-card {sentiment}" style="display: flex; gap: 20px; align-items: stretch;">'
                f'{img_tag}'
                f'<div style="flex: 1; display: flex; flex-direction: column; justify-content: space-between;">'
                f'<div><div style="display: flex; justify-content: space-between; align-items: flex-start;">'
                f'<a href="{art["url"]}" target="_blank" rel="noopener noreferrer" class="article-title">{art["title"]}</a>'
                f'<span class="badge-importance">⭐ {importance:.1f}</span></div>'
                f'<p class="article-summary">{art.get("summary", "요약 정보가 없습니다.")}</p>'
                f'{key_points_html}</div>'
                f'<div class="article-meta" style="font-size: 0.8rem; color: #94a3b8; display: flex; flex-direction: column; justify-content: flex-end; margin-top: 12px;">'
                f'<div style="display: flex; justify-content: space-between; margin-bottom: 8px;">'
                f'<span>{source_icon}{source_name}</span><span>{date_label}: {date_val}</span></div>'
                f'{tag_html}</div></div></div>'
            )
            st.markdown(card_html, unsafe_allow_html=True)

        # 3. 하단 데이터 수집 현황 (간결한 형태)
        st.markdown("---")
        with st.expander("📊 데이터 수집 상세 현황 (Source Wise)", expanded=False):
            if stats["sources"]:
                import pandas as pd
                df = pd.DataFrame(stats["sources"])
                df.columns = ["소스", "수집량", "최근수집"]
                st.dataframe(df, use_container_width=True, hide_index=True)
            else:
                st.info("수집된 데이터 소스가 없습니다.")
