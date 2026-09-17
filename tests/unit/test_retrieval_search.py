import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from packages.exceptions import RetrievalError
from packages.retrieval.dense import dense_search
from packages.retrieval.filters import build_workspace_filter


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
        "text": "the relevant clause says...",
        **payload_overrides,
    }
    point = SimpleNamespace(id=str(uuid.uuid4()), payload=payload, score=0.83)
    return point, document_id, document_version_id


def test_dense_search_applies_the_mandatory_workspace_filter():
    workspace_id = uuid.uuid4()
    point, _, _ = _fake_point()
    qdrant_client = MagicMock()
    qdrant_client.query_points.return_value = SimpleNamespace(points=[point])
    embeddings = MagicMock()
    embeddings.embed_query.return_value = [0.1, 0.2, 0.3]

    dense_search(
        qdrant_client=qdrant_client,
        embeddings=embeddings,
        collection_name="mm_rag_v1",
        workspace_id=workspace_id,
        query="what does the contract say",
        k=8,
    )

    embeddings.embed_query.assert_called_once_with("what does the contract say")
    _, call_kwargs = qdrant_client.query_points.call_args
    assert call_kwargs["query_filter"] == build_workspace_filter(workspace_id)
    assert call_kwargs["collection_name"] == "mm_rag_v1"
    assert call_kwargs["limit"] == 8


def test_dense_search_maps_qdrant_points_to_search_results():
    point, document_id, document_version_id = _fake_point()
    expected_point_id = point.id
    qdrant_client = MagicMock()
    qdrant_client.query_points.return_value = SimpleNamespace(points=[point])
    embeddings = MagicMock()
    embeddings.embed_query.return_value = [0.1]

    results = dense_search(
        qdrant_client=qdrant_client,
        embeddings=embeddings,
        collection_name="mm_rag_v1",
        workspace_id=uuid.uuid4(),
        query="q",
    )

    assert len(results) == 1
    result = results[0]
    assert result.point_id == expected_point_id
    assert result.document_id == document_id
    assert result.document_version_id == document_version_id
    assert result.filename == "contract.pdf"
    assert result.text == "the relevant clause says..."
    assert result.score == 0.83


def test_dense_search_wraps_qdrant_failures():
    qdrant_client = MagicMock()
    qdrant_client.query_points.side_effect = RuntimeError("connection refused")
    embeddings = MagicMock()
    embeddings.embed_query.return_value = [0.1]

    with pytest.raises(RetrievalError):
        dense_search(
            qdrant_client=qdrant_client,
            embeddings=embeddings,
            collection_name="mm_rag_v1",
            workspace_id=uuid.uuid4(),
            query="q",
        )


def test_dense_search_wraps_embedding_failures():
    qdrant_client = MagicMock()
    embeddings = MagicMock()
    embeddings.embed_query.side_effect = RuntimeError("rate limited")

    with pytest.raises(RetrievalError):
        dense_search(
            qdrant_client=qdrant_client,
            embeddings=embeddings,
            collection_name="mm_rag_v1",
            workspace_id=uuid.uuid4(),
            query="q",
        )
