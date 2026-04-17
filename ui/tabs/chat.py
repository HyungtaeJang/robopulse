import streamlit as st
from db.vector_store import semantic_search, get_lms_client

def render_tab_chat(is_live, LMS_MODEL_NAME):
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
