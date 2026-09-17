import uuid


def document_key(
    workspace_id: uuid.UUID | str,
    document_id: uuid.UUID | str,
    content_hash: str,
) -> str:
    """Content-hash-addressed key for a raw PDF upload.

    Same content_hash for the same document always yields the same key, which is what
    makes packages.storage.client.upload's exists()-check idempotency safe.
    """
    return f"{workspace_id}/{document_id}/{content_hash}.pdf"


def image_key(
    workspace_id: uuid.UUID | str,
    document_id: uuid.UUID | str,
    document_version_id: uuid.UUID | str,
    image_index: int,
) -> str:
    """Key for an image extracted from a specific document_version, written by ingestion."""
    return (
        f"{workspace_id}/{document_id}/{document_version_id}"
        f"/images/{image_index}.png"
    )


def table_key(
    workspace_id: uuid.UUID | str,
    document_id: uuid.UUID | str,
    document_version_id: uuid.UUID | str,
    table_index: int,
) -> str:
    """Key for a table's raw CSV extracted from a specific document_version, written by
    ingestion (specs/051-table-intelligence) — mirrors image_key's exact shape."""
    return (
        f"{workspace_id}/{document_id}/{document_version_id}"
        f"/tables/{table_index}.csv"
    )
