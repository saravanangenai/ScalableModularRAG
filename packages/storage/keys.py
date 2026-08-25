import uuid


def document_key(
    tenant_id: uuid.UUID | str,
    workspace_id: uuid.UUID | str,
    document_id: uuid.UUID | str,
    content_hash: str,
) -> str:
    """Content-hash-addressed key for a raw PDF upload.

    Same content_hash for the same document always yields the same key, which is what
    makes packages.storage.client.upload's exists()-check idempotency safe.
    """
    return f"{tenant_id}/{workspace_id}/{document_id}/{content_hash}.pdf"


def image_key(
    tenant_id: uuid.UUID | str,
    workspace_id: uuid.UUID | str,
    document_id: uuid.UUID | str,
    document_version_id: uuid.UUID | str,
    image_index: int,
) -> str:
    """Key for an image extracted from a specific document_version, written by ingestion."""
    return (
        f"{tenant_id}/{workspace_id}/{document_id}/{document_version_id}"
        f"/images/{image_index}.png"
    )
