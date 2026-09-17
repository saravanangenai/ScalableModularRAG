import uuid
from functools import lru_cache

from fastembed import SparseTextEmbedding
from fastembed.rerank.cross_encoder import TextCrossEncoder
from langchain_openai import OpenAIEmbeddings
from qdrant_client import QdrantClient

from packages.retrieval.config import Settings
from packages.retrieval.dense import SearchResult, dense_search
from packages.retrieval.fusion import reciprocal_rank_fusion
from packages.retrieval.rerank import rerank
from packages.retrieval.sparse import sparse_search

# How many candidates each leg pulls before fusion — per specs/architecture/
# 04-retrieval-design.md's target pipeline ("top N=~30" per leg). Not the same as k, the
# caller's requested *final* result count.
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


def search(workspace_id: uuid.UUID, query: str, k: int = 8) -> list[SearchResult]:
    """Public entry point apps/api/routers/search.py calls. Dense + sparse legs each pull
    _CANDIDATE_POOL_SIZE candidates (independently workspace-filtered — build_workspace_filter
    applies to both, unchanged from 030), Reciprocal Rank Fusion merges them, a cross-encoder
    reranks the fused set, and the top k comes back. specs/040-hybrid-retrieval-reranking.

    All model/client instances are module-cached (built once, on first call, not per
    request) — each holds its own HTTP connection pool or loaded model weights.
    """
    settings = _settings()

    dense_results = dense_search(
        qdrant_client=_qdrant_client(),
        embeddings=_embeddings(),
        collection_name=settings.qdrant_collection_name,
        workspace_id=workspace_id,
        query=query,
        k=_CANDIDATE_POOL_SIZE,
    )
    sparse_results = sparse_search(
        qdrant_client=_qdrant_client(),
        sparse_model=_sparse_model(),
        collection_name=settings.qdrant_collection_name,
        workspace_id=workspace_id,
        query=query,
        k=_CANDIDATE_POOL_SIZE,
    )

    fused = reciprocal_rank_fusion(dense_results, sparse_results)
    return rerank(query, fused, _cross_encoder(), top_k=k)
