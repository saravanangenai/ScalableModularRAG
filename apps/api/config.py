from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="infra/.env", extra="ignore")

    cors_allowed_origins: list[str] = ["http://localhost:5173"]
    redis_url: str = "redis://localhost:6379/0"
    rate_limit_search_per_minute: int = 30
    rate_limit_upload_per_minute: int = 30

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def _parse_comma_separated(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value
