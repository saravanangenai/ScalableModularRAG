from packages.db.config import Settings


def _settings(**overrides) -> Settings:
    base = dict(
        postgres_user="mmrag",
        postgres_password="secret",
        postgres_db="mmrag",
        postgres_host="db-host",
        postgres_port=5433,
        _env_file=None,
    )
    base.update(overrides)
    return Settings(**base)


def test_sync_database_url_uses_psycopg_driver():
    settings = _settings()
    assert settings.sync_database_url == (
        "postgresql+psycopg://mmrag:secret@db-host:5433/mmrag"
    )


def test_async_database_url_uses_asyncpg_driver():
    settings = _settings()
    assert settings.async_database_url == (
        "postgresql+asyncpg://mmrag:secret@db-host:5433/mmrag"
    )


def test_default_host_and_port():
    settings = Settings(
        postgres_user="u", postgres_password="p", postgres_db="d", _env_file=None
    )
    assert settings.postgres_host == "localhost"
    assert settings.postgres_port == 5432
