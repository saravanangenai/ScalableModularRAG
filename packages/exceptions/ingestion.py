from packages.exceptions.base import DocumentPortalException


class IngestionError(DocumentPortalException):
    """Raised at packages/ingestion's public function boundaries for any underlying
    chunking/embedding/Qdrant-upsert failure."""
