#!/usr/bin/env python3
"""
pgvector 확장 및 dwp_aura.rag_chunk 스키마/테이블 초기화.
DATABASE_URL로 접속한 DB에 CREATE EXTENSION vector; CREATE SCHEMA dwp_aura; CREATE TABLE dwp_aura.rag_chunk; 수행.
실행: python3 scripts/init_rag_pgvector.py (프로젝트 루트에서, .env에 DATABASE_URL 설정 후)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    from core.config import get_settings
    from database.engine import get_engine
    from database.models.rag_chunk import create_rag_chunk_table_if_not_exists, FULL_TABLE

    settings = get_settings()
    url = getattr(settings, "database_url", "") or ""
    if not url or "postgresql" not in url.split(":")[0]:
        print("DATABASE_URL가 PostgreSQL 형식이 아니거나 비어 있습니다. .env 확인 후 다시 실행하세요.")
        sys.exit(1)
    print("PostgreSQL 연결 중...")
    engine = get_engine()
    print("pgvector 확장 및 dwp_aura.rag_chunk 테이블 생성 중...")
    create_rag_chunk_table_if_not_exists(engine)
    print(f"완료: {FULL_TABLE} 테이블이 존재합니다.")
    print("다음으로 python3 scripts/check_rag_vector.py 로 연결·데이터를 확인하세요.")


if __name__ == "__main__":
    main()
