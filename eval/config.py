from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="infra/.env", extra="ignore")

    # Same Keycloak test-identity env vars tests/integration/conftest.py::KeycloakTestSettings
    # reads — reused rather than provisioning a separate eval service account
    # (specs/060-retrieval-evaluation/plan.md's Alternatives).
    keycloak_issuer_url: str
    keycloak_test_client_id: str
    keycloak_test_client_secret: str
    keycloak_test_username: str
    keycloak_test_password: str

    eval_workspace_name: str = "eval"
    eval_fixture_path: str = "tests/fixtures/sample.pdf"
