from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from packages.db.session import _build_sync_engine

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def db_engine():
    """Runs the real Alembic migration (tables + indexes + RLS policies) against the live
    Postgres in infra/docker-compose.yml once per test session, then reverts it. Requires
    `docker compose up -d postgres` and infra/.env populated from infra/.env.example."""
    alembic_cfg = Config(str(REPO_ROOT / "alembic.ini"))
    command.upgrade(alembic_cfg, "head")

    engine = _build_sync_engine()
    yield engine
    engine.dispose()

    command.downgrade(alembic_cfg, "base")


@pytest.fixture()
def db_session(db_engine):
    from sqlalchemy.orm import Session

    session = Session(bind=db_engine)
    try:
        yield session
    finally:
        session.rollback()
        session.close()
