from eval.config import Settings


def _settings(**overrides) -> Settings:
    base = dict(
        keycloak_issuer_url="http://localhost:8080/realms/mm-rag",
        keycloak_test_client_id="client",
        keycloak_test_client_secret="secret",
        keycloak_test_username="testuser",
        keycloak_test_password="password",
        _env_file=None,
    )
    base.update(overrides)
    return Settings(**base)


def test_defaults():
    settings = _settings()
    assert settings.eval_workspace_name == "eval"
    assert settings.eval_fixture_path == "tests/fixtures/sample.pdf"
