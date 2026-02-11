"""
dwp_aura.rag_chunk 모델 (pgvector).

embedding vector(1536), doc_id, chunk_index, content 및 규정 인용용 메타데이터.
"""

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

SCHEMA = "dwp_aura"
TABLE_NAME = "rag_chunk"
FULL_TABLE = f"{SCHEMA}.{TABLE_NAME}"


def create_rag_chunk_table_if_not_exists(engine: Engine) -> None:
    """
    CREATE EXTENSION vector; CREATE SCHEMA IF NOT EXISTS dwp_aura;
    CREATE TABLE IF NOT EXISTS dwp_aura.rag_chunk (...).
    """
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA};"))
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS {FULL_TABLE} (
                id SERIAL PRIMARY KEY,
                doc_id VARCHAR(256) NOT NULL,
                chunk_index INTEGER NOT NULL,
                content TEXT NOT NULL,
                embedding vector(1536) NOT NULL,
                regulation_article VARCHAR(64),
                regulation_clause VARCHAR(64),
                location VARCHAR(256),
                title VARCHAR(512),
                doc_type VARCHAR(32),
                metadata_json JSONB
            );
        """))
        conn.execute(text(f"""
            CREATE INDEX IF NOT EXISTS ix_rag_chunk_doc_id ON {FULL_TABLE} (doc_id);
        """))
        conn.commit()
    logger.info("rag_chunk table ready: %s", FULL_TABLE)
