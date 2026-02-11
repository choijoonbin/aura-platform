"""
Database engine and session for PostgreSQL + pgvector.

dwp_aura.rag_chunk 등 pgvector 테이블 접근용.
"""

import logging
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from core.config import get_settings

logger = logging.getLogger(__name__)

_engine = None
_SessionLocal = None


def get_engine():
    """SQLAlchemy engine (pgvector 확장 적용 DB)."""
    global _engine
    if _engine is not None:
        return _engine
    settings = get_settings()
    _engine = create_engine(
        settings.database_url,
        pool_size=getattr(settings, "database_pool_size", 10),
        max_overflow=getattr(settings, "database_max_overflow", 20),
    )
    return _engine


def get_session_factory():
    """Session factory for dwp_aura.rag_chunk 등."""
    global _SessionLocal
    if _SessionLocal is not None:
        return _SessionLocal
    _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=get_engine())
    return _SessionLocal


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Context manager for DB session. 사용 후 commit/rollback 처리."""
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def ensure_pgvector_extension(session: Session) -> None:
    """CREATE EXTENSION IF NOT EXISTS vector; (같은 DB에서 1회)."""
    session.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
    session.commit()
