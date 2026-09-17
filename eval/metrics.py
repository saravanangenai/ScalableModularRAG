from dataclasses import dataclass
from typing import Protocol

from eval.dataset import EvalCase


class _Result(Protocol):
    """Structural match for packages.retrieval.dense.SearchResult — eval doesn't import it
    directly so this module stays testable with plain fakes, no packages/retrieval
    dependency for unit tests."""

    filename: str | None
    page_number: int | None
    content_type: str | None
    table_index: int | None
    image_index: int | None


@dataclass
class CaseResult:
    case_id: str
    hit: bool
    reciprocal_rank: float
    k: int
    latency_ms: float


def _matches(case: EvalCase, result: _Result) -> bool:
    if result.filename != case.expected_filename:
        return False
    if result.page_number != case.expected_page_number:
        return False
    if result.content_type != case.expected_content_type:
        return False
    if case.expected_table_index is not None and result.table_index != case.expected_table_index:
        return False
    if case.expected_image_index is not None and result.image_index != case.expected_image_index:
        return False
    return True


def hit_at_k(case: EvalCase, results: list[_Result]) -> bool:
    """Did a result matching case's expected source appear anywhere in the returned top-k."""
    return any(_matches(case, result) for result in results)


def reciprocal_rank(case: EvalCase, results: list[_Result]) -> float:
    """1/rank of the first matching result (1-indexed), 0.0 if none match. Informational —
    not promoted to a primary aggregate metric in this increment (specs/060-retrieval-
    evaluation/plan.md's Alternatives — recall@k/precision@k are what the spec commits to)."""
    for rank, result in enumerate(results, start=1):
        if _matches(case, result):
            return 1.0 / rank
    return 0.0


def _percentile(sorted_values: list[float], fraction: float) -> float:
    if not sorted_values:
        return 0.0
    index = min(len(sorted_values) - 1, int(len(sorted_values) * fraction))
    return sorted_values[index]


def aggregate(case_results: list[CaseResult]) -> dict:
    """recall@k = mean hit rate. precision@k = mean of (1/k if hit else 0) per case — with
    exactly one relevant item per question, this is a degenerate/low-information form of
    precision@k, reported anyway per specs/060-retrieval-evaluation/spec.md's Goals, labeled
    here rather than silently presented as a richer metric than the dataset shape supports.
    """
    if not case_results:
        return {
            "case_count": 0,
            "recall_at_k": 0.0,
            "precision_at_k": 0.0,
            "precision_at_k_note": "degenerate: one relevant item per case",
            "mean_reciprocal_rank": 0.0,
            "latency_p50_ms": 0.0,
            "latency_p95_ms": 0.0,
        }

    n = len(case_results)
    latencies = sorted(r.latency_ms for r in case_results)

    return {
        "case_count": n,
        "recall_at_k": sum(1 for r in case_results if r.hit) / n,
        "precision_at_k": sum((1.0 / r.k) for r in case_results if r.hit) / n,
        "precision_at_k_note": "degenerate: one relevant item per case",
        "mean_reciprocal_rank": sum(r.reciprocal_rank for r in case_results) / n,
        "latency_p50_ms": _percentile(latencies, 0.50),
        "latency_p95_ms": _percentile(latencies, 0.95),
    }
