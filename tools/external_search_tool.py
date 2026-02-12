"""
External Search Tool (Web Search)

회계/세무 기준 등 외부 지식 검색용. Tavily Search API 우선, 미설정 시 DuckDuckGo 폴백.
검색 결과가 LLM 컨텍스트에 포함될 때 원문 URL이 유지되도록 구조화된 형식으로 반환합니다.
"""

import json
import logging
from typing import Any

from langchain_core.tools import tool
from pydantic import Field

logger = logging.getLogger(__name__)

# Optional: Tavily API key from env (TAVILY_API_KEY)
_tavily_tool = None
_duckduckgo_available = False


def _get_tavily_tool():
    """TavilySearchResults 도구 (TAVILY_API_KEY 설정 시)."""
    global _tavily_tool
    if _tavily_tool is not None:
        return _tavily_tool
    try:
        from langchain_community.tools.tavily_search import TavilySearchResults
        import os
        api_key = os.environ.get("TAVILY_API_KEY", "")
        if api_key:
            _tavily_tool = TavilySearchResults(
                max_results=5,
                api_key=api_key,
                include_answer=True,
                include_raw_content=False,
            )
        else:
            _tavily_tool = False
    except ImportError:
        logger.debug("Tavily not available (pip install langchain-community tavily-python)")
        _tavily_tool = False
    return _tavily_tool


def _check_duckduckgo():
    global _duckduckgo_available
    if _duckduckgo_available:
        return True
    try:
        from langchain_community.tools.duckduckgo_search import DuckDuckGoSearchRun
        _duckduckgo_available = True
        return True
    except ImportError:
        return False


def _format_search_result_with_urls(results: list[dict[str, Any]]) -> str:
    """
    검색 결과를 원문 URL이 유지된 문자열로 포맷.
    LLM이 인용 시 [설명](URL) 마크다운 링크로 사용할 수 있도록 함.
    """
    parts: list[str] = []
    for i, r in enumerate(results, 1):
        title = r.get("title") or r.get("name") or f"결과 {i}"
        url = r.get("url") or r.get("link") or ""
        content = r.get("content") or r.get("snippet") or r.get("body") or ""
        if url:
            parts.append(f"[{title}]({url})\n{content[:500]}")
        else:
            parts.append(f"{title}\n{content[:500]}")
    return "\n\n---\n\n".join(parts) if parts else "검색 결과가 없습니다."


def _results_to_citations(results: list[dict[str, Any]]) -> list[dict[str, str]]:
    """검색 결과에서 citations 리스트 추출 (답변 하단 노출용)."""
    citations: list[dict[str, str]] = []
    for r in results:
        title = (r.get("title") or r.get("name") or "").strip() or "외부 참조"
        url = (r.get("url") or r.get("link") or "").strip()
        if url:
            citations.append({"title": title, "url": url})
    return citations


@tool
async def web_search(query: str = Field(..., description="검색 쿼리 (예: 국세청 법인카드 세무처리, 회계기준 경비 인정)")) -> str:
    """
    외부 지능형 웹 검색을 실행합니다.
    회계/세무 기준, 국세청 가이드라인, 업종별 지출 관행 등을 검색할 때 사용합니다.
    검색 결과에는 반드시 원문 URL이 포함되며, 답변 작성 시 [설명](URL) 마크다운 형식으로 인용하세요.
    (run당 호출 횟수는 백엔드 가드레일과 동기화된 web_search_max_calls_per_run으로 제한됩니다.)
    """
    try:
        from core.context import get_guardrails
        from core.config import get_settings
        guardrails = get_guardrails()
        if guardrails is not None:
            guardrails["web_search_calls"] = guardrails.get("web_search_calls", 0) + 1
            max_calls = guardrails.get("web_search_max_calls") or get_settings().web_search_max_calls_per_run
            if max_calls > 0 and guardrails["web_search_calls"] > max_calls:
                return json.dumps(
                    {"error": "web_search 호출 한도 초과 (가드레일). 백엔드 설정과 동기화된 상한을 확인하세요.", "query": query},
                    ensure_ascii=False,
                )
    except Exception:
        pass
    # 1) Tavily
    tavily = _get_tavily_tool()
    if tavily:
        try:
            raw = await tavily.ainvoke({"query": query})
            if isinstance(raw, list):
                results = raw
            elif isinstance(raw, dict):
                results = raw.get("results", [])
            else:
                results = []
            if results:
                return _format_search_result_with_urls(results)
        except Exception as e:
            logger.warning(f"Tavily search failed: {e}")

    # 2) DuckDuckGo fallback
    if _check_duckduckgo():
        try:
            from langchain_community.tools.duckduckgo_search import DuckDuckGoSearchRun
            ddg = DuckDuckGoSearchRun()
            out = await ddg.ainvoke(query)
            if out and isinstance(out, str) and out.strip():
                return out.strip()
        except Exception as e:
            logger.warning(f"DuckDuckGo search failed: {e}")

    return json.dumps({"error": "외부 검색을 사용할 수 없습니다. TAVILY_API_KEY 설정 또는 langchain-community 설치를 확인하세요.", "query": query}, ensure_ascii=False)


async def _run_web_search_with_citations(query: str) -> tuple[str, list[dict[str, str]]]:
    """
    가드레일 적용 후 Tavily/DuckDuckGo 실행, 텍스트와 citations 반환.
    Returns:
        (text_for_llm, citations: [{"title", "url"}])
    """
    # 가드레일 체크 (web_search 도구와 동일)
    try:
        from core.context import get_guardrails
        from core.config import get_settings
        guardrails = get_guardrails()
        if guardrails is not None:
            guardrails["web_search_calls"] = guardrails.get("web_search_calls", 0) + 1
            max_calls = guardrails.get("web_search_max_calls") or get_settings().web_search_max_calls_per_run
            if max_calls > 0 and guardrails["web_search_calls"] > max_calls:
                return (
                    json.dumps({"error": "web_search 호출 한도 초과 (가드레일).", "query": query}, ensure_ascii=False),
                    [],
                )
    except Exception:
        pass

    citations: list[dict[str, str]] = []
    tavily = _get_tavily_tool()
    if tavily:
        try:
            raw = await tavily.ainvoke({"query": query})
            if isinstance(raw, list):
                results = raw
            elif isinstance(raw, dict):
                results = raw.get("results", [])
            else:
                results = []
            if results:
                citations = _results_to_citations(results)
                return _format_search_result_with_urls(results), citations
        except Exception as e:
            logger.warning(f"Tavily search failed: {e}")

    if _check_duckduckgo():
        try:
            from langchain_community.tools.duckduckgo_search import DuckDuckGoSearchRun
            ddg = DuckDuckGoSearchRun()
            out = await ddg.ainvoke(query)
            if out and isinstance(out, str) and out.strip():
                return out.strip(), citations
        except Exception as e:
            logger.warning(f"DuckDuckGo search failed: {e}")

    return (
        json.dumps({"error": "외부 검색을 사용할 수 없습니다.", "query": query}, ensure_ascii=False),
        [],
    )


async def run_web_search_for_pipeline(query: str) -> dict[str, Any]:
    """
    파이프라인(감사 분석)에서 조건부 외부 검색 시 사용.
    가드레일(max_calls) 적용 후 실행하며, 검색 결과 URL을 citations 리스트로 반환하여 답변 하단 노출용으로 전달.
    Returns:
        {"text": str, "citations": [{"title": str, "url": str}, ...]}
    """
    text, citations = await _run_web_search_with_citations(query)
    return {"text": text, "citations": citations}
