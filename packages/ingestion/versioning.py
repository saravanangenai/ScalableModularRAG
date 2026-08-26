import hashlib


def content_hash(data: bytes) -> str:
    """sha256 of the raw bytes, matching packages/storage's content-hash-addressed key
    scheme (specs/010-metadata-db-and-object-storage/plan.md)."""
    return hashlib.sha256(data).hexdigest()


def is_unchanged(new_hash: str, current_hash: str | None) -> bool:
    """True if a re-upload's content_hash matches the document's current version — per
    03-ingestion-workflow.md §5, this means no new version and no job."""
    return current_hash is not None and new_hash == current_hash
