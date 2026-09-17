from packages.exceptions.base import DocumentPortalException


class EvalError(DocumentPortalException):
    """Raised at eval/'s module boundaries — dataset loading, workspace bootstrap, or a
    configured retrieval-pipeline-variant call failing."""
