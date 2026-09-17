from packages.retrieval.config import Settings


def test_defaults_match_ingestion_settings():
    """packages/retrieval and packages/ingestion embed with the same model/collection so a
    query vector is comparable to the vectors written at ingest time
    (packages/ingestion/pipeline.py)."""
    settings = Settings(qdrant_url="http://localhost:6333", openai_api_key="k", _env_file=None)

    assert settings.qdrant_collection_name == "mm_rag_v1"
    assert settings.openai_embedding_model == "text-embedding-3-large"
    assert settings.openai_embedding_dimension == 3072
    assert settings.sparse_embedding_model == "Qdrant/bm25"
    assert settings.reranker_model == "Xenova/ms-marco-MiniLM-L-6-v2"


def test_qdrant_api_key_optional():
    settings = Settings(qdrant_url="http://localhost:6333", openai_api_key="k", _env_file=None)
    assert settings.qdrant_api_key is None
