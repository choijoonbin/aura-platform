#!/usr/bin/env python3
"""
Analysis replay gate runner (Aura-side).

CI/CD에서 이 스크립트를 호출하면 리플레이 결과를 기준으로 배포 가능 여부를 판정한다.
현재는 retrieval 품질 지표를 게이트로 사용하며, 향후 analysis 정답률 지표를 추가 확장한다.

Usage:
  python3 tools/analysis_replay_gate.py \
    --cases docs/prompts/golden_rag_cases.json \
    --tenant-id 1 \
    --doc-ids 23,26 \
    --top-k 5 \
    --threshold 0.70 \
    --max-zero-rate 0.20 \
    --min-hit-at-k 0.70 \
    --min-strict-top1 0.45
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
    for tok in raw.split(","):
        s = tok.strip()
        if not s:
            continue
        try:
            out.append(int(s))
        except Exception:
            continue
    return out or None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", required=True)
    ap.add_argument("--tenant-id", type=int, default=1)
    ap.add_argument("--doc-ids", default="")
    ap.add_argument("--top-k", type=int, default=5)
    ap.add_argument("--threshold", type=float, default=0.7)
    ap.add_argument("--max-zero-rate", type=float, default=0.2)
    ap.add_argument("--min-hit-at-k", type=float, default=0.7)
    ap.add_argument("--min-strict-top1", type=float, default=0.45)
    ap.add_argument("--out", default="", help="optional json output path")
    args = ap.parse_args()

    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))
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
    gate_checks = {
        "zero_rate_ok": report["zero_rate"] <= float(args.max_zero_rate),
        "hit_at_k_ok": report["hit_at_k"] >= float(args.min_hit_at_k),
        "strict_top1_ok": report["strict_hit_top1"] >= float(args.min_strict_top1),
    }
    gate_passed = all(gate_checks.values())
    output = {
        "gate_passed": gate_passed,
        "thresholds": {
            "max_zero_rate": float(args.max_zero_rate),
            "min_hit_at_k": float(args.min_hit_at_k),
            "min_strict_top1": float(args.min_strict_top1),
        },
        "checks": gate_checks,
        "report": report,
    }
    text = json.dumps(output, ensure_ascii=False, indent=2)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    return 0 if gate_passed else 2


if __name__ == "__main__":
    raise SystemExit(main())

