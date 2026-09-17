import uuid

from packages.retrieval.dense import SearchResult
from packages.retrieval.fusion import reciprocal_rank_fusion


def _result(point_id: str, score: float = 0.0) -> SearchResult:
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
        text="text",
        score=score,
    )


def test_reciprocal_rank_fusion_hand_computed_scores():
    a, b, c, d = _result("a"), _result("b"), _result("c"), _result("d")
    dense_results = [a, b, c]  # ranks 1, 2, 3
    sparse_results = [b, d]  # ranks 1, 2

    fused = reciprocal_rank_fusion(dense_results, sparse_results, rrf_k=60)

    # b: 1/62 (dense rank 2) + 1/61 (sparse rank 1) = 0.032522...
    # a: 1/61 (dense rank 1 only)                    = 0.016393...
    # d: 1/62 (sparse rank 2 only)                    = 0.016129...
    # c: 1/63 (dense rank 3 only)                     = 0.015873...
    assert [r.point_id for r in fused] == ["b", "a", "d", "c"]


def test_reciprocal_rank_fusion_point_in_both_lists_outranks_single_list_points():
    """A point appearing in both lists, even at worse individual ranks, can still beat a
    point that only appears once at rank 1 — the core reason fusion exists."""
    shared = _result("shared")
    only_dense = _result("only-dense")
    only_sparse = _result("only-sparse")

    dense_results = [only_dense, shared]  # shared at rank 2
    sparse_results = [only_sparse, shared]  # shared at rank 2

    fused = reciprocal_rank_fusion(dense_results, sparse_results, rrf_k=60)

    assert fused[0].point_id == "shared"


def test_reciprocal_rank_fusion_dedupes_by_point_id():
    shared = _result("shared")
    fused = reciprocal_rank_fusion([shared], [shared], rrf_k=60)

    assert len(fused) == 1
    assert fused[0].point_id == "shared"


def test_reciprocal_rank_fusion_preserves_the_original_search_result_object():
    """Fusion only reorders — it does not overwrite .score (rerank.py does that later)."""
    result = _result("a", score=0.42)

    fused = reciprocal_rank_fusion([result], [], rrf_k=60)

    assert fused[0] is result
    assert fused[0].score == 0.42


def test_reciprocal_rank_fusion_handles_empty_lists():
    assert reciprocal_rank_fusion([], [], rrf_k=60) == []

    a = _result("a")
    assert reciprocal_rank_fusion([a], [], rrf_k=60) == [a]
    assert reciprocal_rank_fusion([], [a], rrf_k=60) == [a]
