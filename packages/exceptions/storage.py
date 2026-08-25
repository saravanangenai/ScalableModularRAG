from packages.exceptions.base import DocumentPortalException


class ObjectStorageError(DocumentPortalException):
    """Raised at packages/storage's public function boundaries for any underlying
    boto3/botocore failure (connection, access, missing key)."""
