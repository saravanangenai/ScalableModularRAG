from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from packages.db.config import Settings
from packages.db.session import get_async_sessionmaker, get_sync_sessionmaker


def _settings() -> Settings:
    return Settings(
        postgres_user="u", postgres_password="p", postgres_db="d", _env_file=None
    )


def test_sync_sessionmaker_produces_sync_session():
    session_factory = get_sync_sessionmaker(_settings())
    session = session_factory()
    try:
        assert isinstance(session, Session)
    finally:
        session.close()


def test_async_sessionmaker_produces_async_session():
    session_factory = get_async_sessionmaker(_settings())
    session = session_factory()
    assert isinstance(session, AsyncSession)
