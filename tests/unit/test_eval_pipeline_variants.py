import uuid
from unittest.mock import MagicMock

import pytest

import eval.pipeline_variants as pv
from packages.exceptions import EvalError


@pytest.fixture(autouse=True)
def _patched_clients(monkeypatch):
    """Avoid constructing real Qdrant/OpenAI/FastEmbed clients — this module's lru_cache'd
    getters would otherwise try to build real ones on first call. Fixed instances (not a
    lambda creating a fresh MagicMock per call) so a test asserting rerank was called with
    "the cross encoder" compares against the same object run_search actually used."""
    qdrant_client, embeddings, sparse_model, cross_encoder = (
        MagicMock(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
    )
    monkeypatch.setattr(pv, "_qdrant_client", lambda: qdrant_client)
    monkeypatch.setattr(pv, "_embeddings", lambda: embeddings)
    monkeypatch.setattr(pv, "_sparse_model", lambda: sparse_model)
    monkeypatch.setattr(pv, "_cross_encoder", lambda: cross_encoder)
    settings = MagicMock(qdrant_collection_name="mm_rag_v1")
    monkeypatch.setattr(pv, "_settings", lambda: settings)
    return {"cross_encoder": cross_encoder}


def test_run_search_calls_all_four_legs_by_default(monkeypatch):
    dense_search = MagicMock(return_value=["dense-result"])
    sparse_search = MagicMock(return_value=["sparse-result"])
    fusion = MagicMock(return_value=["fused-result"])
    rerank = MagicMock(return_value=["reranked-result"])
    monkeypatch.setattr(pv, "dense_search", dense_search)
    monkeypatch.setattr(pv, "sparse_search", sparse_search)
    monkeypatch.setattr(pv, "reciprocal_rank_fusion", fusion)
    monkeypatch.setattr(pv, "rerank", rerank)

    result = pv.run_search(uuid.uuid4(), "query", k=8)

    dense_search.assert_called_once()
    sparse_search.assert_called_once()
    fusion.assert_called_once_with(["dense-result"], ["sparse-result"])
    rerank.assert_called_once()
    assert result == ["reranked-result"]


def test_run_search_skips_sparse_and_fusion_when_use_sparse_false(monkeypatch, _patched_clients):
    dense_search = MagicMock(return_value=["dense-result"])
    sparse_search = MagicMock()
    fusion = MagicMock()
    rerank = MagicMock(return_value=["reranked-result"])
    monkeypatch.setattr(pv, "dense_search", dense_search)
    monkeypatch.setattr(pv, "sparse_search", sparse_search)
    monkeypatch.setattr(pv, "reciprocal_rank_fusion", fusion)
    monkeypatch.setattr(pv, "rerank", rerank)

    pv.run_search(uuid.uuid4(), "query", k=8, use_sparse=False)

    sparse_search.assert_not_called()
    fusion.assert_not_called()
    rerank.assert_called_once_with(
        "query", ["dense-result"], _patched_clients["cross_encoder"], top_k=8
    )


def test_run_search_skips_rerank_and_truncates_to_k_when_use_rerank_false(monkeypatch):
    dense_search = MagicMock(return_value=["dense-result"])
    sparse_search = MagicMock(return_value=["sparse-result"])
    fusion = MagicMock(return_value=["a", "b", "c", "d"])
    rerank = MagicMock()
    monkeypatch.setattr(pv, "dense_search", dense_search)
    monkeypatch.setattr(pv, "sparse_search", sparse_search)
    monkeypatch.setattr(pv, "reciprocal_rank_fusion", fusion)
    monkeypatch.setattr(pv, "rerank", rerank)

    result = pv.run_search(uuid.uuid4(), "query", k=2, use_rerank=False)

    rerank.assert_not_called()
    assert result == ["a", "b"]


def test_run_search_no_sparse_no_rerank_just_truncates_dense(monkeypatch):
    dense_search = MagicMock(return_value=["a", "b", "c"])
    sparse_search = MagicMock()
    fusion = MagicMock()
    rerank = MagicMock()
    monkeypatch.setattr(pv, "dense_search", dense_search)
    monkeypatch.setattr(pv, "sparse_search", sparse_search)
    monkeypatch.setattr(pv, "reciprocal_rank_fusion", fusion)
    monkeypatch.setattr(pv, "rerank", rerank)

    result = pv.run_search(uuid.uuid4(), "query", k=2, use_sparse=False, use_rerank=False)

    sparse_search.assert_not_called()
    fusion.assert_not_called()
    rerank.assert_not_called()
    assert result == ["a", "b"]


def test_run_search_wraps_failures(monkeypatch):
    monkeypatch.setattr(pv, "dense_search", MagicMock(side_effect=RuntimeError("boom")))

    with pytest.raises(EvalError):
        pv.run_search(uuid.uuid4(), "query")
