"""Synchronous SQLAlchemy engine and per-request session dependency.

Route handlers that use these must be plain `def` (FastAPI runs them in a threadpool) so blocking
database calls never run inside the async event loop.
"""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

DB_CONNECT_TIMEOUT_SECONDS = 3


@lru_cache
def get_engine() -> Engine:
    settings = get_settings()
    return create_engine(
        settings.DATABASE_URL.get_secret_value(),
        pool_pre_ping=True,
        connect_args={
            "connect_timeout": DB_CONNECT_TIMEOUT_SECONDS,
            # Finite waits: a stuck lock/statement becomes a sanitized retryable error, not a hang.
            "options": f"-c statement_timeout={settings.DB_STATEMENT_TIMEOUT_MS}"
            f" -c lock_timeout={settings.DB_LOCK_TIMEOUT_MS}",
        },
    )


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request, always closed."""
    session = get_sessionmaker()()
    try:
        yield session
    finally:
        session.close()
