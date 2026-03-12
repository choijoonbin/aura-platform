"""
RAG Query Rewriter — 검색 정합성 강화 (방향 ①)

retrieve_rag_pgvector 호출 전에 쿼리를 분석하여
SAP 코드값·줄임말·불완전 질의를 의미어로 확장합니다.

동작 원칙:
  1. 쿼리가 이미 충분히 명확하면 LLM 호출 없이 그대로 통과 (비용 0)
  2. 재작성이 필요한 쿼리(코드값·줄임말·짧은 쿼리)만 LLM 재작성
  3. 재작성 결과로 검색, 0건이면 원본 쿼리로 재시도 (안전망)
  4. 캐시: 동일 쿼리는 LRU 캐시로 LLM 재호출 방지

환경변수:
  RAG_QUERY_REWRITE_ENABLED=true/false  (기본 true)
  RAG_QUERY_REWRITE_MIN_LEN=5           (이 길이 미만은 항상 재작성 시도)
"""

from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# ── 재작성 필요 여부를 판단하는 휴리스틱 패턴 ─────────────────────────────
# 이 패턴이 하나라도 감지되면 LLM 재작성 시도
_REWRITE_TRIGGERS: list[re.Pattern[str]] = [
    re.compile(r"\b[A-Z]{2,}\d{4,}\b"),       # SAP 계정코드: PA0030, SK0100
    re.compile(r"\b\d{4,}\b"),                 # 4자리 이상 숫자: 6311, 4110
    re.compile(r"\b[A-Z]{3,}\b"),              # 대문자 약어: SAP, ERP, GL
    re.compile(r"법카|출장정산|전표처리"),      # 명확한 줄임말/복합어 (일반 단어 제외)
    re.compile(r"[?？]\s*$"),                  # 물음표로 끝나는 짧은 질문
]

# 이 길이 이하면 무조건 재작성 시도
_SHORT_QUERY_THRESHOLD = 8


def _needs_rewrite(query: str) -> bool:
    """쿼리가 재작성이 필요한지 빠르게 판단 (LLM 호출 없음)."""
    q = (query or "").strip()
    if not q:
        return False
    if len(q) <= _SHORT_QUERY_THRESHOLD:
        return True
    for pattern in _REWRITE_TRIGGERS:
        if pattern.search(q):
            return True
    return False


@lru_cache(maxsize=256)
def _load_prompts() -> dict[str, str]:
    """rag_query_rewriter.yaml 프롬프트 로드 (싱글톤 캐시)."""
    from pathlib import Path
    prompt_path = Path(__file__).parent.parent / "llm" / "prompts" / "rag_query_rewriter.yaml"
    try:
        with open(prompt_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data.get("prompts", {})
    except Exception as e:
        logger.warning("rag_query_rewriter: 프롬프트 로드 실패 (%s)", e)
        return {}


@lru_cache(maxsize=512)
def _rewrite_cached(query: str) -> str:
    """
    LLM 재작성 결과를 LRU 캐시로 저장.
    동일 쿼리는 LLM 재호출 없이 캐시에서 반환.
    """
    prompts = _load_prompts()
    system_prompt = prompts.get("system", "")
    user_template = prompts.get("user_template", "원본 질의: {query}")

    if not system_prompt:
        logger.debug("rag_query_rewriter: 프롬프트 없음, 원본 반환")
        return query

    try:
        from core.llm.client import get_llm_client
        llm = get_llm_client()

        user_msg = user_template.replace("{query}", query)
        from langchain_core.messages import HumanMessage, SystemMessage
        response = llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_msg),
        ])
        raw = response.content if hasattr(response, "content") else str(response)

        # JSON 파싱
        raw_stripped = raw.strip()
        if raw_stripped.startswith("```"):
            raw_stripped = re.sub(r"```(?:json)?", "", raw_stripped).strip("`").strip()
        result: dict[str, Any] = json.loads(raw_stripped)

        rewritten = (result.get("rewritten") or "").strip()
        changed = bool(result.get("changed", False))
        reason = result.get("reason", "")

        if not rewritten or not changed:
            logger.debug(
                "rag_query_rewriter: 재작성 불필요 query='%s' reason='%s'",
                query[:80], reason,
            )
            return query

        logger.info(
            "rag_query_rewriter: 재작성 완료 original='%s' rewritten='%s' reason='%s'",
            query[:80], rewritten[:80], reason,
        )
        return rewritten

    except json.JSONDecodeError as e:
        logger.warning("rag_query_rewriter: JSON 파싱 실패 (%s) raw='%s'", e, raw[:200] if "raw" in dir() else "")
        return query
    except Exception as e:
        logger.warning("rag_query_rewriter: LLM 호출 실패 (%s), 원본 쿼리 사용", e)
        return query


def rewrite_query(query: str) -> tuple[str, bool]:
    """
    쿼리를 분석하여 필요 시 의미어로 재작성.

    Returns:
        (rewritten_query, was_rewritten)
        - was_rewritten=False: 원본 반환 (LLM 호출 없었음)
        - was_rewritten=True: 재작성된 쿼리 반환
    """
    from core.config import get_settings
    settings = get_settings()

    if not bool(getattr(settings, "rag_query_rewrite_enabled", True)):
        return query, False

    q = (query or "").strip()
    if not q:
        return query, False

    if not _needs_rewrite(q):
        logger.debug("rag_query_rewriter: 재작성 불필요 (명확한 쿼리) query='%s'", q[:80])
        return query, False

    rewritten = _rewrite_cached(q)
    was_changed = rewritten != q
    return rewritten, was_changed
