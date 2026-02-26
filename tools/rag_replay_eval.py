#!/usr/bin/env python3
"""
RAG 리플레이 평가 실행기.

사용 예:
  python3 tools/rag_replay_eval.py \
    --cases docs/prompts/golden_rag_cases.json \
    --tenant-id 1 \
    --doc-ids 23,26 \
    --top-k 5 \
    --threshold 0.7
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from core.analysis.rag import retrieve_rag_pgvector
from core.analysis.rag_eval import evaluate_retrieval_cases


def _parse_doc_ids(raw: str | None) -> list[int] | None:
    if not raw:
        return None
    out: list[int] = []
    for t in raw.split(","):
        s = t.strip()
        if not s:
            continue
        try:
            out.append(int(s))
        except Exception:
            continue
    return out or None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", required=True, help="골든셋 JSON 경로")
    ap.add_argument("--tenant-id", type=int, default=1)
    ap.add_argument("--doc-ids", default="", help="예: 23,26")
    ap.add_argument("--top-k", type=int, default=5)
    ap.add_argument("--threshold", type=float, default=0.7)
    args = ap.parse_args()

    cases_path = Path(args.cases)
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    doc_ids = _parse_doc_ids(args.doc_ids)

    def _retrieve(query: str, top_k: int) -> list[dict[str, Any]]:
        return retrieve_rag_pgvector(
            query,
            top_k=top_k,
            similarity_threshold=float(args.threshold),
            doc_ids=doc_ids,
            tenant_id=int(args.tenant_id),
            include_article_clause=True,
        )

    report = evaluate_retrieval_cases(cases, retrieve_fn=_retrieve, top_k=int(args.top_k))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    # 간단 게이트: 0건률 20% 이하, hit@k 70% 이상
    if report["zero_rate"] > 0.2 or report["hit_at_k"] < 0.7:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
