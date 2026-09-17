import uuid

from fastembed import SparseTextEmbedding
from qdrant_client import QdrantClient, models

from packages.exceptions import RetrievalError
from packages.observability import RETRIEVAL_STAGE_DURATION, get_tracer
from packages.retrieval.dense import SearchResult, map_points_to_results
from packages.retrieval.filters import build_workspace_filter

SPARSE_VECTOR_NAME = "sparse"

_tracer = get_tracer(__name__)


def sparse_search(
    *,
    qdrant_client: QdrantClient,
    sparse_model: SparseTextEmbedding,
    collection_name: str,
    workspace_id: uuid.UUID,
    query: str,
    k: int = 8,
) -> list[SearchResult]:
    """The sparse (BM25) leg of hybrid search, mirroring dense.py::dense_search — same
    mandatory workspace filter, same error wrapping, same SearchResult mapping. Combined
    with the dense leg via RRF fusion (fusion.py) and reranked (rerank.py) in search.py —
    specs/040-hybrid-retrieval-reranking. .query_embed() (not .embed()) matches how the
    sparse leg embeds chunks at ingest time (packages/ingestion/pipeline.py).
    """
    with (
        _tracer.start_as_current_span("retrieval.sparse_search") as span,
        RETRIEVAL_STAGE_DURATION.labels(stage="sparse_search").time(),
    ):
        span.set_attribute("workspace_id", str(workspace_id))
        span.set_attribute("k", k)
        try:
            sparse_embedding = next(iter(sparse_model.query_embed(query)))
            response = qdrant_client.query_points(
                collection_name=collection_name,
                query=models.SparseVector(
                    indices=sparse_embedding.indices.tolist(),
                    values=sparse_embedding.values.tolist(),
                ),
                using=SPARSE_VECTOR_NAME,
                query_filter=build_workspace_filter(workspace_id),
                limit=k,
            )
        except Exception as exc:
            raise RetrievalError("sparse search failed", original_exception=exc) from exc

        return map_points_to_results(response.points)
