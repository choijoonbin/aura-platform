#!/usr/bin/env python3
"""
pgvector 사용 시 DB 연결 확인용.
dwp_aura.rag_chunk 테이블 생성·마이그레이션은 백엔드에서 수행합니다. Aura는 INSERT/DDL 하지 않음.
실행: python3 scripts/init_rag_pgvector.py (프로젝트 루트에서, .env에 DATABASE_URL 설정 후)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    from core.config import get_settings
    from database.engine import get_engine
    from database.models.rag_chunk import FULL_TABLE

    settings = get_settings()
    url = getattr(settings, "database_url", "") or ""
    if not url or "postgresql" not in url.split(":")[0]:
        print("DATABASE_URL가 PostgreSQL 형식이 아니거나 비어 있습니다. .env 확인 후 다시 실행하세요.")
        sys.exit(1)
    print("PostgreSQL 연결 중...")
    engine = get_engine()
    with engine.connect() as conn:
        from sqlalchemy import text
        conn.execute(text("SELECT 1"))
    print("연결 성공.")
    print(f"rag_chunk 테이블({FULL_TABLE}) 생성·마이그레이션은 백엔드에서 수행하세요.")
    print("데이터 확인: python3 scripts/check_rag_vector.py")


if __name__ == "__main__":
    main()
