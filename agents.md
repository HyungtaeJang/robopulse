# NewsStream Project Development Environment

이 문서는 AI 에이전트(Antigravity)가 NewsStream 프로젝트를 작업할 때 준수해야 할 환경 정보를 담고 있습니다.

## 🖥️ 하드웨어 구성

### 1. 개발용 맥북 (Workplace)
- **용도**: 코드 작성 및 수정 전용.
- **경로**: `/Users/hyungtaejang/MySW/robopulse`
- **특징**: 
  - 코딩만 수행하며, 실제 DB나 Redis 등 백엔드 서비스는 실행되지 않음.
  - 가상 환경(`venv`)이나 의존성 패키지가 완벽하지 않을 수 있음.
  - **주의**: 이 환경에서 직접 DB 패치 명령(`psql`, `python3 patch.py` 등)을 실행하면 실패함.

### 2. 실행용 맥스튜디오 (Target Server)
- **용도**: 실제 서비스 가동 및 데이터 처리.
- **경로**: `/Users/hyungtaejang/Git/robopulse`
- **배포 방식**: 맥북에서 코드를 수정 후 Push하면, 사용자가 맥스튜디오에서 `git pull`하여 실행함.
- **인프라**:
  - **Database**: PostgreSQL (pgvector 설치됨)
  - **Cache**: Redis
  - **LLM**: LM Studio (Gemma 4 26B 가동 중)
  - **Python**: 가상 환경(`venv`) 구축됨.

## 🚀 에이전트 지침

1. **DB 스키마 변경 시**: 
   - 맥북 터미널에서 `psql`이나 스크립트를 직접 실행하지 마십시오.
   - 대신, 서비스 코드(예: `db/vector_store.py`)가 실행될 때 자동으로 스키마를 체크하고 컬럼을 생성하는 **Self-Healing(Migrating)** 로직을 작성하십시오.
   - 또는 사용자가 맥스튜디오 터미널에서 실행할 수 있는 별도의 마이그레이션 스크립트를 제공하고 안내하십시오.

2. **의존성 추가 시**:
   - `requirements.txt`에 기록하고, 사용자가 맥스튜디오에서 업데이트할 수 있도록 안내하십시오.

3. **테스트 및 검증**:
   - 맥북 환경에서의 실행 실패는 무시하되, 코드 로직의 정합성을 최우선으로 검토하십시오.
   - 실제 동작 여부는 사용자가 맥스튜디오에서 확인해야 함을 명시하십시오.
