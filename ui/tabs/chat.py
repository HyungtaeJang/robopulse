import streamlit as st
from db.vector_store import semantic_search, get_lms_client, get_domain

def render_tab_chat(is_live, LMS_MODEL_NAME):
    selected_domain_key = st.session_state.selected_domain_key
    
    # 도메인 정보 로드
    domain_name = "홈로봇"
    custom_system_prompt = None
    if is_live:
        dom_info = get_domain(selected_domain_key)
        if dom_info:
            domain_name = dom_info["name"]
            custom_system_prompt = dom_info.get("system_prompt")

    st.info(f"💡 활용 단계: 수집된 최신 지식을 바탕으로 '{domain_name}' AI 분석가와 대화하며 인사이트를 얻습니다.")
    
    # 도메인 전환 시 대화 기록 초기화
    if "chat_domain_key" not in st.session_state or st.session_state.chat_domain_key != selected_domain_key:
        st.session_state.chat_domain_key = selected_domain_key
        st.session_state.chat_history = [
            {"role": "assistant", "content": f"안녕하세요! '{domain_name}' 관련 정보 수집 및 분석을 도와주는 AI 어시스턴트입니다. 궁금한 점을 질문해 주세요."}
        ]

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
                    # 선택된 도메인 격리 검색
                    results = semantic_search(user_input, top_k=3, domain_key=selected_domain_key)
                    context = "\n".join([f"- {r['title']}: {r['summary']}" for r in results])
                    
                    # 시스템 프롬프트 결정
                    if custom_system_prompt:
                        sys_prompt = custom_system_prompt
                    else:
                        sys_prompt = f"당신은 '{domain_name}' 분야의 전문 산업 분석가입니다. 제공된 문맥을 바탕으로 신뢰할 수 있고 깊이 있는 답변을 작성하세요. 한국어로 성실하게 답변해야 합니다."
                    
                    # 공용 클라이언트 사용 (프록시 우회 자동 적용)
                    client = get_lms_client()
                    resp = client.chat.completions.create(
                        model=LMS_MODEL_NAME,
                        messages=[
                            {"role": "system", "content": sys_prompt}, 
                            {"role": "user", "content": f"문맥:\n{context}\n\n질문: {user_input}"}
                        ],
                        temperature=0.3
                    )
                    answer = resp.choices[0].message.content
                except Exception as e: 
                    answer = f"연결 오류: {e}"
            else:
                answer = f"데모 모드입니다. '{domain_name}' 도메인에 대한 가상 RAG 답변입니다."
                
            st.write(answer)
            st.session_state.chat_history.append({"role": "assistant", "content": answer})
