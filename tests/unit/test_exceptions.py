import pytest

from packages.exceptions import (
    AuthenticationError,
    AuthorizationError,
    DatabaseError,
    DocumentPortalException,
    MembershipNotFoundError,
    ObjectStorageError,
)


def test_document_portal_exception_message_only():
    exc = DocumentPortalException("something failed")
    assert exc.message == "something failed"
    assert exc.original_exception is None
    assert str(exc) == "something failed"


def test_document_portal_exception_wraps_cause():
    cause = ValueError("root cause")
    exc = DocumentPortalException("wrapped failure", original_exception=cause)
    assert exc.original_exception is cause
    assert "wrapped failure" in str(exc)
    assert "root cause" in str(exc)


def test_database_error_is_document_portal_exception():
    exc = DatabaseError("db boom", original_exception=RuntimeError("driver error"))
    assert isinstance(exc, DocumentPortalException)
    with pytest.raises(DatabaseError):
        raise exc


def test_object_storage_error_is_document_portal_exception():
    exc = ObjectStorageError("s3 boom", original_exception=RuntimeError("botocore error"))
    assert isinstance(exc, DocumentPortalException)
    with pytest.raises(ObjectStorageError):
        raise exc


def test_authentication_error_is_document_portal_exception():
    exc = AuthenticationError("bad token")
    assert isinstance(exc, DocumentPortalException)
    with pytest.raises(AuthenticationError):
        raise exc


def test_authorization_error_is_document_portal_exception():
    exc = AuthorizationError("insufficient role")
    assert isinstance(exc, DocumentPortalException)
    with pytest.raises(AuthorizationError):
        raise exc


def test_membership_not_found_error_is_document_portal_exception():
    exc = MembershipNotFoundError("not a member")
    assert isinstance(exc, DocumentPortalException)
    with pytest.raises(MembershipNotFoundError):
        raise exc
