from dataclasses import dataclass

from eval.dataset import EvalCase
from eval.metrics import CaseResult, aggregate, hit_at_k, reciprocal_rank


@dataclass
class _FakeResult:
    filename: str | None
    page_number: int | None
    content_type: str | None
    table_index: int | None = None
    image_index: int | None = None


def _case(**overrides) -> EvalCase:
    base = dict(
        id="Q-001",
        question="q",
        expected_filename="sample.pdf",
        expected_page_number=5,
        expected_content_type="table",
        expected_table_index=1,
        expected_image_index=None,
    )
    base.update(overrides)
    return EvalCase(**base)


def _matching_result(**overrides) -> _FakeResult:
    base = dict(filename="sample.pdf", page_number=5, content_type="table", table_index=1)
    base.update(overrides)
    return _FakeResult(**base)


def test_hit_at_k_true_when_expected_source_present():
    case = _case()
    results = [_FakeResult("other.pdf", 1, "table"), _matching_result()]
    assert hit_at_k(case, results) is True


def test_hit_at_k_false_when_absent():
    case = _case()
    results = [_FakeResult("other.pdf", 1, "table")]
    assert hit_at_k(case, results) is False


def test_hit_at_k_requires_table_index_match_when_specified():
    case = _case(expected_table_index=2)
    results = [_matching_result(table_index=1)]  # right page, wrong table
    assert hit_at_k(case, results) is False


def test_hit_at_k_image_case_requires_image_index_match():
    case = _case(
        expected_page_number=24,
        expected_content_type="image",
        expected_table_index=None,
        expected_image_index=1,
    )
    results = [_FakeResult("sample.pdf", 24, "image", image_index=2)]
    assert hit_at_k(case, results) is False
    results_correct = [_FakeResult("sample.pdf", 24, "image", image_index=1)]
    assert hit_at_k(case, results_correct) is True


def test_reciprocal_rank_at_rank_one():
    case = _case()
    results = [_matching_result()]
    assert reciprocal_rank(case, results) == 1.0


def test_reciprocal_rank_at_rank_three():
    case = _case()
    results = [
        _FakeResult("other.pdf", 1, "table"),
        _FakeResult("other.pdf", 2, "table"),
        _matching_result(),
    ]
    assert reciprocal_rank(case, results) == 1.0 / 3


def test_reciprocal_rank_zero_when_no_match():
    case = _case()
    results = [_FakeResult("other.pdf", 1, "table")]
    assert reciprocal_rank(case, results) == 0.0


def test_aggregate_hand_computed():
    # Case A: hit at k=8 -> precision contribution 1/8, rr=1.0 (rank 1)
    # Case B: miss -> precision contribution 0, rr=0.0
    # Case C: hit at k=8 -> precision contribution 1/8, rr=0.5 (rank 2)
    case_results = [
        CaseResult(case_id="A", hit=True, reciprocal_rank=1.0, k=8, latency_ms=100.0),
        CaseResult(case_id="B", hit=False, reciprocal_rank=0.0, k=8, latency_ms=200.0),
        CaseResult(case_id="C", hit=True, reciprocal_rank=0.5, k=8, latency_ms=300.0),
    ]

    result = aggregate(case_results)

    assert result["case_count"] == 3
    assert result["recall_at_k"] == 2 / 3
    assert result["precision_at_k"] == (1 / 8 + 0 + 1 / 8) / 3
    assert result["mean_reciprocal_rank"] == (1.0 + 0.0 + 0.5) / 3
    assert result["latency_p50_ms"] == 200.0


def test_aggregate_empty_case_list():
    result = aggregate([])
    assert result["case_count"] == 0
    assert result["recall_at_k"] == 0.0
