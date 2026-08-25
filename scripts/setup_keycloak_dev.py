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


def ensure_realm(client: httpx.Client, headers: dict) -> None:
    response = client.get(f"{KEYCLOAK_BASE_URL}/admin/realms/{REALM_NAME}", headers=headers)
    if response.status_code == 200:
        print(f"realm {REALM_NAME!r} already exists")
        return
    response = client.post(
        f"{KEYCLOAK_BASE_URL}/admin/realms",
        headers=headers,
        json={"realm": REALM_NAME, "enabled": True},
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
