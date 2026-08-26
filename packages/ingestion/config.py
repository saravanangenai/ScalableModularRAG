from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="infra/.env", extra="ignore")

    qdrant_url: str
    qdrant_api_key: str | None = None
    qdrant_collection_name: str = "mm_rag_v1"

    openai_api_key: str
    openai_embedding_model: str = "text-embedding-3-large"
    openai_embedding_dimension: int = 3072

    celery_broker_url: str
    celery_result_backend: str
