from packages.observability.config import Settings


def test_defaults():
    settings = Settings(_env_file=None)

    assert settings.otel_exporter_endpoint == "http://localhost:4318"
    assert settings.sentry_dsn is None
    assert settings.environment == "local"
