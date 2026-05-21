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
from db.vector_store import get_lms_client, add_recommended_source, get_active_model_name, get_domain

logger = logging.getLogger(__name__)

def generate_dynamic_queries(domain_info: dict) -> list[dict]:
    """
    LLM을 호출하여 현재 도메인의 이름과 키워드를 바탕으로
    인터넷에서 양질의 RSS 및 유튜브 채널을 발굴하기 위한 다변화 쿼리 6종을 생성합니다.
    """
    dom_name = domain_info.get("name", "이 기술")
    keywords = ", ".join(domain_info.get("keywords", []))
    
    prompt = f"""
당신은 최고의 데이터 엔지니어이자 웹 탐색 전문가입니다.
우리는 '{dom_name}'(관심 키워드: {keywords}) 분야의 뉴스 및 영상을 수집하기 위해 웹 검색(DuckDuckGo)을 수행하려고 합니다.
이 도메인을 전방위적으로 모니터링하기 위해 가장 신뢰도 높은 '전문 매체', '뉴스레터 RSS 피드', '공식 블로그', '유튜브 크리에이터 설명 채널'을 발굴할 수 있는 최적의 영어 및 한국어 검색 쿼리 6종을 생성하세요.

쿼리 유형 정의:
1. global_news_expert: 글로벌 전문 테크 미디어/블로그 탐색용 (예: "domain_name tech news rss OR blog")
2. global_newsletter: 글로벌 전문 뉴스레터/동향 RSS 탐색용 (예: "domain_name newsletter rss feed")
3. local_news: 국내 전문 미디어 및 커뮤니티 탐색용 (예: "domain_name IT 뉴스 블로그 RSS")
4. global_youtube_official: 글로벌 유튜브 공식/기관 채널 탐색용 (예: "domain_name official youtube channel")
5. global_youtube_creator: 글로벌 전문 유튜브 크리에이터/해설 채널 탐색용 (예: "domain_name tech explanation channel youtube")
6. local_youtube: 국내 전문 유튜브 크리에이터 채널 탐색용 (예: "domain_name 전문 유튜브 채널")

반드시 아래 JSON 포맷의 배열로만 반환하고, 다른 텍스트는 절대 포함하지 마세요.

[
  {{
    "query": "검색 쿼리 문자열",
    "search_type": "news 또는 youtube",
    "reason": "해당 쿼리를 설계한 이유"
  }},
  ...
]
"""
    try:
        client = get_lms_client()
        resp = client.chat.completions.create(
            model=get_active_model_name(),
            messages=[
                {"role": "system", "content": "당신은 AI 데이터 엔지니어입니다. JSON 배열로만 정밀하게 응답하세요."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2
        )
        content = resp.choices[0].message.content.strip()
        if content.startswith("```"):
            content = "\n".join(content.split("\n")[1:-1])
        
        import json
        queries = json.loads(content)
        return queries
    except Exception as e:
        logger.warning(f"동적 쿼리 생성 실패 (기본 폴백 사용): {e}")
        # 폴백 기본 쿼리 세트
        return [
            {"query": f"{dom_name} tech news rss OR blog", "search_type": "news", "reason": "글로벌 테크 미디어"},
            {"query": f"{dom_name} newsletter rss feed", "search_type": "news", "reason": "글로벌 뉴스레터"},
            {"query": f"{dom_name} IT 뉴스 블로그 RSS", "search_type": "news", "reason": "국내 전문 미디어"},
            {"query": f"{dom_name} official youtube channel", "search_type": "youtube", "reason": "글로벌 공식 유튜브"},
            {"query": f"{dom_name} tech explanation channel youtube", "search_type": "youtube", "reason": "글로벌 해설 유튜브"},
            {"query": f"{dom_name} 전문 유튜브 채널", "search_type": "youtube", "reason": "국내 해설 유튜브"}
        ]


def discover_sources(domain_key: str = "home_robot"):
    """
    지식 그래프 및 도메인 정보를 해석하고, 동적 검색 쿼리를 생성하여
    웹을 다각도로 탐색하고 양질의 소스를 추천 DB에 적재합니다.
    """
    logger.info(f"🔍 [AI 자율 탐색] 신규 데이터 소스 발굴 시작... (도메인: {domain_key})")
    start_time = datetime.now()

    # 1. 도메인 정보 획득
    dom_info = get_domain(domain_key)
    if not dom_info:
        logger.warning(f"도메인 정보를 찾을 수 없습니다: {domain_key}")
        return

    # 2. 동적 검색 쿼리 6종 생성
    dynamic_queries = generate_dynamic_queries(dom_info)
    logger.info(f"동적 생성된 탐색 쿼리 세트 ({len(dynamic_queries)}건):")
    for idx, q in enumerate(dynamic_queries):
        logger.info(f"  [{idx+1}] {q['query']} ({q['search_type']}) - 사유: {q['reason']}")

    new_recommendations_count = 0
    client = get_lms_client()

    # 3. 각 동적 쿼리에 대해 웹 검색 및 검증 수행
    for q_item in dynamic_queries:
        query = q_item["query"]
        search_type = q_item["search_type"]
        
        try:
            import time
            results = []
            # RateLimit 방지 지연
            time.sleep(2)
            
            try:
                with DDGS() as ddgs:
                    for r in ddgs.text(query, backend="html", max_results=3):
                        results.append(r)
            except Exception:
                time.sleep(2)
                try:
                    with DDGS() as ddgs2:
                        for r in ddgs2.text(query, backend="lite", max_results=3):
                            results.append(r)
                except Exception as e2:
                    logger.warning(f"Lite 백엔드 재시도 실패: {e2}")
            
            if not results:
                continue
            
            # 4. Gemma에게 검증 및 추출 요청
            prompt = f"""
다음은 쿼리 '{query}'로 검색한 웹 결과입니다.
이 중 '{dom_info['name']}' 도메인의 양질의 모니터링을 위해 수집할 가치가 있는 '전문 블로그/RSS' 또는 '유튜브 채널'의 URL이 있다면 하나만 추출하세요.
단순 검색 포털이나 단순 위키백과 등 수집 가치가 없는 정보라면 빈 문자열을 반환하세요.

검색 결과:
{json.dumps(results, ensure_ascii=False, indent=2)}

출력 형식(반드시 아래 JSON만 출력, 다른 말 금지):
{{
  "url": "찾은 URL (없으면 빈 문자열)",
  "source_type": "{'video' if search_type == 'youtube' else 'news'}",
  "label": "채널 또는 블로그의 UI 표시 이름 (예: TechCrunch AI)",
  "reason": "추천하는 구체적인 이유 (1줄)"
}}
"""
            resp = client.chat.completions.create(
                model=get_active_model_name(),
                messages=[
                    {"role": "system", "content": "당신은 AI 데이터 엔지니어입니다. 반드시 출력 형식의 JSON만 정확히 출력하십시오."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1
            )
            
            content = resp.choices[0].message.content.strip()
            if content.startswith("```"):
                content = "\n".join(content.split("\n")[1:-1])
                
            data = json.loads(content)
            url = data.get("url", "").strip()
            
            if url and ("youtube.com" in url if search_type == "youtube" else True):
                # 5. DB 추천함에 적재
                add_recommended_source(
                    url=url,
                    source_type=data.get("source_type", "news"),
                    label=data.get("label", dom_info['name']),
                    reason=data.get("reason", "웹 지능형 자율 탐색 결과"),
                    domain_key=domain_key
                )
                new_recommendations_count += 1
                logger.info(f"💡 신규 소스 발굴 성공: [{data.get('label')}] {url}")
                
        except Exception as e:
            logger.warning(f"탐색/검증 실패 (쿼리: {query}): {e}")

    elapsed = (datetime.now() - start_time).total_seconds()
    logger.info(f"✅ [AI 자율 탐색] 완료 ({elapsed:.1f}초) - 신규 추천 {new_recommendations_count}건 추가됨")

if __name__ == "__main__":
    discover_sources()
