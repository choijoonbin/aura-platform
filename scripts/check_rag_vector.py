#!/usr/bin/env python3
"""
벡터 저장소(pgvector / Chroma)에 적재된 데이터 존재 여부 확인.
실행: python scripts/check_rag_vector.py (프로젝트 루트에서)
"""

import os
import sys

# 프로젝트 루트를 path에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def check_pgvector():
    """dwp_aura.rag_chunk 테이블 레코드 수 및 doc_id 목록."""
    from core.config import get_settings
    from database.engine import get_engine, get_session
    from database.models.rag_chunk import FULL_TABLE, create_rag_chunk_table_if_not_exists
    from sqlalchemy import text

    settings = get_settings()
    engine = get_engine()
    create_rag_chunk_table_if_not_exists(engine)
    with get_session() as session:
        r = session.execute(text(f"SELECT COUNT(*) FROM {FULL_TABLE}")).scalar()
        count = r or 0
        if count == 0:
            return 0, []
        rows = session.execute(
            text(f"SELECT DISTINCT doc_id FROM {FULL_TABLE} ORDER BY doc_id")
        ).fetchall()
        doc_ids = [row[0] for row in rows]
    return count, doc_ids


def check_chroma():
    """Chroma 컬렉션 문서 수 (vector_store_type=chroma 시)."""
    from core.analysis.rag import get_vector_store
    store = get_vector_store()
    if store is None:
        return None
    try:
        coll = store._collection
        return coll.count()
    except Exception as e:
        return f"error: {e}"


def main():
    from core.config import get_settings
    settings = get_settings()
    vs_type = (getattr(settings, "vector_store_type", "none") or "").strip().lower()

    print("=== 벡터 저장소 데이터 확인 ===\n")
    print(f"vector_store_type (설정): {vs_type}")

    if vs_type == "pgvector":
        try:
            count, doc_ids = check_pgvector()
            print(f"\n[pgvector] dwp_aura.rag_chunk")
            print(f"  Total Chunks: {count}" + (" (정상 연결 상태)" if count == 0 else ""))
            if doc_ids:
                print(f"  doc_id 목록: {doc_ids[:20]}{' ...' if len(doc_ids) > 20 else ''}")
        except Exception as e:
            print(f"\n[pgvector] 연결/조회 실패: {e}")
            print("  → .env 의 DATABASE_URL, PostgreSQL 접속 가능 여부 확인")

    elif vs_type == "chroma":
        n = check_chroma()
        if n is None:
            print("\n[Chroma] 벡터 스토어 미설정 또는 의존성 미설치")
        elif isinstance(n, str):
            print(f"\n[Chroma] {n}")
        else:
            print(f"\n[Chroma] 컬렉션 문서 수: {n}")

    else:
        print("\npgvector/chroma 미사용 (vector_store_type=none 또는 미설정).")
        print("  → 데이터 확인을 위해 .env 에 VECTOR_STORE_TYPE=pgvector 또는 chroma 설정 후 PostgreSQL/Chroma 구성.")

    print()


if __name__ == "__main__":
    main()
