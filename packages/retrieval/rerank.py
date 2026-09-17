from dataclasses import replace

from fastembed.rerank.cross_encoder import TextCrossEncoder

from packages.exceptions import RetrievalError
from packages.observability import RETRIEVAL_STAGE_DURATION, get_tracer
from packages.retrieval.dense import SearchResult

_tracer = get_tracer(__name__)


def rerank(
    query: str,
    candidates: list[SearchResult],
    cross_encoder: TextCrossEncoder,
    top_k: int = 8,
) -> list[SearchResult]:
    """Scores each fused candidate (fusion.py::reciprocal_rank_fusion) against the query with
    a cross-encoder and returns the top_k reordered by that score — the final stage of
    search.py's dense+sparse+RRF+rerank pipeline (specs/040-hybrid-retrieval-reranking).

    Replaces each returned result's .score with the reranker's score: the fused RRF score
    was only ever an internal ordering signal, not something callers of search() were ever
    contracted to see (030's API contract predates fusion entirely).
    """
    if not candidates:
        return []

    with (
        _tracer.start_as_current_span("retrieval.rerank") as span,
        RETRIEVAL_STAGE_DURATION.labels(stage="rerank").time(),
    ):
        span.set_attribute("candidate_count", len(candidates))
        span.set_attribute("top_k", top_k)
        try:
            scores = list(
                cross_encoder.rerank(query, [candidate.text or "" for candidate in candidates])
            )
        except Exception as exc:
            raise RetrievalError("reranking failed", original_exception=exc) from exc

        scored = sorted(zip(scores, candidates), key=lambda pair: pair[0], reverse=True)
        return [replace(candidate, score=score) for score, candidate in scored[:top_k]]
