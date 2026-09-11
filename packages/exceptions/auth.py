from packages.exceptions.base import DocumentPortalException


class AuthenticationError(DocumentPortalException):
    """Raised when a bearer credential (JWT or API key) is missing, malformed, expired, or
    otherwise fails verification. Maps to HTTP 401 at the API boundary."""


class AuthorizationError(DocumentPortalException):
    """Raised when the caller is a known member of the target workspace but their
    role doesn't meet the route's minimum requirement. Maps to HTTP 403."""


class MembershipNotFoundError(DocumentPortalException):
    """Raised when the caller has no membership at all in the target workspace.
    Maps to HTTP 404 (not 403), per 06-security-model.md §5: a non-member must not be able
    to distinguish "doesn't exist" from "exists but you can't see it"."""
