from packages.ingestion.config import Settings


def _settings(**overrides) -> Settings:
    base = dict(
        qdrant_url="http://localhost:6333",
        openai_api_key="k",
        celery_broker_url="redis://localhost:6379/0",
        celery_result_backend="redis://localhost:6379/0",
        _env_file=None,
    )
    base.update(overrides)
    return Settings(**base)


def test_defaults():
    settings = _settings()
    assert settings.qdrant_collection_name == "mm_rag_v1"
    assert settings.openai_embedding_model == "text-embedding-3-large"
    assert settings.openai_embedding_dimension == 3072
    assert settings.sparse_embedding_model == "Qdrant/bm25"
    assert settings.openai_vision_model == "gpt-4.1-mini"
    assert settings.table_chunk_row_threshold == 20
    assert settings.table_chunk_group_size == 15


def test_qdrant_api_key_optional():
    settings = _settings()
    assert settings.qdrant_api_key is None
