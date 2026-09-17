"""One-shot local dev bootstrap for Keycloak: creates the mm-rag realm, a confidential
client (mm-rag-api) with Direct Access Grants enabled so tests can mint real tokens via the
Resource Owner Password Credentials grant, and a test user. Idempotent — safe to re-run.

Usage: uv run python scripts/setup_keycloak_dev.py
Requires KEYCLOAK_ADMIN / KEYCLOAK_ADMIN_PASSWORD in infra/.env (dev-only credentials for
this script; apps/api never uses them at runtime).
"""

import sys
from pathlib import Path

import httpx
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[1]
KEYCLOAK_BASE_URL = "http://localhost:8080"
REALM_NAME = "mm-rag"
CLIENT_ID = "mm-rag-api"
SPA_CLIENT_ID = "mm-rag-ui"
SPA_DEV_ORIGIN = "http://localhost:5173"
TEST_USERS = [
    ("testuser", "testuser@example.com", "testuser-changeme"),
    ("testuser2", "testuser2@example.com", "testuser2-changeme"),
]


class BootstrapSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file="infra/.env", extra="ignore")

    keycloak_admin: str
    keycloak_admin_password: str


def get_admin_token(client: httpx.Client, settings: BootstrapSettings) -> str:
    response = client.post(
        f"{KEYCLOAK_BASE_URL}/realms/master/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": settings.keycloak_admin,
            "password": settings.keycloak_admin_password,
        },
    )
    response.raise_for_status()
    return response.json()["access_token"]


# Local-dev-only token lifetimes, deliberately longer than Keycloak's defaults
# (accessTokenLifespan defaults to 300s) so a manual testing/demo session in
# apps/UI (specs/071-search-frontend) doesn't run into "session expired" every 5
# minutes. Not a production security posture — revisit before any real deployment.
DEV_ACCESS_TOKEN_LIFESPAN = 300  # 5 minutes
DEV_SSO_SESSION_IDLE_TIMEOUT = 7200  # 2 hours


def ensure_realm(client: httpx.Client, headers: dict) -> None:
    response = client.get(f"{KEYCLOAK_BASE_URL}/admin/realms/{REALM_NAME}", headers=headers)
    realm_settings = {
        "realm": REALM_NAME,
        "enabled": True,
        "accessTokenLifespan": DEV_ACCESS_TOKEN_LIFESPAN,
        "ssoSessionIdleTimeout": DEV_SSO_SESSION_IDLE_TIMEOUT,
    }
    if response.status_code == 200:
        update_response = client.put(
            f"{KEYCLOAK_BASE_URL}/admin/realms/{REALM_NAME}",
            headers=headers,
            json={**response.json(), **realm_settings},
        )
        update_response.raise_for_status()
        print(f"realm {REALM_NAME!r} already exists (token lifetimes confirmed)")
        return
    response = client.post(
        f"{KEYCLOAK_BASE_URL}/admin/realms",
        headers=headers,
        json=realm_settings,
    )
    response.raise_for_status()
    print(f"created realm {REALM_NAME!r}")


def ensure_client(client: httpx.Client, headers: dict) -> str:
    response = client.get(
        f"{KEYCLOAK_BASE_URL}/admin/realms/{REALM_NAME}/clients",
        headers=headers,
        params={"clientId": CLIENT_ID},
    )
    response.raise_for_status()
    existing = response.json()
    if existing:
        client_uuid = existing[0]["id"]
        print(f"client {CLIENT_ID!r} already exists")
    else:
        response = client.post(
            f"{KEYCLOAK_BASE_URL}/admin/realms/{REALM_NAME}/clients",
            headers=headers,
            json={
                "clientId": CLIENT_ID,
                "enabled": True,
                "protocol": "openid-connect",
                "publicClient": False,
                "directAccessGrantsEnabled": True,
                "standardFlowEnabled": False,
                "implicitFlowEnabled": False,
                "serviceAccountsEnabled": False,
                "protocolMappers": [
                    {
                        "name": "audience-mapper",
                        "protocol": "openid-connect",
                        "protocolMapper": "oidc-audience-mapper",
                        "consentRequired": False,
                        "config": {
                            "included.client.audience": CLIENT_ID,
                            "id.token.claim": "false",
                            "access.token.claim": "true",
                        },
                    }
                ],
            },
        )
        response.raise_for_status()
        location = response.headers["Location"]
        client_uuid = location.rstrip("/").rsplit("/", 1)[-1]
        print(f"created client {CLIENT_ID!r}")

    response = client.get(
        f"{KEYCLOAK_BASE_URL}/admin/realms/{REALM_NAME}/clients/{client_uuid}/client-secret",
        headers=headers,
    )
    response.raise_for_status()
    return response.json()["value"]


def ensure_spa_client(client: httpx.Client, headers: dict) -> None:
    """specs/071-search-frontend: a public client for the browser SPA — Authorization Code
    + PKCE, no client secret (public clients don't get one; PKCE replaces the secret's role
    in preventing authorization-code interception), no Direct Access Grants (browser-only,
    unlike CLIENT_ID's confidential test client)."""
    response = client.get(
        f"{KEYCLOAK_BASE_URL}/admin/realms/{REALM_NAME}/clients",
        headers=headers,
        params={"clientId": SPA_CLIENT_ID},
    )
    response.raise_for_status()
    existing = response.json()
    payload = {
        "clientId": SPA_CLIENT_ID,
        "enabled": True,
        "protocol": "openid-connect",
        "publicClient": True,
        "directAccessGrantsEnabled": False,
        "standardFlowEnabled": True,
        "implicitFlowEnabled": False,
        "serviceAccountsEnabled": False,
        "redirectUris": [f"{SPA_DEV_ORIGIN}/*"],
        "webOrigins": [SPA_DEV_ORIGIN],
        "attributes": {"pkce.code.challenge.method": "S256"},
    }
    # Without this, apps/api's JWT verification (packages/auth/jwt.py, which requires
    # `aud` to contain CLIENT_ID) rejects every token this client issues — confirmed live
    # (every apps/api call 401'd immediately after a fresh login, even though the token
    # itself was valid/unexpired) when this client was first created without it.
    audience_mapper = {
        "name": "audience-mapper",
        "protocol": "openid-connect",
        "protocolMapper": "oidc-audience-mapper",
        "consentRequired": False,
        "config": {
            "included.client.audience": CLIENT_ID,
            "id.token.claim": "false",
            "access.token.claim": "true",
        },
    }
    if existing:
        client_uuid = existing[0]["id"]
        response = client.put(
            f"{KEYCLOAK_BASE_URL}/admin/realms/{REALM_NAME}/clients/{client_uuid}",
            headers=headers,
            json={**existing[0], **payload},
        )
        response.raise_for_status()

        mappers_response = client.get(
            f"{KEYCLOAK_BASE_URL}/admin/realms/{REALM_NAME}/clients/{client_uuid}/protocol-mappers/models",
            headers=headers,
        )
        mappers_response.raise_for_status()
        if not any(m["name"] == "audience-mapper" for m in mappers_response.json()):
            create_mapper_response = client.post(
                f"{KEYCLOAK_BASE_URL}/admin/realms/{REALM_NAME}/clients/{client_uuid}/protocol-mappers/models",
                headers=headers,
                json=audience_mapper,
            )
            create_mapper_response.raise_for_status()
            print(f"added missing audience-mapper to {SPA_CLIENT_ID!r}")
        print(f"client {SPA_CLIENT_ID!r} already exists (settings confirmed)")
    else:
        payload["protocolMappers"] = [audience_mapper]
        response = client.post(
            f"{KEYCLOAK_BASE_URL}/admin/realms/{REALM_NAME}/clients",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        print(f"created client {SPA_CLIENT_ID!r}")


def ensure_test_user(client: httpx.Client, headers: dict, username: str, email: str, password: str) -> None:
    response = client.get(
        f"{KEYCLOAK_BASE_URL}/admin/realms/{REALM_NAME}/users",
        headers=headers,
        params={"username": username},
    )
    response.raise_for_status()
    existing = response.json()
    if existing:
        user_uuid = existing[0]["id"]
        print(f"user {username!r} already exists")
    else:
        response = client.post(
            f"{KEYCLOAK_BASE_URL}/admin/realms/{REALM_NAME}/users",
            headers=headers,
            json={
                "username": username,
                "email": email,
                "firstName": "Test",
                "lastName": "User",
                "enabled": True,
                "emailVerified": True,
            },
        )
        response.raise_for_status()
        location = response.headers["Location"]
        user_uuid = location.rstrip("/").rsplit("/", 1)[-1]
        print(f"created user {username!r}")

    response = client.put(
        f"{KEYCLOAK_BASE_URL}/admin/realms/{REALM_NAME}/users/{user_uuid}/reset-password",
        headers=headers,
        json={"type": "password", "value": password, "temporary": False},
    )
    response.raise_for_status()


def upsert_env_file(updates: dict[str, str]) -> None:
    env_path = REPO_ROOT / "infra" / ".env"
    lines = env_path.read_text().splitlines() if env_path.exists() else []
    keys_written = set()
    for i, line in enumerate(lines):
        if "=" not in line or line.strip().startswith("#"):
            continue
        key = line.split("=", 1)[0]
        if key in updates:
            lines[i] = f"{key}={updates[key]}"
            keys_written.add(key)
    for key, value in updates.items():
        if key not in keys_written:
            lines.append(f"{key}={value}")
    env_path.write_text("\n".join(lines) + "\n")
    print(f"updated {env_path}")


def main() -> None:
    settings = BootstrapSettings()
    with httpx.Client(timeout=10.0) as client:
        token = get_admin_token(client, settings)
        headers = {"Authorization": f"Bearer {token}"}

        ensure_realm(client, headers)
        client_secret = ensure_client(client, headers)
        ensure_spa_client(client, headers)
        for username, email, password in TEST_USERS:
            ensure_test_user(client, headers, username, email, password)

    env_updates = {
        "KEYCLOAK_ISSUER_URL": f"{KEYCLOAK_BASE_URL}/realms/{REALM_NAME}",
        "KEYCLOAK_AUDIENCE": CLIENT_ID,
        "KEYCLOAK_TEST_CLIENT_ID": CLIENT_ID,
        "KEYCLOAK_TEST_CLIENT_SECRET": client_secret,
    }
    for i, (username, _, password) in enumerate(TEST_USERS, start=1):
        suffix = "" if i == 1 else f"_{i}"
        env_updates[f"KEYCLOAK_TEST_USERNAME{suffix}"] = username
        env_updates[f"KEYCLOAK_TEST_PASSWORD{suffix}"] = password
    upsert_env_file(env_updates)
    print("done")


if __name__ == "__main__":
    try:
        main()
    except httpx.HTTPStatusError as exc:
        print(f"Keycloak API error: {exc.response.status_code} {exc.response.text}", file=sys.stderr)
        sys.exit(1)
