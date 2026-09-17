import uuid
from functools import lru_cache

from fastembed import SparseTextEmbedding
from fastembed.rerank.cross_encoder import TextCrossEncoder
from langchain_openai import OpenAIEmbeddings
from qdrant_client import QdrantClient

from packages.exceptions import EvalError
from packages.retrieval.config import Settings
from packages.retrieval.dense import SearchResult, dense_search
from packages.retrieval.fusion import reciprocal_rank_fusion
from packages.retrieval.rerank import rerank
from packages.retrieval.sparse import sparse_search

_CANDIDATE_POOL_SIZE = 30


@lru_cache(maxsize=1)
def _settings() -> Settings:
    return Settings()


@lru_cache(maxsize=1)
def _qdrant_client() -> QdrantClient:
    settings = _settings()
    return QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key or None)


@lru_cache(maxsize=1)
def _embeddings() -> OpenAIEmbeddings:
    settings = _settings()
    return OpenAIEmbeddings(
        model=settings.openai_embedding_model,
        dimensions=settings.openai_embedding_dimension,
        api_key=settings.openai_api_key,
    )


@lru_cache(maxsize=1)
def _sparse_model() -> SparseTextEmbedding:
    return SparseTextEmbedding(model_name=_settings().sparse_embedding_model)


@lru_cache(maxsize=1)
def _cross_encoder() -> TextCrossEncoder:
    return TextCrossEncoder(model_name=_settings().reranker_model)


def run_search(
    workspace_id: uuid.UUID,
    query: str,
    k: int = 8,
    *,
    use_sparse: bool = True,
    use_rerank: bool = True,
) -> list[SearchResult]:
    """Configurable retrieval-pipeline composition for comparing configs
    (specs/060-retrieval-evaluation) — calls packages/retrieval's same public functions
    production packages.retrieval.search.search() does, just with use_sparse/use_rerank
    choosing which legs run. Deliberately does NOT import search()'s private cached client
    getters: builds its own from packages/retrieval/config.py::Settings (already public),
    so zero lines of packages/retrieval are touched by this spec, per plan.md's constraint.
    """
    try:
        settings = _settings()

        dense_results = dense_search(
            qdrant_client=_qdrant_client(),
            embeddings=_embeddings(),
            collection_name=settings.qdrant_collection_name,
            workspace_id=workspace_id,
            query=query,
            k=_CANDIDATE_POOL_SIZE,
        )

        if use_sparse:
            sparse_results = sparse_search(
                qdrant_client=_qdrant_client(),
                sparse_model=_sparse_model(),
                collection_name=settings.qdrant_collection_name,
                workspace_id=workspace_id,
                query=query,
                k=_CANDIDATE_POOL_SIZE,
            )
            candidates = reciprocal_rank_fusion(dense_results, sparse_results)
        else:
            candidates = dense_results

        if use_rerank:
            return rerank(query, candidates, _cross_encoder(), top_k=k)
        return candidates[:k]
    except Exception as exc:
        raise EvalError("configured retrieval run failed", original_exception=exc) from exc
