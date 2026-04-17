"""
engine/gemma_worker.py
-----------------------
LM Studio(OpenAI 호환 API)를 통해 Gemma 4 26B를 호출하는 추론 엔진.
Pydantic을 활용하여 JSON Schema 기반 구조화 출력을 강제합니다.
"""
import json
import logging
import os
from pathlib import Path
from typing import Literal, Optional

from dotenv import load_dotenv
from jinja2 import Environment, FileSystemLoader
import httpx
from openai import OpenAI
from pydantic import BaseModel, Field

from db.vector_store import get_lms_client
load_dotenv()
logger = logging.getLogger(__name__)

# ---- 설정 --------------------------------------------------
LMS_BASE_URL = os.getenv("LMS_API_BASE", "http://localhost:1234/v1")
LMS_MODEL = os.getenv("LMS_MODEL_NAME", "gemma-4-26b")
PROMPT_DIR = Path(__file__).parent.parent / "prompts"

# _get_client 대신 db.vector_store.get_lms_client를 호출합니다.


# ---- Pydantic 출력 스키마 ----------------------------------
class Entity(BaseModel):
    name: str = Field(..., description="엔티티 이름")
    type: Literal["company", "technology", "institution", "product"]


class Relation(BaseModel):
    subject: str = Field(..., description="관계의 주체")
    predicate: str = Field(..., description="관계 유형 (한국어 동사)")
    object: str = Field(..., description="관계의 대상")


class ArticleAnalysis(BaseModel):
    translated_title: str = Field(..., description="기사/영상 원본 제목의 자연스러운 한국어 번역")
    summary: str = Field(..., description="3줄 이내 핵심 요약 (한국어)")
    key_points: list[str] = Field(default_factory=list, description="기사의 핵심 요점 1~2가지 (한글 불릿포인트, 3개 이상 작성 금지)")
    tech_categories: list[str] = Field(default_factory=list)
    companies: list[str] = Field(default_factory=list)
    institutions: list[str] = Field(default_factory=list)
    products: list[str] = Field(default_factory=list)
    sentiment: Literal["positive", "neutral", "negative"] = "neutral"
    importance_score: float = Field(default=5.0, ge=0.0, le=10.0)
    entities: list[Entity] = Field(default_factory=list)
    relations: list[Relation] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


# ---- 프롬프트 로더 -----------------------------------------
def _render_prompt(template_name: str, **kwargs) -> str:
    env = Environment(loader=FileSystemLoader(str(PROMPT_DIR)))
    template = env.get_template(template_name)
    return template.render(**kwargs)


def _load_system_prompt() -> str:
    return (PROMPT_DIR / "system_prompt.txt").read_text(encoding="utf-8")


# ---- 핵심 추론 함수 ----------------------------------------
def analyze_article(
    title: str,
    content: str,
    source: str = "",
    max_content_chars: int = 6000,
) -> Optional[ArticleAnalysis]:
    """
    기사 텍스트를 Gemma 4에 전달하여 구조화된 분석 결과를 반환합니다.

    Args:
        title: 기사 제목
        content: 기사 본문 (자동으로 max_content_chars로 잘림)
        source: 수집 출처
        max_content_chars: 컨텍스트 길이 제한

    Returns:
        ArticleAnalysis 객체, 실패 시 None
    """
    truncated_content = content[:max_content_chars]

    user_prompt = _render_prompt(
        "article_analysis.j2",
        title=title,
        source=source,
        content=truncated_content,
    )
    system_prompt = _load_system_prompt()

    try:
        client = get_lms_client()
        
        # Pydantic 모델에서 JSON 스키마 추출
        json_schema = ArticleAnalysis.model_json_schema()
        
        response = client.chat.completions.create(
            model=LMS_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            max_tokens=2048,
            # 'json_object' 대신 'json_schema' 규격 사용
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "article_analysis",
                    "strict": False,
                    "schema": json_schema
                }
            },
        )

        raw_json = response.choices[0].message.content
        data = json.loads(raw_json)

        # Pydantic 검증
        result = ArticleAnalysis.model_validate(data)
        logger.info(f"분석 완료 | 중요도: {result.importance_score} | 태그: {result.tags[:3]}")
        return result

    except json.JSONDecodeError as e:
        logger.error(f"JSON 파싱 오류: {e}")
    except Exception as e:
        logger.error(f"LLM 호출 오류: {e}")

    return None


def batch_analyze(articles: list[dict]) -> list[Optional[ArticleAnalysis]]:
    """여러 기사를 순차적으로 분석합니다."""
    results = []
    for i, article in enumerate(articles, 1):
        logger.info(f"분석 중 [{i}/{len(articles)}]: {article.get('title', '')[:50]}")
        result = analyze_article(
            title=article.get("title", ""),
            content=article.get("content", ""),
            source=article.get("source", ""),
        )
        results.append(result)
    return results
