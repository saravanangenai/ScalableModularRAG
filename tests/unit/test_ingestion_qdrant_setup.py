from types import SimpleNamespace
from unittest.mock import MagicMock

from qdrant_client import models

from packages.ingestion.qdrant_setup import SPARSE_VECTOR_NAME, ensure_collection


def _fake_collection_info(*, sparse_vectors=None, payload_schema=None):
    return SimpleNamespace(
        config=SimpleNamespace(params=SimpleNamespace(sparse_vectors=sparse_vectors)),
        payload_schema=payload_schema or {},
    )


def test_new_collection_is_created_with_sparse_vector_config():
    client = MagicMock()
    client.collection_exists.return_value = False
    client.get_collection.return_value = _fake_collection_info(
        sparse_vectors={SPARSE_VECTOR_NAME: models.SparseVectorParams()}
    )

    ensure_collection(client, "mm_rag_v1", vector_size=1536)

    client.create_collection.assert_called_once()
    _, kwargs = client.create_collection.call_args
    assert SPARSE_VECTOR_NAME in kwargs["sparse_vectors_config"]
    client.update_collection.assert_not_called()


def test_existing_collection_missing_sparse_vector_is_recreated():
    """Qdrant's update_collection rejects adding a vector name that wasn't part of the
    original creation (confirmed against live Qdrant Cloud — see qdrant_setup.py's
    docstring) — so a pre-specs/040 collection must be deleted and recreated, not patched."""
    client = MagicMock()
    client.collection_exists.return_value = True
    client.get_collection.return_value = _fake_collection_info(sparse_vectors=None)

    ensure_collection(client, "mm_rag_v1", vector_size=1536)

    client.delete_collection.assert_called_once_with("mm_rag_v1")
    client.update_collection.assert_not_called()
    client.create_collection.assert_called_once()
    _, kwargs = client.create_collection.call_args
    assert SPARSE_VECTOR_NAME in kwargs["sparse_vectors_config"]


def test_existing_collection_with_sparse_vector_already_present_is_untouched():
    client = MagicMock()
    client.collection_exists.return_value = True
    client.get_collection.return_value = _fake_collection_info(
        sparse_vectors={SPARSE_VECTOR_NAME: models.SparseVectorParams()}
    )

    ensure_collection(client, "mm_rag_v1", vector_size=1536)

    client.create_collection.assert_not_called()
    client.update_collection.assert_not_called()
    client.delete_collection.assert_not_called()
