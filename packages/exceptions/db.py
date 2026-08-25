from packages.exceptions.base import DocumentPortalException


class DatabaseError(DocumentPortalException):
    """Raised at packages/db's public function boundaries for any underlying
    SQLAlchemy/driver failure (connection, integrity, query execution)."""
