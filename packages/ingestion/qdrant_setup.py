from qdrant_client import QdrantClient, models

from packages.exceptions import IngestionError

# Payload indexes required for the mandatory workspace filtering a later phase adds,
# per specs/architecture/02-data-model.md §3.
REQUIRED_PAYLOAD_INDEXES: dict[str, models.PayloadSchemaType] = {
    "workspace_id": models.PayloadSchemaType.KEYWORD,
    "document_id": models.PayloadSchemaType.KEYWORD,
    "document_version_id": models.PayloadSchemaType.KEYWORD,
    "is_current_version": models.PayloadSchemaType.BOOL,
    "content_type": models.PayloadSchemaType.KEYWORD,
    "page_number": models.PayloadSchemaType.INTEGER,
}

# Named sparse vector for the BM25 leg (specs/040-hybrid-retrieval-reranking) — lives
# alongside the existing unnamed/default dense vector on the same point, not a separate one.
SPARSE_VECTOR_NAME = "sparse"


def ensure_collection(client: QdrantClient, collection_name: str, vector_size: int) -> None:
    """Creates the collection (with both the dense and sparse vector configs) and its
    payload indexes if missing. Idempotent — safe to call on every worker/API startup.

    A collection created before specs/040 added the sparse vector gets **recreated**, not
    patched in place: Qdrant's update_collection rejects adding a vector name that wasn't
    part of the original creation ("Wrong input: Not existing vector name error: sparse" —
    confirmed against live Qdrant Cloud, contrary to this function's first draft, which
    assumed update_collection could add one). This drops any existing points, consistent
    with this project's established norm (specs/012, specs/030) that pre-launch local
    dev/test data doesn't need preserving across a schema change.
    """
    try:
        exists = client.collection_exists(collection_name)
        needs_recreate = False
        if exists:
            info = client.get_collection(collection_name)
            existing_sparse_vectors = set((info.config.params.sparse_vectors or {}).keys())
            needs_recreate = SPARSE_VECTOR_NAME not in existing_sparse_vectors

        if not exists or needs_recreate:
            if needs_recreate:
                client.delete_collection(collection_name)
            client.create_collection(
                collection_name=collection_name,
                vectors_config=models.VectorParams(
                    size=vector_size, distance=models.Distance.COSINE
                ),
                sparse_vectors_config={SPARSE_VECTOR_NAME: models.SparseVectorParams()},
            )
            info = client.get_collection(collection_name)

        existing_indexes = set((info.payload_schema or {}).keys())

        for field_name, field_schema in REQUIRED_PAYLOAD_INDEXES.items():
            if field_name not in existing_indexes:
                client.create_payload_index(
                    collection_name=collection_name,
                    field_name=field_name,
                    field_schema=field_schema,
                    wait=True,
                )
    except Exception as exc:
        raise IngestionError(
            f"failed to ensure Qdrant collection {collection_name!r}", exc
        ) from exc
