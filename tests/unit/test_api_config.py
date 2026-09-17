from apps.api.config import Settings


def test_defaults():
    settings = Settings(_env_file=None)

    assert settings.cors_allowed_origins == ["http://localhost:5173"]
    assert settings.redis_url == "redis://localhost:6379/0"
    assert settings.rate_limit_search_per_minute == 30
    assert settings.rate_limit_upload_per_minute == 30


def test_parses_comma_separated_origins_from_env_string():
    settings = Settings(
        cors_allowed_origins="https://a.example.com, https://b.example.com",
        _env_file=None,
    )

    assert settings.cors_allowed_origins == ["https://a.example.com", "https://b.example.com"]
