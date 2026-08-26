from qdrant_client import QdrantClient, models

from packages.exceptions import IngestionError

# Payload indexes required for the mandatory tenant/workspace filtering a later phase adds,
# per specs/architecture/02-data-model.md §3.
REQUIRED_PAYLOAD_INDEXES: dict[str, models.PayloadSchemaType] = {
    "tenant_id": models.PayloadSchemaType.KEYWORD,
    "workspace_id": models.PayloadSchemaType.KEYWORD,
    "document_id": models.PayloadSchemaType.KEYWORD,
    "document_version_id": models.PayloadSchemaType.KEYWORD,
    "is_current_version": models.PayloadSchemaType.BOOL,
    "content_type": models.PayloadSchemaType.KEYWORD,
    "page_number": models.PayloadSchemaType.INTEGER,
}


def ensure_collection(client: QdrantClient, collection_name: str, vector_size: int) -> None:
    """Creates the collection and its payload indexes if missing. Idempotent — safe to call
    on every worker/API startup."""
    try:
        if not client.collection_exists(collection_name):
            client.create_collection(
                collection_name=collection_name,
                vectors_config=models.VectorParams(
                    size=vector_size, distance=models.Distance.COSINE
                ),
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
