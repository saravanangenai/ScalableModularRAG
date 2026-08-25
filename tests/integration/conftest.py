from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from httpx import ASGITransport
from pydantic_settings import BaseSettings, SettingsConfigDict

from packages.db.session import _build_sync_engine, get_async_sessionmaker

REPO_ROOT = Path(__file__).resolve().parents[2]


class KeycloakAdminSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file="infra/.env", extra="ignore")

    keycloak_admin: str
    keycloak_admin_password: str


class KeycloakTestSettings(BaseSettings):
    """Dev-only Keycloak test identities, written by scripts/setup_keycloak_dev.py."""

    model_config = SettingsConfigDict(env_file="infra/.env", extra="ignore")

    keycloak_issuer_url: str
    keycloak_test_client_id: str
    keycloak_test_client_secret: str
    keycloak_test_username: str
    keycloak_test_password: str
    keycloak_test_username_2: str
    keycloak_test_password_2: str


@pytest.fixture(scope="session")
def keycloak_settings() -> KeycloakTestSettings:
    return KeycloakTestSettings()


@pytest.fixture()
def mint_token(keycloak_settings):
    """Returns a callable(username, password) -> real access token, minted against the live
    local Keycloak via the Resource Owner Password Credentials grant."""

    def _mint(username: str, password: str) -> str:
        response = httpx.post(
            f"{keycloak_settings.keycloak_issuer_url}/protocol/openid-connect/token",
            data={
                "grant_type": "password",
                "client_id": keycloak_settings.keycloak_test_client_id,
                "client_secret": keycloak_settings.keycloak_test_client_secret,
                "username": username,
                "password": password,
            },
            timeout=10.0,
        )
        response.raise_for_status()
        return response.json()["access_token"]

    return _mint


@pytest.fixture()
def user1_token(mint_token, keycloak_settings) -> str:
    return mint_token(
        keycloak_settings.keycloak_test_username, keycloak_settings.keycloak_test_password
    )


@pytest.fixture()
def user2_token(mint_token, keycloak_settings) -> str:
    return mint_token(
        keycloak_settings.keycloak_test_username_2, keycloak_settings.keycloak_test_password_2
    )


@pytest.fixture()
def create_keycloak_user(keycloak_settings):
    """Factory creating a brand-new throwaway Keycloak identity via the Admin REST API —
    used for JIT-provisioning tests that need a genuinely never-before-seen `sub`, which the
    shared testuser/testuser2 identities can't provide once they've been used once."""
    import uuid as uuid_module

    admin_settings = KeycloakAdminSettings()

    base_url, realm_name = keycloak_settings.keycloak_issuer_url.rsplit("/realms/", 1)

    def _create() -> tuple[str, str]:
        with httpx.Client(timeout=10.0) as client:
            token_response = client.post(
                f"{base_url}/realms/master/protocol/openid-connect/token",
                data={
                    "grant_type": "password",
                    "client_id": "admin-cli",
                    "username": admin_settings.keycloak_admin,
                    "password": admin_settings.keycloak_admin_password,
                },
            )
            token_response.raise_for_status()
            admin_token = token_response.json()["access_token"]
            headers = {"Authorization": f"Bearer {admin_token}"}

            username = f"jit-test-{uuid_module.uuid4().hex[:12]}"
            password = "jit-test-changeme"
            users_url = f"{base_url}/admin/realms/{realm_name}/users"

            create_response = client.post(
                users_url,
                headers=headers,
                json={
                    "username": username,
                    "email": f"{username}@example.com",
                    "firstName": "JIT",
                    "lastName": "Test",
                    "enabled": True,
                    "emailVerified": True,
                },
            )
            create_response.raise_for_status()
            user_id = create_response.headers["Location"].rstrip("/").rsplit("/", 1)[-1]

            reset_response = client.put(
                f"{users_url}/{user_id}/reset-password",
                headers=headers,
                json={"type": "password", "value": password, "temporary": False},
            )
            reset_response.raise_for_status()

        return username, password

    return _create


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


@pytest_asyncio.fixture()
async def api_client(db_engine):
    """An httpx.AsyncClient talking directly to the real apps.api.main FastAPI app over
    ASGI (no separate uvicorn process needed) — but against the real Postgres (db_engine
    ensures migrations are applied) and real Keycloak (packages.auth.jwt hits the live JWKS
    endpoint), per this project's real-dependencies-over-mocks testing preference."""
    from apps.api.main import app

    app.state.session_factory = get_async_sessionmaker()
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
