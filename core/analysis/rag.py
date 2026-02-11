"""
RAG 유틸 (Phase3 및 공통)

artifacts 청킹, topK retrieve, ragRefs 스키마 생성.
"""

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def chunk_artifacts(artifacts: dict[str, Any]) -> list[tuple[str, str, str, str]]:
    """
    artifacts → (sourceType, sourceKey, excerpt, full_text) 리스트.

    policies, documents, openItems, fiDocument 순으로 추출.
    """
    chunks: list[tuple[str, str, str, str]] = []
    if not artifacts or not isinstance(artifacts, dict):
        return chunks

    for i, p in enumerate((artifacts.get("policies") or [])[:20]):
        if isinstance(p, dict):
            text = json.dumps(p, ensure_ascii=False)[:2000]
            key = p.get("id") or p.get("key") or f"POLICY-{i}"
            chunks.append(("POLICY", str(key), text[:500], text))
        elif isinstance(p, str):
            chunks.append(("POLICY", f"POLICY-{i}", p[:500], p))

    for i, d in enumerate((artifacts.get("documents") or [])[:20]):
        if isinstance(d, dict):
            text = json.dumps(d, ensure_ascii=False)[:2000]
            key = d.get("id") or d.get("docKey") or d.get("key") or f"DOC-{i}"
            chunks.append(("DOCUMENT", str(key), text[:500], text))
        elif isinstance(d, str):
            chunks.append(("DOCUMENT", f"DOC-{i}", d[:500], d))

    for i, o in enumerate((artifacts.get("openItems") or [])[:15]):
        if isinstance(o, dict):
            text = json.dumps(o, ensure_ascii=False)[:1500]
            key = o.get("id") or o.get("key") or f"OPEN-{i}"
            chunks.append(("OPEN_ITEM", str(key), text[:500], text))

    fi = artifacts.get("fiDocument") or {}
    if isinstance(fi, dict) and fi:
        text = json.dumps(fi, ensure_ascii=False)[:2000]
        key = fi.get("docKey") or fi.get("id") or "FI-DOC"
        chunks.append(("FI_DOCUMENT", str(key), text[:500], text))

    return chunks


def retrieve_rag(
    chunks: list[tuple[str, str, str, str]],
    top_k: int,
    *,
    min_refs_when_available: int = 2,
) -> list[dict[str, Any]]:
    """
    topK개 선택 후 ragRefs 형식으로 반환.

    refId, sourceType, sourceKey, excerpt, score. 정상 케이스(청크 2개 이상) 시
    min_refs_when_available 건 이상 반환.
    """
    k = (
        max(min_refs_when_available, min(top_k, len(chunks)))
        if len(chunks) >= min_refs_when_available
        else min(1, len(chunks))
    )
    refs: list[dict[str, Any]] = []
    for i, (stype, skey, excerpt, _) in enumerate(chunks[:k]):
        refs.append({
            "refId": f"ref-{i+1}",
            "sourceType": stype,
            "sourceKey": skey,
            "excerpt": excerpt[:400],
            "score": round(0.9 - i * 0.05, 2),
        })
    if not refs and chunks:
        refs.append({
            "refId": "ref-1",
            "sourceType": chunks[0][0],
            "sourceKey": chunks[0][1],
            "excerpt": chunks[0][2][:400],
            "score": 0.85,
        })
    return refs
