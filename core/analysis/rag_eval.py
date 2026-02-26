"""
RAG 평가 유틸.

- 골든셋 기반 retrieval 성능(0건률, hit@k, 인용 조항 일치율) 산출
- 배포 전 리플레이 자동평가에서 사용
"""

from __future__ import annotations

from typing import Any, Callable


def _extract_articles(results: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for r in results or []:
        if not isinstance(r, dict):
            continue
        a = str(
            r.get("regulation_article")
            or r.get("article")
            or r.get("regulationArticle")
            or ""
        ).replace(" ", "").strip()
        if not a or a in seen:
            continue
        seen.add(a)
        out.append(a)
    return out


def evaluate_retrieval_cases(
    cases: list[dict[str, Any]],
    *,
    retrieve_fn: Callable[[str, int], list[dict[str, Any]]],
    top_k: int = 5,
) -> dict[str, Any]:
    """
    cases 예시:
    [
      {"id":"holiday_1","query":"...","expected_articles":["제39조"]},
      ...
    ]
    """
    total = 0
    zero = 0
    hit = 0
    strict_hit = 0
    details: list[dict[str, Any]] = []

    for c in cases or []:
        if not isinstance(c, dict):
            continue
        q = str(c.get("query") or "").strip()
        if not q:
            continue
        total += 1
        expected = [
            str(a).replace(" ", "").strip()
            for a in (c.get("expected_articles") or [])
            if str(a).strip()
        ]
        results = retrieve_fn(q, top_k)
        articles = _extract_articles(results)
        if not results:
            zero += 1
        has_hit = bool(set(expected) & set(articles)) if expected else bool(results)
        if has_hit:
            hit += 1
        # strict_hit: expected가 있는 경우 top1 article 일치
        top1 = articles[0] if articles else ""
        if expected and top1 in expected:
            strict_hit += 1
        details.append(
            {
                "id": c.get("id"),
                "query": q,
                "expected_articles": expected,
                "retrieved_articles": articles,
                "result_count": len(results or []),
                "hit": has_hit,
                "strict_hit_top1": bool(expected and top1 in expected),
            }
        )

    denom = max(total, 1)
    return {
        "total_cases": total,
        "zero_results": zero,
        "zero_rate": round(zero / denom, 4),
        "hit_at_k": round(hit / denom, 4),
        "strict_hit_top1": round(strict_hit / denom, 4),
        "details": details,
    }
