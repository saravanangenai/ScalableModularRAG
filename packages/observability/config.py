from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="infra/.env", extra="ignore")

    otel_exporter_endpoint: str = "http://localhost:4318"
    sentry_dsn: str | None = None
    environment: str = "local"
