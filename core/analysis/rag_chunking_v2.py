"""
RAG Agentic Chunking v2 — 완전 구현 (Phase 1 P0 + Phase 2 P1 + Phase 3 P2)

에이전트형 청킹 4단계 워크플로우:

  Step 1  Structural Anchoring   — LLM이 문서를 먼저 읽어 구조/성격/전략 결정 (Phase 2 P1)
                                    + LLM이 이 문서 전용 커스텀 앵커 패턴 생성
  Step 2  Hybrid Chunking        — 프로파일 결과에 따라 계층형/번호형/의미형 전략 선택
                                    + Layout-Aware 전처리 (표/리스트 구조 보존)
                                    + Semantic Hybrid: 계층형 내 임베딩 기반 의미론적 경계 탐지
  Step 3  Metadata Enrichment    — doc_summary를 텍스트 본문에 직접 주입 + 약한 메타데이터 보강
  Step 4  Self-Correction Loop   — LLM 의미 단절 탐지 → 병합(merge) 실제 적용
                                    + 분할(split) 위치 탐색 후 실제 실행
  Feedback Quality Feedback Loop — 최종 청크 품질 평가 → 저품질 청크 자동 재교정 (Phase 3 P2)

기존 rag.py는 수정하지 않으며, process_and_vectorize_v2()가 동일 입·출력 규격을 유지합니다.
환경변수 RAG_CHUNKING_VERSION=v2 로 전환 시 사용됩니다.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import yaml

from core.config import get_settings
from core.observability import incr
from core.synapse_schema import DOC_TYPE_REGULATION, is_hierarchical

logger = logging.getLogger(__name__)

from core.analysis.rag import (
    _load_text_from_file,
    _extract_document_standard_meta,
    _extract_page_from_chunk,
    _hierarchical_chunk_text,
    _expand_hierarchical_with_subchunks,
    _run_chunk_quality_gate,
    _get_embedding_client,
    EMBEDDING_DIM,
    FINANCE_REGULATION_DOC_TYPE,
)

_PROMPTS_PATH = Path(__file__).resolve().parent.parent / "llm" / "prompts" / "rag_chunking_v2.yaml"
_chunking_prompts_cache: dict[str, str] = {}


# =============================================================================
# 유틸리티
# =============================================================================

def _load_chunking_prompts() -> dict[str, str]:
    """rag_chunking_v2.yaml 로드. 모듈 내 캐싱."""
    global _chunking_prompts_cache
    if _chunking_prompts_cache:
        return _chunking_prompts_cache
    if not _PROMPTS_PATH.exists():
        logger.warning("rag_chunking_v2.yaml not found at %s", _PROMPTS_PATH)
        return {}
    try:
        with open(_PROMPTS_PATH, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        prompts = data.get("prompts", {}) or {}
        _chunking_prompts_cache = {k: str(v or "") for k, v in prompts.items()}
        return _chunking_prompts_cache
    except Exception as e:
        logger.warning("rag_chunking_v2.yaml 로드 실패: %s", e)
        return {}


def _extract_json_from_llm(text: str) -> str:
    """LLM 응답에서 JSON 부분만 추출 (마크다운 코드블록 제거)."""
    if not text:
        return ""
    text = text.strip()
    if "```" in text:
        for part in text.split("```"):
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("{") or part.startswith("["):
                return part
    return text


def _llm_call(prompt: str, label: str) -> str:
    """LLM 단일 호출. 실패 시 빈 문자열 반환."""
    try:
        from core.llm import get_llm_client
        llm = get_llm_client()
        result = llm.invoke(prompt)
        return (result or "").strip()
    except Exception as e:
        logger.warning("rag_chunking_v2 LLM 호출 실패 [%s]: %s", label, e)
        return ""


def _extract_context_header(content: str) -> tuple[str, str]:
    """청크 본문에서 컨텍스트 헤더([path]\n...)와 body를 분리."""
    if content.startswith("[") and "]" in content:
        bracket_end = content.index("]") + 1
        header = content[:bracket_end]
        body = content[bracket_end:].lstrip()
        return header, body
    return "", content


# =============================================================================
# Step 1: Structural Anchoring — 문서 프로파일링 + 커스텀 앵커 (Phase 2 P1)
# =============================================================================

def _llm_document_profile(
    text_content: str,
    doc_title: str,
    doc_type: str,
) -> dict[str, Any]:
    """
    Phase 2 P1 — Structural Anchoring.
    LLM이 청킹 전에 문서를 먼저 읽고 구조/성격을 분석하여 최적 청킹 전략과
    이 문서 전용 커스텀 앵커 패턴을 결정한다.
    """
    default_profile: dict[str, Any] = {
        "structure_type": "standard_korean_regulation",
        "doc_character": "regulation",
        "chunking_strategy": "hierarchical",
        "doc_summary": "",
        "anchor_examples": [],
        "custom_pattern_hint": None,
        "profiling_ok": False,
    }
    if is_hierarchical(doc_type) or doc_type.upper() == DOC_TYPE_REGULATION:
        default_profile["chunking_strategy"] = "hierarchical"

    preview_chars = 2000
    doc_preview = text_content[:preview_chars]

    prompts_map = _load_chunking_prompts()
    system = prompts_map.get("doc_profiling_system", "")
    user_tpl = prompts_map.get("doc_profiling_user_template", "").strip()
    if not user_tpl:
        logger.warning("rag_chunking_v2 profiling: YAML 프롬프트 없음, 기본값 사용")
        return default_profile

    user_msg = user_tpl.format(
        doc_title=doc_title,
        preview_chars=preview_chars,
        doc_preview=doc_preview,
    )
    full_prompt = f"{system}\n\n---\n\n{user_msg}" if system else user_msg

    logger.info(
        "rag_chunking_v2 profiling: start doc_title=%s doc_type=%s preview_chars=%s",
        doc_title, doc_type, preview_chars,
    )
    raw = _llm_call(full_prompt, label="doc_profiling")
    if not raw:
        logger.warning("rag_chunking_v2 profiling: LLM 응답 없음, 기본값 사용 doc_title=%s", doc_title)
        return default_profile

    try:
        parsed = json.loads(_extract_json_from_llm(raw))
        if not isinstance(parsed, dict):
            raise ValueError("JSON 객체가 아님")
        profile: dict[str, Any] = {**default_profile, **parsed, "profiling_ok": True}
        incr("rag_chunking_v2_profiling_ok_total")
        logger.info(
            "rag_chunking_v2 profiling: 완료 doc_title=%s structure=%s character=%s strategy=%s "
            "anchors=%s summary='%s'",
            doc_title,
            profile.get("structure_type"),
            profile.get("doc_character"),
            profile.get("chunking_strategy"),
            profile.get("anchor_examples"),
            (profile.get("doc_summary") or "")[:80],
        )
        return profile
    except Exception as e:
        logger.warning(
            "rag_chunking_v2 profiling: JSON 파싱 실패 doc_title=%s err=%s raw='%s'",
            doc_title, e, raw[:200],
        )
        incr("rag_chunking_v2_profiling_error_total")
        return default_profile


def _build_custom_anchor_regex(anchor_examples: list[str]) -> re.Pattern[str] | None:
    """
    LLM이 발견한 앵커 예시(anchor_examples)로부터 이 문서 전용 정규식을 생성.
    예: ["제1장", "1.1", "Chapter 1"] → 해당 패턴을 추가 경계로 활용.
    """
    if not anchor_examples:
        return None

    patterns: list[str] = []
    for ex in anchor_examples[:10]:
        ex = ex.strip()
        if not ex:
            continue
        # 번호 자리 → \d+ 로 일반화
        generalized = re.sub(r"\d+", r"\\d+", re.escape(ex))
        generalized = generalized.replace(r"\ ", r"\s+")
        patterns.append(generalized)

    if not patterns:
        return None

    combined = "|".join(f"(?:{p})" for p in patterns)
    try:
        compiled = re.compile(rf"(?m)^(?:{combined})", re.UNICODE)
        logger.debug("rag_chunking_v2 custom_anchor_regex: %s", compiled.pattern[:100])
        return compiled
    except re.error as e:
        logger.warning("rag_chunking_v2 커스텀 앵커 정규식 컴파일 실패: %s", e)
        return None


def _apply_custom_anchor_split(
    h_chunks: list[tuple[str, dict[str, Any]]],
    anchor_pattern: re.Pattern[str],
    doc_title: str,
) -> list[tuple[str, dict[str, Any]]]:
    """
    커스텀 앵커 패턴을 사용해 청크 내에 숨겨진 경계를 찾아 추가 분할.
    기존 계층형 청킹이 놓친 비표준 경계를 보완한다.
    """
    result: list[tuple[str, dict[str, Any]]] = []
    split_count = 0

    for content, meta in h_chunks:
        header, body = _extract_context_header(content)
        splits = anchor_pattern.split(body)
        delimiters = anchor_pattern.findall(body)

        if len(splits) <= 1:
            result.append((content, meta))
            continue

        # 첫 번째 분할 조각
        first_body = splits[0].strip()
        if first_body:
            result.append((header + first_body if header else first_body, meta))

        for delim, piece in zip(delimiters, splits[1:]):
            piece_stripped = piece.strip()
            sub_content = (header + delim + " " + piece_stripped) if header else (delim + " " + piece_stripped)
            sub_meta = {
                **meta,
                "regulation_article": delim.strip() or meta.get("regulation_article"),
                "location": (
                    f"{meta.get('location', doc_title)} > {delim.strip()}"
                    if meta.get("location")
                    else f"{doc_title} > {delim.strip()}"
                ),
            }
            result.append((sub_content, sub_meta))
            split_count += 1

    if split_count:
        logger.info(
            "rag_chunking_v2 custom_anchor_split: doc_title=%s 추가분할=%s before=%s after=%s",
            doc_title, split_count, len(h_chunks), len(result),
        )
    return result


# =============================================================================
# Step 2: Layout-Aware Preprocessing — 표/리스트 구조 보존
# =============================================================================

_TABLE_START = "[[TABLE_START]]"
_TABLE_END = "[[TABLE_END]]"
_LIST_START = "[[LIST_START]]"
_LIST_END = "[[LIST_END]]"

_TABLE_LINE_RE = re.compile(r"^\s*\|.+\|")
_TABLE_DIVIDER_RE = re.compile(r"^\s*\+[-+]+\+\s*$")
_LIST_ITEM_RE = re.compile(r"^[\①②③④⑤⑥⑦⑧⑨⑩\-\*•◦]\s")
_NUMBERED_ITEM_RE = re.compile(r"^\d+\.\s")


def _layout_aware_preprocess(text_content: str) -> str:
    """
    Phase 3 P2 — Layout-Aware Chunking 전처리.
    표(Table)와 리스트(List) 블록을 마커로 감싸 청킹 시 분리되지 않도록 보호.

    표 감지: | 구분자 2개 이상인 연속 행
    리스트 감지: ① ② ③ / - * • 로 시작하는 연속 3행 이상
    """
    lines = text_content.split("\n")
    result: list[str] = []
    i = 0

    while i < len(lines):
        line = lines[i]

        # ── 표(Table) 감지 ──────────────────────────────────────────
        if _TABLE_LINE_RE.match(line) or _TABLE_DIVIDER_RE.match(line.strip()):
            table_lines: list[str] = []
            while i < len(lines) and (
                _TABLE_LINE_RE.match(lines[i])
                or _TABLE_DIVIDER_RE.match(lines[i].strip())
                or (table_lines and lines[i].strip() == "")
            ):
                table_lines.append(lines[i])
                i += 1
            # 빈 줄로 끝나는 경우 제거
            while table_lines and not table_lines[-1].strip():
                table_lines.pop()
            if len(table_lines) >= 2:
                result.append(_TABLE_START)
                result.extend(table_lines)
                result.append(_TABLE_END)
                continue
            else:
                result.extend(table_lines)
            continue

        # ── 리스트(List) 감지 ────────────────────────────────────────
        if _LIST_ITEM_RE.match(line.strip()) or _NUMBERED_ITEM_RE.match(line.strip()):
            list_lines: list[str] = []
            while i < len(lines):
                ln = lines[i]
                ln_stripped = ln.strip()
                is_item = (
                    _LIST_ITEM_RE.match(ln_stripped)
                    or _NUMBERED_ITEM_RE.match(ln_stripped)
                )
                is_continuation = (
                    list_lines
                    and ln_stripped
                    and not re.match(r"^제\d+[장조항호절]", ln_stripped)
                    and not ln_stripped.startswith("[")
                    and not is_item
                )
                if not (is_item or is_continuation):
                    break
                list_lines.append(ln)
                i += 1
            if len(list_lines) >= 3:
                result.append(_LIST_START)
                result.extend(list_lines)
                result.append(_LIST_END)
                continue
            else:
                result.extend(list_lines)
            continue

        result.append(line)
        i += 1

    processed = "\n".join(result)
    table_count = processed.count(_TABLE_START)
    list_count = processed.count(_LIST_START)
    if table_count or list_count:
        logger.info(
            "rag_chunking_v2 layout_preprocess: 표=%s 리스트=%s 감지/보호",
            table_count, list_count,
        )
    return processed


def _preserve_layout_in_chunks(
    h_chunks: list[tuple[str, dict[str, Any]]],
) -> list[tuple[str, dict[str, Any]]]:
    """
    TABLE_START/END 또는 LIST_START/END 마커가 청크 경계에서 갈라진 경우
    인접 청크를 병합하여 표/리스트 블록 무결성을 복원.
    """
    if not h_chunks:
        return h_chunks

    result: list[tuple[str, dict[str, Any]]] = []
    merge_buffer: list[str] = []
    buffer_meta: dict[str, Any] = {}
    in_protected = False

    for content, meta in h_chunks:
        starts = content.count(_TABLE_START) + content.count(_LIST_START)
        ends = content.count(_TABLE_END) + content.count(_LIST_END)

        if not in_protected and starts == 0 and ends == 0:
            result.append((content, meta))
            continue

        if not in_protected:
            merge_buffer = [content]
            buffer_meta = meta
            in_protected = True
        else:
            merge_buffer.append(content)

        open_count = sum(c.count(_TABLE_START) + c.count(_LIST_START) for c in merge_buffer)
        close_count = sum(c.count(_TABLE_END) + c.count(_LIST_END) for c in merge_buffer)

        if close_count >= open_count:
            merged = "\n".join(merge_buffer)
            result.append((merged, buffer_meta))
            merge_buffer = []
            buffer_meta = {}
            in_protected = False

    if merge_buffer:
        result.append(("\n".join(merge_buffer), buffer_meta))

    return result


def _strip_layout_markers(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """최종 청크에서 레이아웃 마커 태그 제거."""
    cleaned: list[dict[str, Any]] = []
    for chunk in chunks:
        content = chunk.get("content") or ""
        for marker in (_TABLE_START, _TABLE_END, _LIST_START, _LIST_END):
            content = content.replace(marker + "\n", "").replace(marker, "")
        cleaned.append({**chunk, "content": content.strip()})
    return cleaned


# =============================================================================
# Step 2: Semantic Hybrid Sub-chunking — 계층형 내 의미론적 경계 탐지
# =============================================================================

def _semantic_hybrid_sub_chunk(
    h_chunks: list[tuple[str, dict[str, Any]]],
    emb: Any,
    chunk_size: int,
    doc_title: str,
) -> list[tuple[str, dict[str, Any]]]:
    """
    Phase 3 P2 — Semantic Boundary Detection within hierarchical chunks.

    계층형 청킹(regex)으로 만들어진 청크 중 chunk_size * 1.5를 초과하는 것에 한해
    임베딩 유사도 기반 SemanticChunker를 적용하여 의미 경계에서 추가 분할.
    → 진정한 Hybrid: 외부 경계는 규칙(Rule), 내부 경계는 의미론(Semantic).
    """
    OVER_SIZE_THRESHOLD = chunk_size * 1.5

    try:
        from langchain_experimental.text_splitter import SemanticChunker
        sem_splitter = SemanticChunker(
            embeddings=emb,
            breakpoint_threshold_type="percentile",
        )
    except ImportError:
        logger.warning("rag_chunking_v2 semantic_hybrid: langchain-experimental 미설치, 스킵")
        return h_chunks

    result: list[tuple[str, dict[str, Any]]] = []
    semantic_split_count = 0

    for content, meta in h_chunks:
        if len(content) <= OVER_SIZE_THRESHOLD:
            result.append((content, meta))
            continue

        header, body = _extract_context_header(content)
        if not body.strip():
            result.append((content, meta))
            continue

        try:
            sub_texts = sem_splitter.split_text(body)
        except Exception as e:
            logger.debug("rag_chunking_v2 semantic_hybrid: split 실패 err=%s", e)
            result.append((content, meta))
            continue

        if len(sub_texts) <= 1:
            result.append((content, meta))
            continue

        for si, sub_text in enumerate(sub_texts):
            sub_text = sub_text.strip()
            if not sub_text:
                continue
            sub_content = (header + "\n" + sub_text) if header else sub_text
            sub_meta = {**meta, "semantic_sub_index": si, "parent_chunk_semantic": True}
            result.append((sub_content, sub_meta))
            semantic_split_count += 1

    if semantic_split_count > 0:
        logger.info(
            "rag_chunking_v2 semantic_hybrid: doc_title=%s 의미론적_분할=%s before=%s after=%s",
            doc_title, semantic_split_count, len(h_chunks), len(result),
        )
    return result


# =============================================================================
# Step 2: Hybrid Chunking — 전략별 청킹
# =============================================================================

def _outline_chunk_text(
    text: str,
    doc_title: str,
    custom_pattern_hint: str | None,
    max_chunk_chars: int,
) -> list[tuple[str, dict[str, Any]]]:
    """번호 계층 구조(1. / 1.1 / 1.1.1) 문서용 청킹."""
    anchor_pattern: re.Pattern[str] | None = None
    if custom_pattern_hint:
        try:
            generalized = re.sub(r"\d+", r"\\d+", re.escape(custom_pattern_hint))
            anchor_pattern = re.compile(rf"(?m)^({generalized}\s+.{{1,80}})$")
        except re.error:
            anchor_pattern = None

    if anchor_pattern is None:
        anchor_pattern = re.compile(r"(?m)^(\d+(?:\.\d+)*\.?\s+.{1,80})$")

    lines = text.split("\n")
    chunks_out: list[tuple[str, dict[str, Any]]] = []
    current_section: str = ""
    current_buffer: list[str] = []

    for line in lines:
        m = anchor_pattern.match(line.strip())
        if m:
            if current_buffer:
                body = " ".join(current_buffer).strip()
                content = f"[{doc_title} > {current_section}] " + body
                if len(content) >= 30:
                    chunks_out.append((content, {
                        "location": f"{doc_title} > {current_section}",
                        "regulation_article": current_section,
                    }))
            current_section = m.group(1).strip()[:80]
            current_buffer = []
        else:
            stripped = line.strip()
            if stripped:
                current_buffer.append(stripped)
                if len(" ".join(current_buffer)) > max_chunk_chars:
                    body = " ".join(current_buffer).strip()
                    content = f"[{doc_title} > {current_section}] " + body
                    chunks_out.append((content, {
                        "location": f"{doc_title} > {current_section}",
                        "regulation_article": current_section,
                    }))
                    current_buffer = []

    if current_buffer:
        body = " ".join(current_buffer).strip()
        content = f"[{doc_title} > {current_section}] " + body
        if len(content) >= 30:
            chunks_out.append((content, {
                "location": f"{doc_title} > {current_section}",
                "regulation_article": current_section,
            }))

    logger.info(
        "rag_chunking_v2 outline_chunk: doc_title=%s chunks=%s pattern=%s",
        doc_title, len(chunks_out), (custom_pattern_hint or "default_numbered"),
    )
    return chunks_out


def _structural_chunking(
    text_content: str,
    doc_title: str,
    doc_type: str,
    profile: dict[str, Any],
    settings: Any,
    emb: Any,
    chunk_size: int,
    chunk_overlap: int,
) -> tuple[list[str], list[dict[str, Any]]]:
    """
    Step 2: Hybrid Chunking.
    프로파일 결과에 따라 3가지 전략 중 하나를 선택 + 커스텀 앵커 보완 + 의미론적 하이브리드.
    """
    strategy = profile.get("chunking_strategy", "hierarchical")
    anchor_examples = profile.get("anchor_examples") or []
    custom_anchor_re = _build_custom_anchor_regex(anchor_examples)

    if strategy == "hierarchical" or is_hierarchical(doc_type):
        logger.info(
            "rag_chunking_v2 structural_chunking: strategy=hierarchical doc_title=%s",
            doc_title,
        )
        h_chunks = _hierarchical_chunk_text(
            text_content, doc_title=doc_title, max_chunk_chars=chunk_size
        )
        if not h_chunks:
            return [], []

        # 커스텀 앵커로 추가 분할 (비표준 경계 보완)
        if custom_anchor_re:
            h_chunks = _apply_custom_anchor_split(h_chunks, custom_anchor_re, doc_title)

        # 표/리스트 블록 무결성 복원
        h_chunks = _preserve_layout_in_chunks(h_chunks)

        if bool(getattr(settings, "rag_hybrid_subchunk_enabled", True)):
            h_chunks = _expand_hierarchical_with_subchunks(
                h_chunks,
                doc_title=str(doc_title),
                sub_size=int(getattr(settings, "rag_hybrid_subchunk_size", 420)),
                sub_overlap=int(getattr(settings, "rag_hybrid_subchunk_overlap", 80)),
                min_chars=int(getattr(settings, "rag_hybrid_subchunk_min_chars", 140)),
            )

        # Semantic Hybrid: 계층형 대형 청크를 의미론적으로 추가 분할
        if bool(getattr(settings, "rag_chunking_v2_semantic_hybrid_enabled", True)):
            h_chunks = _semantic_hybrid_sub_chunk(h_chunks, emb, chunk_size, doc_title)

        return [c[0] for c in h_chunks], [c[1] for c in h_chunks]

    elif strategy == "outline":
        logger.info(
            "rag_chunking_v2 structural_chunking: strategy=outline doc_title=%s custom_pattern=%s",
            doc_title, profile.get("custom_pattern_hint"),
        )
        o_chunks = _outline_chunk_text(
            text_content,
            doc_title=doc_title,
            custom_pattern_hint=profile.get("custom_pattern_hint"),
            max_chunk_chars=chunk_size,
        )
        if not o_chunks:
            return [], []
        if custom_anchor_re:
            o_chunks = _apply_custom_anchor_split(o_chunks, custom_anchor_re, doc_title)
        return [c[0] for c in o_chunks], [c[1] for c in o_chunks]

    else:
        logger.info(
            "rag_chunking_v2 structural_chunking: strategy=semantic doc_title=%s",
            doc_title,
        )
        try:
            from langchain_experimental.text_splitter import SemanticChunker
            chunks_text = SemanticChunker(
                embeddings=emb,
                breakpoint_threshold_type="percentile",
            ).split_text(text_content)
            logger.info(
                "rag_chunking_v2 structural_chunking: semantic 완료 chunks=%s",
                len(chunks_text),
            )
            return chunks_text, []
        except Exception as e:
            logger.warning("SemanticChunker 실패, RecursiveCharacter 폴백: %s", e)
            try:
                from langchain_text_splitters import RecursiveCharacterTextSplitter
                chunks_text = RecursiveCharacterTextSplitter(
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                    length_function=len,
                ).split_text(text_content)
                return chunks_text, []
            except Exception as e2:
                logger.error("RecursiveCharacter 폴백 실패: %s", e2)
                return [], []


# =============================================================================
# Step 3: Metadata Enrichment + Context Injection
# =============================================================================

def _inject_context_into_body(
    prepared_chunks: list[dict[str, Any]],
    doc_title: str,
    doc_profile: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Phase 1 P0 — Contextual Retrieval (Small-to-Big).
    각 청크 텍스트 본문에 doc_summary를 직접 주입.
    계층형: [path] 프리픽스 뒤에 주입 / 비계층형: [doc_title] + 주입.
    """
    doc_summary = (doc_profile.get("doc_summary") or "").strip()
    if not doc_summary:
        return prepared_chunks

    result: list[dict[str, Any]] = []
    for chunk in prepared_chunks:
        content = chunk.get("content") or ""
        meta = chunk.get("metadata") or {}
        if content.startswith("[") and "]" in content:
            bracket_end = content.index("]") + 1
            prefix_part = content[:bracket_end]
            body_part = content[bracket_end:].lstrip()
            new_content = f"{prefix_part}\n문서 개요: {doc_summary}\n{body_part}"
        else:
            location = (meta.get("location") or doc_title).strip()
            new_content = f"[{location}]\n문서 개요: {doc_summary}\n{content}"
        result.append({**chunk, "content": new_content})

    logger.info(
        "rag_chunking_v2 context_inject: 완료 doc_title=%s injected=%s summary='%s'",
        doc_title, len(result), doc_summary[:60],
    )
    return result


def _llm_enrich_chunk_headers(
    prepared_chunks: list[dict[str, Any]],
    doc_title: str,
    doc_type: str,
) -> list[dict[str, Any]]:
    """Metadata Enrichment: 약한 location/regulation_article LLM 보강."""
    weak_indices: list[int] = []
    for i, row in enumerate(prepared_chunks):
        meta = row.get("metadata") or {}
        loc = (meta.get("location") or "").strip()
        art = (meta.get("regulation_article") or "").strip()
        if not loc or not art or "일반문서" in (loc + art):
            weak_indices.append(i)

    if not weak_indices:
        logger.info(
            "rag_chunking_v2 header_enrich: skip (모든 청크 location/article 충분) doc_title=%s total=%s",
            doc_title, len(prepared_chunks),
        )
        return prepared_chunks

    sample_indices = weak_indices[:15]
    logger.info(
        "rag_chunking_v2 header_enrich: start doc_title=%s weak=%s sample=%s",
        doc_title, len(weak_indices), len(sample_indices),
    )
    chunks_for_llm = [
        {
            "chunk_idx": i,
            "content_preview": (prepared_chunks[i].get("content") or "")[:500],
            "location": (prepared_chunks[i].get("metadata") or {}).get("location"),
            "regulation_article": (prepared_chunks[i].get("metadata") or {}).get("regulation_article"),
        }
        for i in sample_indices
    ]
    prompts_map = _load_chunking_prompts()
    system = prompts_map.get("header_enrichment_system", "")
    user_tpl = prompts_map.get("header_enrichment_user_template", "").strip()
    if not user_tpl:
        return prepared_chunks

    user_msg = user_tpl.format(
        doc_title=doc_title,
        chunks_json=json.dumps(chunks_for_llm, ensure_ascii=False, indent=2),
    )
    raw = _llm_call(
        f"{system}\n\n---\n\n{user_msg}" if system else user_msg,
        label="header_enrich",
    )
    if not raw:
        return prepared_chunks

    try:
        suggestions = json.loads(_extract_json_from_llm(raw))
        if not isinstance(suggestions, list):
            raise ValueError("JSON 배열이 아님")
        enriched_count = 0
        for s in suggestions:
            idx = s.get("chunk_idx")
            if idx is None or not isinstance(idx, int) or idx >= len(prepared_chunks):
                continue
            loc = s.get("location")
            art = s.get("regulation_article")
            if loc or art:
                meta = dict(prepared_chunks[idx].get("metadata") or {})
                if loc:
                    meta["location"] = str(loc).strip()
                if art:
                    meta["regulation_article"] = str(art).strip()
                prepared_chunks[idx] = {**prepared_chunks[idx], "metadata": meta}
                enriched_count += 1
        incr("rag_chunking_v2_llm_enrich_runs_total")
        logger.info(
            "rag_chunking_v2 header_enrich: 완료 doc_title=%s enriched=%s / suggested=%s",
            doc_title, enriched_count, len(suggestions),
        )
    except Exception as e:
        logger.warning("rag_chunking_v2 header_enrich 실패: %s", e)
        incr("rag_chunking_v2_llm_enrich_error_total")
    return prepared_chunks


# =============================================================================
# Step 4: Self-Correction Loop — 병합 + 분할 실제 실행
# =============================================================================

def _find_split_position(body: str, split_hint: str) -> int:
    """
    split_hint(LLM이 제안한 분할 위치 힌트)를 본문에서 찾아 위치 반환.
    못 찾으면 -1 반환.
    """
    if not split_hint or not body:
        return -1

    # 한국 조항 패턴 우선 탐색 (제N조, 제N항, 제N절 등)
    article_m = re.search(r"(제\d+[조항절호])", split_hint)
    if article_m:
        target = article_m.group(1)
        m = re.search(rf"(?<!\S){re.escape(target)}", body)
        if m and m.start() > 20:
            return m.start()

    # 번호 계층 패턴 (1.1.1 등)
    outline_m = re.search(r"(\d+(?:\.\d+)+\.?)\s", split_hint)
    if outline_m:
        target = outline_m.group(1)
        pos = body.find(target)
        if pos > 20:
            return pos

    # 텍스트 직접 탐색 (힌트 앞 20자)
    hint_prefix = split_hint[:25].strip()
    if len(hint_prefix) >= 5:
        pos = body.find(hint_prefix)
        if pos > 20:
            return pos

    return -1


def _apply_chunk_splits(
    chunks: list[dict[str, Any]],
    splits_flagged: list[dict[str, Any]],
    doc_title: str,
) -> tuple[list[dict[str, Any]], int]:
    """
    Self-Correction에서 flagged된 split 대상을 실제로 분할.
    split_hint로 텍스트 내 분할 위치를 탐색하여 두 청크로 분리.
    """
    if not splits_flagged:
        return chunks, 0

    result = list(chunks)
    splits_applied = 0

    # 높은 인덱스부터 처리하여 앞 인덱스 유지
    for split_info in sorted(splits_flagged, key=lambda x: x.get("global_index", 0), reverse=True):
        idx = split_info.get("global_index")
        split_hint = (split_info.get("split_hint") or "").strip()

        if idx is None or idx >= len(result) or not split_hint:
            continue

        chunk = result[idx]
        content = chunk.get("content") or ""
        meta = dict(chunk.get("metadata") or {})

        header, body = _extract_context_header(content)

        split_pos = _find_split_position(body, split_hint)
        if split_pos <= 0:
            logger.debug(
                "rag_chunking_v2 split: 위치 탐색 실패 idx=%s hint='%s'",
                idx, split_hint[:40],
            )
            continue

        part1 = body[:split_pos].rstrip()
        part2 = body[split_pos:].lstrip()

        if len(part1) < 30 or len(part2) < 30:
            logger.debug(
                "rag_chunking_v2 split: 분할 후 너무 짧음 idx=%s part1=%s part2=%s",
                idx, len(part1), len(part2),
            )
            continue

        content1 = (header + "\n" + part1) if header else part1
        content2 = (header + "\n" + part2) if header else part2

        result[idx] = {**chunk, "content": content1}
        result.insert(idx + 1, {
            "content": content2,
            "metadata": {**meta, "split_from_index": idx},
        })
        splits_applied += 1
        logger.debug(
            "rag_chunking_v2 split: 적용 idx=%s hint='%s' part1=%s part2=%s",
            idx, split_hint[:40], len(part1), len(part2),
        )

    if splits_applied:
        # 청크 인덱스 재부여
        for i, chunk in enumerate(result):
            meta = dict(chunk.get("metadata") or {})
            meta["chunk_index"] = i
            result[i] = {**chunk, "metadata": meta}
        logger.info(
            "rag_chunking_v2 split_apply: doc_title=%s 분할_적용=%s",
            doc_title, splits_applied,
        )

    return result, splits_applied


def _build_window_previews(window: list[dict[str, Any]], window_start: int) -> str:
    """자기 교정 LLM용 청크 창 미리보기."""
    lines: list[str] = []
    for local_i, chunk in enumerate(window):
        content = (chunk.get("content") or "")
        body_lines = content.split("\n")
        body = " ".join(
            l.strip() for l in body_lines
            if l.strip() and not l.startswith("[") and not l.startswith("문서 개요:")
        )
        meta = chunk.get("metadata") or {}
        article = meta.get("regulation_article") or ""
        char_count = len(content)
        lines.append(
            f"[{window_start + local_i}] article={article} chars={char_count}\n"
            f"  시작: {body[:80].strip()}\n"
            f"  끝:   {body[-80:].strip()}"
        )
    return "\n\n".join(lines)


def _get_correction_actions_for_window(
    window: list[dict[str, Any]],
    doc_title: str,
    window_start: int,
) -> list[dict[str, Any]]:
    """LLM에 창 단위 교정 요청."""
    prompts_map = _load_chunking_prompts()
    system = prompts_map.get("self_correction_system", "")
    user_tpl = prompts_map.get("self_correction_user_template", "").strip()
    if not user_tpl:
        return []

    user_msg = user_tpl.format(
        doc_title=doc_title,
        window_start=window_start,
        window_end=window_start + len(window) - 1,
        window_count=len(window),
        chunk_previews=_build_window_previews(window, window_start),
    )
    raw = _llm_call(
        f"{system}\n\n---\n\n{user_msg}" if system else user_msg,
        label="self_correction",
    )
    if not raw:
        return []
    try:
        parsed = json.loads(_extract_json_from_llm(raw))
        actions = parsed.get("actions") if isinstance(parsed, dict) else None
        return actions if isinstance(actions, list) else []
    except Exception as e:
        logger.debug("rag_chunking_v2 self_correction: JSON 파싱 실패 window=%s err=%s", window_start, e)
        return []


def _llm_self_correction_loop(
    prepared_chunks: list[dict[str, Any]],
    doc_title: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Phase 1 P0 — Self-Correction Loop (완전 구현).
    창(window) 단위로 LLM에 교정 요청 → 병합(merge) 및 분할(split) 실제 적용.
    """
    if len(prepared_chunks) < 2:
        return prepared_chunks, {"merges_applied": 0, "splits_applied": 0}

    WINDOW_SIZE = 10
    WINDOW_STEP = 8

    merge_candidates: dict[int, str] = {}
    splits_flagged: list[dict[str, Any]] = []

    logger.info(
        "rag_chunking_v2 self_correction: start doc_title=%s total_chunks=%s",
        doc_title, len(prepared_chunks),
    )

    for start in range(0, len(prepared_chunks), WINDOW_STEP):
        window = prepared_chunks[start: start + WINDOW_SIZE]
        if len(window) < 2:
            break

        actions = _get_correction_actions_for_window(window, doc_title, window_start=start)
        for action in actions:
            atype = action.get("type", "keep")
            if atype == "merge":
                local_indices = action.get("indices") or []
                if (
                    len(local_indices) == 2
                    and isinstance(local_indices[0], int)
                    and isinstance(local_indices[1], int)
                ):
                    lo, hi = sorted(local_indices)
                    if hi - lo == 1:
                        global_lo = start + lo
                        if global_lo not in merge_candidates:
                            merge_candidates[global_lo] = action.get("reason", "")
            elif atype == "split":
                local_idx = action.get("index")
                if local_idx is not None:
                    splits_flagged.append({
                        "global_index": start + int(local_idx),
                        "split_hint": action.get("split_hint", ""),
                        "reason": action.get("reason", ""),
                    })

    # 병합 적용 (역순)
    result = list(prepared_chunks)
    applied_merges: list[dict[str, Any]] = []

    for idx in sorted(merge_candidates.keys(), reverse=True):
        if idx + 1 >= len(result):
            continue
        c1 = result[idx]
        c2 = result[idx + 1]
        c1_content = (c1.get("content") or "").rstrip()

        # c2의 컨텍스트 헤더/요약 라인 제거 후 본문만 추출
        c2_lines = (c2.get("content") or "").split("\n")
        c2_body_lines = [
            ln for ln in c2_lines
            if not (ln.startswith("[") and "]" in ln) and not ln.startswith("문서 개요:")
        ]
        c2_body = "\n".join(c2_body_lines).strip()

        merged_content = c1_content + "\n" + c2_body
        result[idx] = {"content": merged_content, "metadata": dict(c1.get("metadata") or {})}
        result.pop(idx + 1)
        applied_merges.append({"merged_at_global": idx, "reason": merge_candidates[idx]})

    # 인덱스 재부여 후 분할 적용
    for i, chunk in enumerate(result):
        meta = dict(chunk.get("metadata") or {})
        meta["chunk_index"] = i
        result[i] = {**chunk, "metadata": meta}

    result, splits_applied_count = _apply_chunk_splits(result, splits_flagged, doc_title)

    correction_report: dict[str, Any] = {
        "merges_applied": len(applied_merges),
        "splits_applied": splits_applied_count,
        "splits_flagged": len(splits_flagged),
        "merge_details": applied_merges,
    }
    incr("rag_chunking_v2_llm_correction_runs_total")
    logger.info(
        "rag_chunking_v2 self_correction: 완료 doc_title=%s merges=%s splits_applied=%s "
        "splits_flagged=%s before=%s after=%s",
        doc_title,
        len(applied_merges),
        splits_applied_count,
        len(splits_flagged),
        len(prepared_chunks),
        len(result),
    )
    return result, correction_report


# =============================================================================
# Phase 3 P2: Quality Feedback Loop — 저품질 청크 자동 재교정
# =============================================================================

def _llm_quality_feedback_loop(
    prepared_chunks: list[dict[str, Any]],
    doc_title: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Phase 3 P2 — 자동 최적화 피드백 루프.

    최종 청크 샘플을 LLM이 RAG 검색 적합성 관점에서 평가.
    POOR 판정 청크는 인접 청크와 병합하여 품질을 개선.
    → '에이전트가 스스로 재청킹' 개념의 경량 구현.
    """
    if len(prepared_chunks) < 3:
        return prepared_chunks, {"overall_ok": True, "summary": "청크 수 부족, 스킵"}

    # 균등 샘플링 (최대 8건)
    total = len(prepared_chunks)
    sample_step = max(1, total // 8)
    sample_indices = list(range(0, min(total, 8 * sample_step), sample_step))[:8]
    sample = [(idx, prepared_chunks[idx]) for idx in sample_indices]

    previews_lines: list[str] = []
    for idx, chunk in sample:
        content = (chunk.get("content") or "")
        header, body = _extract_context_header(content)
        body_preview = body[:200].strip()
        meta = chunk.get("metadata") or {}
        previews_lines.append(
            f"[chunk_idx={idx}] article={meta.get('regulation_article')} chars={len(content)}\n"
            f"{body_preview}"
        )

    prompts_map = _load_chunking_prompts()
    system = prompts_map.get("quality_feedback_system", "")
    user_tpl = prompts_map.get("quality_feedback_user_template", "").strip()
    if not user_tpl:
        return prepared_chunks, {"overall_ok": True, "summary": "YAML 프롬프트 없음, 스킵"}

    user_msg = user_tpl.format(
        doc_title=doc_title,
        total_chunks=total,
        sample_count=len(sample),
        chunk_previews="\n\n---\n\n".join(previews_lines),
    )
    raw = _llm_call(
        f"{system}\n\n---\n\n{user_msg}" if system else user_msg,
        label="quality_feedback",
    )

    feedback_report: dict[str, Any] = {"overall_ok": True, "summary": "", "poor_chunks": []}
    if not raw:
        return prepared_chunks, feedback_report

    try:
        parsed = json.loads(_extract_json_from_llm(raw))
        if not isinstance(parsed, dict):
            raise ValueError("JSON 객체 아님")

        feedback_report["overall_ok"] = parsed.get("overall_ok", True)
        feedback_report["summary"] = parsed.get("summary", "")
        evaluations = parsed.get("evaluations") or []

        poor_indices: list[int] = []
        for ev in evaluations:
            if ev.get("quality") == "poor":
                chunk_idx = ev.get("chunk_idx")
                if chunk_idx is not None and isinstance(chunk_idx, int):
                    poor_indices.append(chunk_idx)
                    feedback_report["poor_chunks"].append({
                        "idx": chunk_idx,
                        "reason": ev.get("reason", ""),
                    })

        incr("rag_chunking_v2_quality_feedback_runs_total")
        logger.info(
            "rag_chunking_v2 quality_feedback: doc_title=%s overall_ok=%s poor=%s summary='%s'",
            doc_title,
            feedback_report["overall_ok"],
            len(poor_indices),
            (feedback_report["summary"] or "")[:80],
        )

        # POOR 청크 → 인접 청크와 병합 교정
        if poor_indices:
            result = list(prepared_chunks)
            merged_poor = 0
            for idx in sorted(set(poor_indices), reverse=True):
                if idx >= len(result):
                    continue
                chunk = result[idx]
                content = chunk.get("content") or ""
                # 너무 짧거나 제목만 있는 청크: 다음 청크와 병합
                if len(content) < 100 and idx + 1 < len(result):
                    next_chunk = result[idx + 1]
                    c2_lines = (next_chunk.get("content") or "").split("\n")
                    c2_body = "\n".join(
                        ln for ln in c2_lines
                        if not (ln.startswith("[") and "]" in ln) and not ln.startswith("문서 개요:")
                    ).strip()
                    merged_content = content.rstrip() + "\n" + c2_body
                    result[idx] = {**chunk, "content": merged_content}
                    result.pop(idx + 1)
                    merged_poor += 1
                # 문장이 잘린 청크: 이전 청크와 병합
                elif idx > 0 and not content.rstrip().endswith(("다.", "다", "임.", "임")):
                    prev_chunk = result[idx - 1]
                    _, cur_body = _extract_context_header(content)
                    prev_content = (prev_chunk.get("content") or "").rstrip()
                    merged_content = prev_content + "\n" + cur_body.lstrip()
                    result[idx - 1] = {**prev_chunk, "content": merged_content}
                    result.pop(idx)
                    merged_poor += 1

            if merged_poor:
                for i, chunk in enumerate(result):
                    meta = dict(chunk.get("metadata") or {})
                    meta["chunk_index"] = i
                    result[i] = {**chunk, "metadata": meta}
                logger.info(
                    "rag_chunking_v2 quality_feedback: 재교정 적용 doc_title=%s merged_poor=%s before=%s after=%s",
                    doc_title, merged_poor, total, len(result),
                )
            feedback_report["merged_poor"] = merged_poor
            return result, feedback_report

    except Exception as e:
        logger.warning("rag_chunking_v2 quality_feedback 파싱 실패: %s", e)
        incr("rag_chunking_v2_quality_feedback_error_total")

    return prepared_chunks, feedback_report


# =============================================================================
# 메인 파이프라인
# =============================================================================

def process_and_vectorize_v2(
    file_path: str | Path,
    rag_document_id: str,
    metadata: dict[str, Any] | None = None,
    *,
    chunk_size: int = 800,
    chunk_overlap: int = 120,
    doc_type: str = FINANCE_REGULATION_DOC_TYPE,
) -> dict[str, Any]:
    """
    에이전트형 청킹 v2 메인 파이프라인 (완전 구현).

      Step 1  Structural Anchoring  — LLM 문서 프로파일링 + 커스텀 앵커 패턴 생성
      Step 2  Hybrid Chunking       — 전략별 청킹 + Layout-Aware + Semantic Hybrid
      Step 3  Metadata Enrichment   — doc_summary 본문 주입 + 약한 메타데이터 LLM 보강
      Step 4  Self-Correction       — LLM 병합/분할 실제 적용
      Feedback Quality Feedback     — 저품질 청크 자동 재교정
    """
    settings = get_settings()
    path = Path(file_path)
    emb = _get_embedding_client()
    if emb is None:
        return {"ok": False, "error": "Embedding client not available"}

    try:
        text_content = _load_text_from_file(path)
    except Exception as e:
        return {"ok": False, "error": str(e)}

    meta = dict(metadata or {})
    meta.update(_extract_document_standard_meta(text_content, meta))
    doc_title = meta.get("title") or meta.get("file_name") or path.stem or "규정문서"
    is_pdf = path.suffix.lower() == ".pdf"

    logger.info(
        "rag_chunking_v2 pipeline: 시작 doc_id=%s doc_type=%s doc_title=%s",
        rag_document_id, doc_type, doc_title,
    )

    # ── Step 1: Structural Anchoring (Document Profiling) ─────────────────
    doc_profile: dict[str, Any] = {
        "structure_type": "standard_korean_regulation",
        "doc_character": "regulation",
        "chunking_strategy": "hierarchical",
        "doc_summary": "",
        "anchor_examples": [],
        "profiling_ok": False,
    }
    if bool(getattr(settings, "rag_chunking_v2_profiling_enabled", True)):
        doc_profile = _llm_document_profile(text_content, doc_title, doc_type)
    else:
        logger.debug("rag_chunking_v2 pipeline: profiling 비활성화")

    logger.info(
        "rag_chunking_v2 pipeline: [Step 1 완료] strategy=%s character=%s profiling_ok=%s anchors=%s",
        doc_profile.get("chunking_strategy"),
        doc_profile.get("doc_character"),
        doc_profile.get("profiling_ok"),
        doc_profile.get("anchor_examples"),
    )

    # ── Layout-Aware 전처리 ────────────────────────────────────────────────
    if bool(getattr(settings, "rag_chunking_v2_layout_aware_enabled", True)):
        text_content = _layout_aware_preprocess(text_content)

    # ── Step 2: Hybrid Chunking ──────────────────────────────────────────
    chunks_text, hierarchical_meta = _structural_chunking(
        text_content=text_content,
        doc_title=doc_title,
        doc_type=doc_type,
        profile=doc_profile,
        settings=settings,
        emb=emb,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )

    if not chunks_text:
        logger.warning("rag_chunking_v2 pipeline: 청킹 결과 없음 doc_id=%s", rag_document_id)
        return {"ok": True, "rag_document_id": rag_document_id, "chunks": []}

    logger.info(
        "rag_chunking_v2 pipeline: [Step 2 완료] strategy=%s chunks=%s",
        doc_profile.get("chunking_strategy"), len(chunks_text),
    )

    # ── prepared_chunks 구성 ─────────────────────────────────────────────
    regulation_article = meta.get("regulation_article") or meta.get("regulationArticle")
    regulation_clause = meta.get("regulation_clause") or meta.get("regulationClause")
    location = meta.get("location") or meta.get("regulationLocation")
    title = meta.get("title")
    if not location and (regulation_article or regulation_clause):
        location = f"규정 {regulation_article or ''} {regulation_clause or ''}".strip()
    file_path_str = str(path.resolve())

    prepared_chunks: list[dict[str, Any]] = []
    for i, content in enumerate(chunks_text):
        page_number = _extract_page_from_chunk(content) if is_pdf else 1
        h_meta = hierarchical_meta[i] if i < len(hierarchical_meta) else {}
        if is_hierarchical(doc_type) and h_meta:
            chunk_meta: dict[str, Any] = {
                **meta,
                "doc_id": str(rag_document_id),
                "chunk_index": i,
                "page_number": page_number,
                "file_path": file_path_str,
                "regulation_article": h_meta.get("regulation_article") or regulation_article,
                "regulation_clause": h_meta.get("regulation_clause") or regulation_clause,
                "location": h_meta.get("location") or location,
                "title": title,
                "doc_type": doc_type,
                "violation_clause": h_meta.get("violation_clause"),
                "parent_chunk_id": h_meta.get("parent_chunk_id"),
                "parent_article": h_meta.get("parent_article"),
                "parent_title": h_meta.get("parent_title"),
                "child_index": h_meta.get("child_index"),
                "chunk_level": h_meta.get("chunk_level"),
                "node_type": h_meta.get("node_type"),
            }
        else:
            chunk_meta = {
                **meta,
                "doc_id": str(rag_document_id),
                "chunk_index": i,
                "page_number": page_number,
                "file_path": file_path_str,
                "regulation_article": h_meta.get("regulation_article") or regulation_article,
                "regulation_clause": h_meta.get("regulation_clause") or regulation_clause,
                "location": h_meta.get("location") or location,
                "title": title,
                "doc_type": doc_type,
            }
        prepared_chunks.append({"content": content, "metadata": chunk_meta})

    # ── Step 3: Metadata Enrichment + Context Injection ──────────────────
    if bool(getattr(settings, "rag_chunking_v2_context_inject_enabled", True)):
        prepared_chunks = _inject_context_into_body(prepared_chunks, doc_title, doc_profile)

    if bool(getattr(settings, "rag_chunking_v2_llm_enrich_enabled", True)):
        prepared_chunks = _llm_enrich_chunk_headers(prepared_chunks, doc_title, doc_type)

    logger.info(
        "rag_chunking_v2 pipeline: [Step 3 완료] chunks=%s", len(prepared_chunks),
    )

    # ── Step 4: Self-Correction Loop ──────────────────────────────────────
    correction_report: dict[str, Any] = {}
    if bool(getattr(settings, "rag_chunking_v2_llm_verify_enabled", True)):
        prepared_chunks, correction_report = _llm_self_correction_loop(prepared_chunks, doc_title)
        logger.info(
            "rag_chunking_v2 pipeline: [Step 4 완료] after_correction=%s merges=%s splits=%s",
            len(prepared_chunks),
            correction_report.get("merges_applied", 0),
            correction_report.get("splits_applied", 0),
        )

    # ── Quality Gate ──────────────────────────────────────────────────────
    quality_report: dict[str, Any] = {}
    if bool(getattr(settings, "rag_quality_gate_enabled", True)):
        quality = _run_chunk_quality_gate(
            prepared_chunks,
            rag_document_id=str(rag_document_id),
            base_meta=meta,
            doc_type=doc_type,
            settings_obj=settings,
        )
        quality_report = quality.get("report") or {}
        prepared_chunks = quality.get("chunks") or []
        if correction_report:
            quality_report["v2_self_correction"] = correction_report
        if doc_profile.get("profiling_ok"):
            quality_report["v2_doc_profile"] = {
                "structure_type": doc_profile.get("structure_type"),
                "doc_character": doc_profile.get("doc_character"),
                "chunking_strategy": doc_profile.get("chunking_strategy"),
            }
        if not quality.get("ok"):
            return {
                "ok": False,
                "error": "RAG quality gate failed",
                "quality_report": quality_report,
            }
    else:
        if correction_report:
            quality_report["v2_self_correction"] = correction_report

    # ── Feedback: Layout 마커 제거 ────────────────────────────────────────
    prepared_chunks = _strip_layout_markers(prepared_chunks)

    # ── Feedback: Quality Feedback Loop (Phase 3 P2) ──────────────────────
    feedback_report: dict[str, Any] = {}
    if bool(getattr(settings, "rag_chunking_v2_feedback_enabled", True)) and prepared_chunks:
        prepared_chunks, feedback_report = _llm_quality_feedback_loop(prepared_chunks, doc_title)
        quality_report["v2_quality_feedback"] = feedback_report
        logger.info(
            "rag_chunking_v2 pipeline: [Feedback 완료] final_chunks=%s overall_ok=%s merged_poor=%s",
            len(prepared_chunks),
            feedback_report.get("overall_ok"),
            feedback_report.get("merged_poor", 0),
        )

    if not prepared_chunks:
        return {"ok": True, "rag_document_id": rag_document_id, "chunks": [], "quality_report": quality_report}

    # ── Embedding ─────────────────────────────────────────────────────────
    chunks_text_clean = [str(c.get("content") or "") for c in prepared_chunks]
    embeddings = emb.embed_documents(chunks_text_clean)
    if len(embeddings) != len(chunks_text_clean):
        return {"ok": False, "error": "Embedding count mismatch"}
    if embeddings and len(embeddings[0]) != EMBEDDING_DIM:
        return {"ok": False, "error": f"Embedding dim must be {EMBEDDING_DIM}"}

    chunks_out: list[dict[str, Any]] = []
    for i, (prepared, vec) in enumerate(zip(prepared_chunks, embeddings)):
        content = str(prepared.get("content") or "")
        chunk_meta = dict(prepared.get("metadata") or {})
        chunk_meta["chunk_index"] = i
        if chunk_meta.get("page_number") is None:
            chunk_meta["page_number"] = _extract_page_from_chunk(content) if is_pdf else 1
        chunks_out.append({
            "chunk_index": i,
            "content": content,
            "embedding": [float(x) for x in vec],
            "metadata": chunk_meta,
        })

    incr("rag_chunking_v2_vectorize_completed_total")
    logger.info(
        "rag_chunking_v2 파이프라인 완료: doc_id=%s final_chunks=%s "
        "profiling=%s strategy=%s layout=%s semantic_hybrid=%s "
        "context_inject=%s enrich=%s correction=%s merges=%s splits=%s feedback=%s",
        rag_document_id,
        len(chunks_out),
        "ok" if doc_profile.get("profiling_ok") else "default",
        doc_profile.get("chunking_strategy", "hierarchical"),
        "on" if getattr(settings, "rag_chunking_v2_layout_aware_enabled", True) else "off",
        "on" if getattr(settings, "rag_chunking_v2_semantic_hybrid_enabled", True) else "off",
        "on" if getattr(settings, "rag_chunking_v2_context_inject_enabled", True) else "off",
        "on" if getattr(settings, "rag_chunking_v2_llm_enrich_enabled", True) else "off",
        "on" if getattr(settings, "rag_chunking_v2_llm_verify_enabled", True) else "off",
        correction_report.get("merges_applied", 0),
        correction_report.get("splits_applied", 0),
        "on" if getattr(settings, "rag_chunking_v2_feedback_enabled", True) else "off",
    )
    return {
        "ok": True,
        "rag_document_id": rag_document_id,
        "chunks": chunks_out,
        "quality_report": quality_report,
    }
