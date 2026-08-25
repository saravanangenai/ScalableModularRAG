class DocumentPortalException(Exception):
    """Base exception for all typed errors raised across MM-RAG packages.

    Wraps an underlying driver/SDK error at a module boundary, preserving it as
    `original_exception` so callers can inspect the root cause without every
    package needing to know each other's exception types.
    """

    def __init__(self, message: str, original_exception: Exception | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.original_exception = original_exception

    def __str__(self) -> str:
        if self.original_exception is not None:
            return f"{self.message} (caused by: {self.original_exception!r})"
        return self.message
