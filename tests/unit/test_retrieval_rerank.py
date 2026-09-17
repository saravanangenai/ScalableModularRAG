import uuid
from unittest.mock import MagicMock

import pytest

from packages.exceptions import RetrievalError
from packages.retrieval.dense import SearchResult
from packages.retrieval.rerank import rerank


def _result(point_id: str, text: str = "text", score: float = 0.0) -> SearchResult:
    return SearchResult(
        point_id=point_id,
        document_id=uuid.uuid4(),
        document_version_id=uuid.uuid4(),
        filename="contract.pdf",
        content_type="page_text_plus_ocr",
        page_number=1,
        chunk_index=0,
        table_index=None,
        image_index=None,
        image_path=None,
        text=text,
        score=score,
    )


def test_rerank_reorders_by_cross_encoder_score():
    a, b, c = _result("a", score=0.9), _result("b", score=0.1), _result("c", score=0.5)
    cross_encoder = MagicMock()
    # Input order [a, b, c] -> cross-encoder scores b highest, then c, then a.
    cross_encoder.rerank.return_value = [0.2, 0.9, 0.5]

    results = rerank("query", [a, b, c], cross_encoder, top_k=8)

    assert [r.point_id for r in results] == ["b", "c", "a"]


def test_rerank_replaces_score_with_reranker_score_not_the_fused_score():
    a = _result("a", score=0.9)
    cross_encoder = MagicMock()
    cross_encoder.rerank.return_value = [0.42]

    results = rerank("query", [a], cross_encoder, top_k=8)

    assert results[0].score == 0.42


def test_rerank_truncates_to_top_k():
    candidates = [_result(str(i)) for i in range(5)]
    cross_encoder = MagicMock()
    cross_encoder.rerank.return_value = [float(i) for i in range(5)]

    results = rerank("query", candidates, cross_encoder, top_k=2)

    assert len(results) == 2
    assert [r.point_id for r in results] == ["4", "3"]


def test_rerank_passes_candidate_text_to_the_cross_encoder():
    a, b = _result("a", text="alpha"), _result("b", text="beta")
    cross_encoder = MagicMock()
    cross_encoder.rerank.return_value = [0.1, 0.2]

    rerank("query", [a, b], cross_encoder, top_k=8)

    cross_encoder.rerank.assert_called_once_with("query", ["alpha", "beta"])


def test_rerank_handles_none_text_without_crashing():
    a = _result("a", text=None)
    cross_encoder = MagicMock()
    cross_encoder.rerank.return_value = [0.1]

    rerank("query", [a], cross_encoder, top_k=8)

    cross_encoder.rerank.assert_called_once_with("query", [""])


def test_rerank_returns_empty_list_for_no_candidates():
    cross_encoder = MagicMock()
    assert rerank("query", [], cross_encoder, top_k=8) == []
    cross_encoder.rerank.assert_not_called()


def test_rerank_wraps_cross_encoder_failures():
    a = _result("a")
    cross_encoder = MagicMock()
    cross_encoder.rerank.side_effect = RuntimeError("model error")

    with pytest.raises(RetrievalError):
        rerank("query", [a], cross_encoder, top_k=8)
