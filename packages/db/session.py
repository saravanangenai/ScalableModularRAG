from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager, contextmanager

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine, AsyncSession
from sqlalchemy.orm import Session, sessionmaker

from packages.db.config import Settings
from packages.exceptions import DatabaseError


def _build_sync_engine(settings: Settings | None = None):
    settings = settings or Settings()
    try:
        return create_engine(settings.sync_database_url)
    except Exception as exc:
        raise DatabaseError("failed to create sync database engine", original_exception=exc) from exc


def _build_async_engine(settings: Settings | None = None):
    settings = settings or Settings()
    try:
        return create_async_engine(settings.async_database_url)
    except Exception as exc:
        raise DatabaseError(
            "failed to create async database engine", original_exception=exc
        ) from exc


def get_sync_sessionmaker(settings: Settings | None = None) -> sessionmaker[Session]:
    engine = _build_sync_engine(settings)
    return sessionmaker(bind=engine, expire_on_commit=False)


def get_async_sessionmaker(
    settings: Settings | None = None,
) -> async_sessionmaker[AsyncSession]:
    engine = _build_async_engine(settings)
    return async_sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def sync_session(settings: Settings | None = None) -> Generator[Session, None, None]:
    session_factory = get_sync_sessionmaker(settings)
    session = session_factory()
    try:
        yield session
    except Exception as exc:
        session.rollback()
        raise DatabaseError("sync session operation failed", original_exception=exc) from exc
    finally:
        session.close()


@asynccontextmanager
async def async_session(settings: Settings | None = None) -> AsyncGenerator[AsyncSession, None]:
    session_factory = get_async_sessionmaker(settings)
    session = session_factory()
    try:
        yield session
    except Exception as exc:
        await session.rollback()
        raise DatabaseError("async session operation failed", original_exception=exc) from exc
    finally:
        await session.close()
