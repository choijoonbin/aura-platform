"""
dwp_aura.rag_chunk 테이블 상수 (Aura는 INSERT/DDL 하지 않음).

- 검색(retrieve_rag_pgvector) 시 테이블명 참조용.
- 테이블 생성·마이그레이션은 백엔드에서 수행.
"""

SCHEMA = "dwp_aura"
TABLE_NAME = "rag_chunk"
FULL_TABLE = f"{SCHEMA}.{TABLE_NAME}"
