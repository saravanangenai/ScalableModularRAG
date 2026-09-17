import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from qdrant_client import models

from packages.exceptions import RetrievalError
from packages.retrieval.filters import build_workspace_filter
from packages.retrieval.sparse import SPARSE_VECTOR_NAME, sparse_search


def _fake_point(**payload_overrides):
    document_id = uuid.uuid4()
    document_version_id = uuid.uuid4()
    payload = {
        "document_id": str(document_id),
        "document_version_id": str(document_version_id),
        "filename": "contract.pdf",
        "content_type": "page_text_plus_ocr",
        "page_number": 3,
        "chunk_index": 1,
        "table_index": None,
        "image_index": None,
        "image_path": None,
        "text": "clause 14.2 says...",
        **payload_overrides,
    }
    point = SimpleNamespace(id=str(uuid.uuid4()), payload=payload, score=1.7)
    return point, document_id, document_version_id


def _fake_sparse_embedding():
    return SimpleNamespace(
        indices=SimpleNamespace(tolist=lambda: [1, 2, 3]),
        values=SimpleNamespace(tolist=lambda: [0.5, 0.4, 0.3]),
    )


def test_sparse_search_queries_the_named_sparse_vector_with_the_mandatory_filter():
    workspace_id = uuid.uuid4()
    point, _, _ = _fake_point()
    qdrant_client = MagicMock()
    qdrant_client.query_points.return_value = SimpleNamespace(points=[point])
    sparse_model = MagicMock()
    sparse_model.query_embed.return_value = [_fake_sparse_embedding()]

    sparse_search(
        qdrant_client=qdrant_client,
        sparse_model=sparse_model,
        collection_name="mm_rag_v1",
        workspace_id=workspace_id,
        query="clause 14.2",
        k=8,
    )

    sparse_model.query_embed.assert_called_once_with("clause 14.2")
    _, call_kwargs = qdrant_client.query_points.call_args
    assert call_kwargs["using"] == SPARSE_VECTOR_NAME
    assert call_kwargs["query"] == models.SparseVector(indices=[1, 2, 3], values=[0.5, 0.4, 0.3])
    assert call_kwargs["query_filter"] == build_workspace_filter(workspace_id)
    assert call_kwargs["limit"] == 8


def test_sparse_search_maps_qdrant_points_to_search_results():
    point, document_id, document_version_id = _fake_point()
    qdrant_client = MagicMock()
    qdrant_client.query_points.return_value = SimpleNamespace(points=[point])
    sparse_model = MagicMock()
    sparse_model.query_embed.return_value = [_fake_sparse_embedding()]

    results = sparse_search(
        qdrant_client=qdrant_client,
        sparse_model=sparse_model,
        collection_name="mm_rag_v1",
        workspace_id=uuid.uuid4(),
        query="clause 14.2",
    )

    assert len(results) == 1
    result = results[0]
    assert result.point_id == point.id
    assert result.document_id == document_id
    assert result.document_version_id == document_version_id
    assert result.text == "clause 14.2 says..."
    assert result.score == 1.7


def test_sparse_search_wraps_qdrant_failures():
    qdrant_client = MagicMock()
    qdrant_client.query_points.side_effect = RuntimeError("connection refused")
    sparse_model = MagicMock()
    sparse_model.query_embed.return_value = [_fake_sparse_embedding()]

    with pytest.raises(RetrievalError):
        sparse_search(
            qdrant_client=qdrant_client,
            sparse_model=sparse_model,
            collection_name="mm_rag_v1",
            workspace_id=uuid.uuid4(),
            query="q",
        )


def test_sparse_search_wraps_embedding_failures():
    qdrant_client = MagicMock()
    sparse_model = MagicMock()
    sparse_model.query_embed.side_effect = RuntimeError("model not loaded")

    with pytest.raises(RetrievalError):
        sparse_search(
            qdrant_client=qdrant_client,
            sparse_model=sparse_model,
            collection_name="mm_rag_v1",
            workspace_id=uuid.uuid4(),
            query="q",
        )
