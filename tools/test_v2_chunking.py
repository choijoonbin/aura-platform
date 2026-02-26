#!/usr/bin/env python3
"""
v2 에이전트형 청킹 smoke 테스트.
샘플 규정 텍스트로 process_and_vectorize_v2 실행 → 로그 및 결과 확인.

사용: RAG_CHUNKING_VERSION=v2 python3 tools/test_v2_chunking.py
"""

import logging
import sys
from pathlib import Path

# 프로젝트 루트를 path에 추가
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 로깅을 stdout으로 출력하여 로그 확인
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

SAMPLE_TEXT = """
제1장 총칙

제1조 목적
이 규정은 법인카드 및 경비 지출에 관한 사항을 정한다.

제2조 적용 범위
본 규정은 전 직원의 법인카드 사용에 적용된다.

제3장 지출

제12조 식대
1항 주말 및 공휴일 식대는 원칙적으로 인정하지 않는다.
2항 단, 업무상 불가피한 경우 사전 승인을 받은 경우에는 예외로 한다.
3항 1항 및 2항의 한도는 별도로 정한다.

제13조 여비
1항 국내 출장 시 교통비는 실비로 지급한다.
2항 해외 출장은 별도 규정에 따른다.
"""


def main() -> int:
    tmp_dir = ROOT / "data" / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    sample_path = tmp_dir / "test_v2_sample.txt"
    sample_path.write_text(SAMPLE_TEXT.strip(), encoding="utf-8")

    from core.analysis.rag_chunking_v2 import process_and_vectorize_v2
    from core.synapse_schema import DOC_TYPE_HIERARCHICAL

    print("=" * 60)
    print("v2 에이전트형 청킹 smoke 테스트")
    print("=" * 60)
    print(f"파일: {sample_path}")
    print(f"길이: {len(SAMPLE_TEXT)} chars")
    print()

    result = process_and_vectorize_v2(
        sample_path,
        rag_document_id="test-v2-smoke",
        metadata={"title": "운영규정(테스트)"},
        doc_type=DOC_TYPE_HIERARCHICAL,
    )

    if not result.get("ok"):
        print("FAIL:", result.get("error", "Unknown error"))
        return 1

    chunks = result.get("chunks", [])
    qr = result.get("quality_report", {})
    print("=" * 60)
    print(f"완료: ok=True, chunks={len(chunks)}")
    print(f"quality_report.keys: {list(qr.keys())}")
    if "v2_doc_profile" in qr:
        print(f"  v2_doc_profile: {qr['v2_doc_profile']}")
    if "v2_self_correction" in qr:
        sc = qr["v2_self_correction"]
        print(f"  v2_self_correction: merges={sc.get('merges_applied')} splits={sc.get('splits_applied')}")
    if "v2_quality_feedback" in qr:
        fb = qr["v2_quality_feedback"]
        print(f"  v2_quality_feedback: overall_ok={fb.get('overall_ok')}")
    if chunks:
        c0 = chunks[0]
        content_preview = (c0.get("content") or "")[:200]
        print(f"첫 청크 미리보기: {content_preview}...")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
