from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="infra/.env", extra="ignore")

    s3_endpoint_url: str
    s3_bucket: str
    minio_root_user: str
    minio_root_password: str
