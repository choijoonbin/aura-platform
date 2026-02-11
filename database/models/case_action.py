"""
dwp_aura.case_action_history, dwp_aura.fi_doc_header 테이블 정의 (참조용).

- Aura는 이 테이블에 직접 INSERT/UPDATE하지 않습니다. 조치 이력·전표 상태는 백엔드가 관리합니다.
- 스키마 참조 또는 마이그레이션 정합성용으로만 유지됩니다.
"""

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

SCHEMA = "dwp_aura"
TABLE_ACTION_HISTORY = "case_action_history"
TABLE_FI_DOC_HEADER = "fi_doc_header"
FULL_ACTION_HISTORY = f"{SCHEMA}.{TABLE_ACTION_HISTORY}"
FULL_FI_DOC_HEADER = f"{SCHEMA}.{TABLE_FI_DOC_HEADER}"


def create_case_action_tables_if_not_exists(engine: Engine) -> None:
    """
    case_action_history: 실행자 ID, 조치 유형, 코멘트 즉시 기록.
    fi_doc_header: 관련 전표 status_code (조치 결과에 맞춰 동기화).
    """
    with engine.connect() as conn:
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA};"))
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS {FULL_ACTION_HISTORY} (
                id SERIAL PRIMARY KEY,
                case_id VARCHAR(128) NOT NULL,
                request_id VARCHAR(128) NOT NULL,
                executor_id VARCHAR(128) NOT NULL,
                action_type VARCHAR(32) NOT NULL,
                comment TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """))
        conn.execute(text(f"""
            CREATE INDEX IF NOT EXISTS ix_case_action_history_case_id
            ON {FULL_ACTION_HISTORY} (case_id);
        """))
        conn.execute(text(f"""
            CREATE INDEX IF NOT EXISTS ix_case_action_history_request_id
            ON {FULL_ACTION_HISTORY} (request_id);
        """))
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS {FULL_FI_DOC_HEADER} (
                id SERIAL PRIMARY KEY,
                case_id VARCHAR(128),
                doc_key VARCHAR(256),
                bukrs VARCHAR(16),
                belnr VARCHAR(32),
                gjahr VARCHAR(8),
                status_code VARCHAR(32) NOT NULL DEFAULT 'PENDING',
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """))
        conn.execute(text(f"""
            CREATE INDEX IF NOT EXISTS ix_fi_doc_header_case_id
            ON {FULL_FI_DOC_HEADER} (case_id);
        """))
        conn.execute(text(f"""
            CREATE INDEX IF NOT EXISTS ix_fi_doc_header_doc_key
            ON {FULL_FI_DOC_HEADER} (doc_key);
        """))
        conn.commit()
    logger.info("case_action tables ready: %s, %s", FULL_ACTION_HISTORY, FULL_FI_DOC_HEADER)
