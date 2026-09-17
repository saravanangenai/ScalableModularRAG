import uuid
from dataclasses import dataclass

from langchain_openai import OpenAIEmbeddings
from qdrant_client import QdrantClient

from packages.exceptions import RetrievalError
from packages.observability import RETRIEVAL_STAGE_DURATION, get_tracer
from packages.retrieval.filters import build_workspace_filter

_tracer = get_tracer(__name__)


@dataclass
class SearchResult:
    point_id: str
    document_id: uuid.UUID
    document_version_id: uuid.UUID
    filename: str
    content_type: str | None
    page_number: int | None
    chunk_index: int | None
    table_index: int | None
    image_index: int | None
    image_path: str | None
    text: str | None
    score: float


def map_points_to_results(points) -> list[SearchResult]:
    """Shared by dense_search and sparse.py::sparse_search — both query the same collection
    and payload shape, differing only in which vector they search against."""
    results: list[SearchResult] = []
    for point in points:
        payload = point.payload or {}
        results.append(
            SearchResult(
                point_id=str(point.id),
                document_id=uuid.UUID(payload["document_id"]),
                document_version_id=uuid.UUID(payload["document_version_id"]),
                filename=payload.get("filename"),
                content_type=payload.get("content_type"),
                page_number=payload.get("page_number"),
                chunk_index=payload.get("chunk_index"),
                table_index=payload.get("table_index"),
                image_index=payload.get("image_index"),
                image_path=payload.get("image_path"),
                text=payload.get("text"),
                score=point.score,
            )
        )
    return results


def dense_search(
    *,
    qdrant_client: QdrantClient,
    embeddings: OpenAIEmbeddings,
    collection_name: str,
    workspace_id: uuid.UUID,
    query: str,
    k: int = 8,
) -> list[SearchResult]:
    """The dense leg of hybrid search, scoped by the mandatory server-constructed workspace
    filter (build_workspace_filter). Combined with the sparse leg (sparse.py) via RRF fusion
    (fusion.py) and reranked (rerank.py) in search.py — specs/040-hybrid-retrieval-reranking.
    workspace_id is never accepted from request input by any caller of this function
    (specs/030-workspace-rbac-filtering/plan.md's API contract) — it is the caller's job to
    resolve it from an authorized source (apps/api/deps/rbac.py) first.
    """
    with (
        _tracer.start_as_current_span("retrieval.dense_search") as span,
        RETRIEVAL_STAGE_DURATION.labels(stage="dense_search").time(),
    ):
        span.set_attribute("workspace_id", str(workspace_id))
        span.set_attribute("k", k)
        try:
            vector = embeddings.embed_query(query)
            response = qdrant_client.query_points(
                collection_name=collection_name,
                query=vector,
                query_filter=build_workspace_filter(workspace_id),
                limit=k,
            )
        except Exception as exc:
            raise RetrievalError("dense search failed", original_exception=exc) from exc

        return map_points_to_results(response.points)
