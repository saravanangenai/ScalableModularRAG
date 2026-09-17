from packages.exceptions.base import DocumentPortalException


class RateLimitExceededError(DocumentPortalException):
    """Raised when a caller exceeds a configured rate-limit window. Maps to HTTP 429, with
    retry_after_seconds surfaced as the response's Retry-After header."""

    def __init__(self, message: str, retry_after_seconds: int) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds
