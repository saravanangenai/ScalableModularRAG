from packages.auth.config import Settings


def test_settings_reads_explicit_values():
    settings = Settings(
        keycloak_issuer_url="http://localhost:8080/realms/mm-rag",
        keycloak_audience="mm-rag-api",
        _env_file=None,
    )

    assert settings.keycloak_issuer_url == "http://localhost:8080/realms/mm-rag"
    assert settings.keycloak_audience == "mm-rag-api"
