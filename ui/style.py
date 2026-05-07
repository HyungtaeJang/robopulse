import streamlit as st

def apply_global_styles():
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
    color: #4338ca;
    background: linear-gradient(135deg, #4338ca 0%, #7c3aed 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    margin: 0;
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
.tag-badge { 
    background: #eff6ff; color: #1d4ed8; padding: 1px 6px; border-radius: 4px; 
    font-size: 0.7rem; font-weight: 600; margin-right: 4px; border: 1px solid #dbeafe; 
    text-decoration: none; cursor: pointer; transition: all 0.2s;
}
.tag-badge:hover { background: #1d4ed8; color: #ffffff; border-color: #1d4ed8; }

/* 상태 인디케이터 Dot */
.status-dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; margin-right: 8px; }

div[data-testid="stTab"] button { font-size: 1rem !important; font-weight: 600 !important; }

/* AI Chat & Bottom Interface - Premium Refinement */
/* 채팅 입력창 너비 제한 해제 및 정렬 동기화 */
[data-testid="stChatInput"] {
    max-width: 100% !important;
    margin: 0 !important;
    background-color: #ffffff !important;
    border: none !important;
    border-radius: 12px !important;
    box-shadow: 0 2px 10px rgba(0, 0, 0, 0.02) !important;
}

/* 하단 고정 영역(챗봇 컨테이너 등) 단일 레이어로 투명도/블러 처리 */
[data-testid="stBottom"] {
    background: rgba(255, 255, 255, 0.35) !important;
    backdrop-filter: blur(16px) !important;
    -webkit-backdrop-filter: blur(16px) !important;
    box-shadow: 0 -4px 15px rgba(0, 0, 0, 0.03) !important;
    border-top: 1px solid rgba(255, 255, 255, 0.3) !important;
    border-top-left-radius: 24px !important;
    border-top-right-radius: 24px !important;
    padding-top: 12px !important;
}

/* 이중 레이어 방지를 위해 하위 컨테이너 배경 투명화 */
[data-testid="stBottom"] > * {
    background: transparent !important;
    padding-bottom: 0px !important;
}

/* 컴포넌트 전용 유틸리티 클래스 */
.comp-header-box {
    background-color: #f8fafc; padding: 20px; border-radius: 10px; 
    border-left: 5px solid #3b82f6; margin-bottom: 20px; margin-top: 30px;
}
.comp-header-inner { display: flex; align-items: center; gap: 15px; }
.comp-header-title { flex: 1; font-size: 18px; font-weight: bold; color: #1e293b; }
.comp-header-vs { font-size: 24px; font-weight: bold; color: #3b82f6; padding: 0 10px; }

.filter-alert-box {
    background-color: #fffbeb; padding: 10px 15px; border-radius: 8px; 
    border: 1px solid #fcd34d; margin-bottom: 15px; font-size: 14px; color: #92400e;
}

.stat-badge-container { display: flex; gap: 8px; margin-bottom: 20px; flex-wrap: wrap; align-items: center; }
.stat-badge { padding: 2px 10px; border-radius: 4px; font-size: 11px; border: 1px solid #e2e8f0; }
.badge-test { color: #475569; background-color: #f8fafc; }
.badge-sig { border-width: 1px; }
.badge-metric { color: #334155; border-color: #cbd5e1; background-color: #f1f5f9; }
</style>
    """, unsafe_allow_html=True)
