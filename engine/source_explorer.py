"""
engine/source_explorer.py
-------------------------
AI가 자율적으로 신규 정보 소스(RSS/YouTube)를 발굴하고 검증하여 추천합니다.
duckduckgo-search를 이용해 실시간 웹 정보를 가져오고 Gemma로 판단합니다.
"""
import logging
import json
import warnings
from datetime import datetime

# 향후 패키지명(ddgs) 변경 예고인 RuntimeWarning 숨김 처리
warnings.filterwarnings("ignore", category=RuntimeWarning, module="duckduckgo_search.*")

# duckduckgo_search 관련 단순 안내 경고 숨기기
warnings.filterwarnings("ignore", message="This package .* has been renamed to ddgs")

from duckduckgo_search import DDGS
from engine.graph_builder import get_entity_stats
from db.vector_store import get_lms_client, add_recommended_source
from engine.gemma_worker import LMS_MODEL

logger = logging.getLogger(__name__)

def discover_sources():
    """
    지식 그래프에서 부상하는 엔티티를 추출해 웹을 탐색하고,
    양질의 신규 소스를 발굴하여 추천 DB에 적재합니다.
    """
    logger.info("🔍 [AI 자율 탐색] 신규 데이터 소스 발굴 시작...")
    start_time = datetime.now()

    # 1. 대상 키워드 추출 (가중치 부여)
    stats = get_entity_stats()
    target_entities = [e["name"] for e in stats if e["type"] in ("company", "technology")][:3]
    
    if not target_entities:
        logger.info("탐색할 주요 엔티티가 충분하지 않습니다. 홈로봇 핵심 타겟 사용.")
        target_entities = ["Figure AI", "Tesla Optimus", "Unitree Robotics", "1X Technologies", "Apptronik"]

    logger.info(f"선정된 탐색 타겟: {target_entities}")

    new_recommendations_count = 0
    client = get_lms_client()

    for entity in target_entities:
        # 홈로봇/휴머노이드 전문성을 위한 쿼리 파라미터 강화
        rss_query = f"{entity} humanoid home robotics official news rss OR blog"
        yt_query = f"{entity} humanoid official youtube channel robotics domestic"

        for query, search_type in [(rss_query, "news"), (yt_query, "youtube")]:
            try:
                import time
                results = []
                # 반복 요청 시 IP 블록/RateLimit(202) 방지를 위해 지연 시간 추가
                time.sleep(2)
                # html 백엔드가 좀 더 안정적임
                try:
                    with DDGS() as ddgs:
                        for r in ddgs.text(query, backend="html", max_results=3):
                            results.append(r)
                except Exception:
                    # 실패 시 독립된 세션으로 lite 폴백
                    time.sleep(2)
                    try:
                        with DDGS() as ddgs2:
                            for r in ddgs2.text(query, backend="lite", max_results=3):
                                results.append(r)
                    except Exception as e2:
                        logger.warning(f"Lite 백엔드 재시도 실패: {e2}")
                
                if not results:
                    continue
                
                # 3. Gemma 4에게 검증 및 추출 요청
                prompt = f"""
다음은 '{entity}'에 대해 '{query}'로 검색한 웹 결과입니다.
이 중 로봇 산업 모니터링을 위해 수집할 가치가 있는 '공식 블로그/RSS' 또는 '공식 유튜브 채널'의 URL이 있다면 하나만 추출하세요.
없거나 쓸모없는 정보라면 빈 문자열을 반환하세요.

검색 결과:
{json.dumps(results, ensure_ascii=False, indent=2)}

출력 형식(반드시 아래 JSON만 출력, 다른 말 금지):
{{
  "url": "찾은 URL (없으면 빈 문자열)",
  "source_type": "{'video' if search_type == 'youtube' else 'news'}",
  "label": "채널 또는 블로그의 UI 표시 이름",
  "reason": "추천하는 이유 (1줄)"
}}
"""
                resp = client.chat.completions.create(
                    model=LMS_MODEL,
                    messages=[
                        {"role": "system", "content": "당신은 AI 데이터 엔지니어입니다."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.1
                )
                
                content = resp.choices[0].message.content.strip()
                # Markdown block 제거
                if content.startswith("```"):
                    content = "\n".join(content.split("\n")[1:-1])
                    
                data = json.loads(content)
                url = data.get("url", "").strip()
                
                if url and "youtube.com" in url if search_type == "youtube" else True:
                    # 4. DB 추천함에 적재
                    add_recommended_source(
                        url=url,
                        source_type=data.get("source_type", "news"),
                        label=data.get("label", entity),
                        reason=data.get("reason", "웹 자율 탐색 결과")
                    )
                    new_recommendations_count += 1
                    logger.info(f"💡 신규 소스 발굴: [{data.get('label')}] {url}")
                    
            except Exception as e:
                logger.warning(f"탐색/검증 실패 ({entity}): {e}")

    elapsed = (datetime.now() - start_time).total_seconds()
    logger.info(f"✅ [AI 자율 탐색] 완료 ({elapsed:.1f}초) - 신규 추천 {new_recommendations_count}건 추가됨")

if __name__ == "__main__":
    discover_sources()
