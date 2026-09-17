from packages.exceptions.base import DocumentPortalException


class RetrievalError(DocumentPortalException):
    """Raised at packages/retrieval's public function boundaries for any underlying
    embedding/Qdrant-query failure."""
