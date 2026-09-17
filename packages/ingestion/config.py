from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="infra/.env", extra="ignore")

    qdrant_url: str
    qdrant_api_key: str | None = None
    qdrant_collection_name: str = "mm_rag_v1"

    openai_api_key: str
    openai_embedding_model: str = "text-embedding-3-large"
    openai_embedding_dimension: int = 3072

    # Must match packages/retrieval/config.py's value — ingestion embeds chunks, retrieval
    # embeds queries, and the two vectors are only comparable if they're the same model.
    sparse_embedding_model: str = "Qdrant/bm25"

    # Vision captioning (specs/050-vision-captioning) and table summarization
    # (specs/051-table-intelligence) — ingestion-only, no retrieval-side counterpart needed
    # since both only ever run at ingest time, never on the query path.
    openai_vision_model: str = "gpt-4.1-mini"

    # Table row-group chunking (specs/051-table-intelligence) — tables at or below the
    # threshold stay one chunk; larger ones split into group_size-row chunks.
    table_chunk_row_threshold: int = 20
    table_chunk_group_size: int = 15

    celery_broker_url: str
    celery_result_backend: str
