from packages.observability import RETRIEVAL_STAGE_DURATION, get_tracer
from packages.retrieval.dense import SearchResult

_tracer = get_tracer(__name__)


def reciprocal_rank_fusion(
    dense_results: list[SearchResult],
    sparse_results: list[SearchResult],
    rrf_k: int = 60,
) -> list[SearchResult]:
    """Merges two independently workspace-filtered ranked lists (dense.py::dense_search,
    sparse.py::sparse_search) by point_id, scoring each point Σ 1/(rrf_k + rank) over
    whichever list(s) it appears in (1-indexed rank), then sorting descending by that fused
    score. rrf_k=60 is the standard default from the original RRF paper and Qdrant's own
    examples — not tuned against this corpus (specs/040-hybrid-retrieval-reranking's
    non-goal; Phase 7 measures retrieval quality). Named rrf_k, not k, to avoid colliding
    with the unrelated "how many final results" parameter used throughout this package.

    Both input lists were already independently scoped by the mandatory workspace filter
    (build_workspace_filter) before this function ever sees them — fusion only reorders
    candidates both legs were already authorized to return, it does not add authorization.
    """
    with (
        _tracer.start_as_current_span("retrieval.fusion") as span,
        RETRIEVAL_STAGE_DURATION.labels(stage="fusion").time(),
    ):
        scores: dict[str, float] = {}
        results_by_id: dict[str, SearchResult] = {}

        for ranked_list in (dense_results, sparse_results):
            for rank, result in enumerate(ranked_list, start=1):
                scores[result.point_id] = scores.get(result.point_id, 0.0) + 1.0 / (rrf_k + rank)
                results_by_id.setdefault(result.point_id, result)

        ordered_ids = sorted(scores, key=lambda point_id: scores[point_id], reverse=True)
        span.set_attribute("fused_result_count", len(ordered_ids))
        return [results_by_id[point_id] for point_id in ordered_ids]
