# NewsStream Project Development Environment

이 문서는 AI 에이전트가 NewsStream(robopulse) 프로젝트를 작업할 때 준수해야 할 환경 정보를 담고 있습니다.

## 🖥️ 실행 환경 (개발/운영 통합)

- **위치**: 맥스튜디오 `/Users/hyungtaejang/Git/robopulse`
- 코드 작성과 실제 서비스 가동을 모두 이 맥스튜디오에서 수행합니다. (과거의 "맥북에서 코드 수정 → push → 맥스튜디오에서 pull" 2단 구조는 더 이상 사용하지 않음)
- **인프라** (모두 이 머신에서 가동 중, 상세는 `~/Git/INFRA.md` 참고):
  - **Database**: PostgreSQL 16 (Homebrew 서비스, pgvector 설치됨), DB명 `newsstream`
  - **Cache**: Redis (Homebrew 서비스), DB index `0`
  - **LLM**: LM Studio (Gemma 4 26B), `http://localhost:1234/v1`
  - **Python**: 프로젝트 내 `venv/`
  - **대시보드**: PM2로 가동 중 (`pm2 restart robopulse`, 로그 `pm2 logs robopulse`), 포트 `8502` (`.streamlit/config.toml`). 실행 정의는 `~/Git/ecosystem.config.js`

## 🚀 에이전트 지침

1. **DB 스키마/데이터 변경 시**:
   - 스키마 변경은 서비스 코드(예: `db/vector_store.py`)의 Self-Healing(기동 시 누락 테이블/컬럼 자동 생성) 로직으로 처리하는 것을 기본으로 합니다.
   - 데이터 자체의 수정·보정이 필요하면 `psql` 등으로 직접 수정해도 됩니다.

2. **의존성 추가 시**:
   - `requirements.txt`에 기록하고 `venv/`에 직접 설치합니다.

3. **테스트 및 검증**:
   - DB/Redis/LM Studio에 실제로 연결되는 환경이므로, 실행 오류는 무시하지 말고 원인을 확인합니다.
   - 대시보드는 운영 중인 서비스이므로 재시작이 필요하면 사용자에게 먼저 알립니다.
