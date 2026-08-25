from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from packages.exceptions import ObjectStorageError
from packages.storage.client import StorageClient
from packages.storage.config import Settings


def _settings() -> Settings:
    return Settings(
        s3_endpoint_url="http://localhost:9000",
        s3_bucket="mm-rag-documents",
        minio_root_user="user",
        minio_root_password="password",
        _env_file=None,
    )


def _not_found_error(operation: str) -> ClientError:
    return ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, operation)


@patch("packages.storage.client.boto3.client")
def test_upload_is_idempotent_when_key_already_exists(mock_boto_client):
    mock_s3 = MagicMock()
    mock_boto_client.return_value = mock_s3
    mock_s3.head_object.return_value = {}  # exists() -> True

    client = StorageClient(_settings())
    result = client.upload("some/key.pdf", b"bytes")

    assert result == "some/key.pdf"
    mock_s3.put_object.assert_not_called()


@patch("packages.storage.client.boto3.client")
def test_upload_puts_object_when_key_is_new(mock_boto_client):
    mock_s3 = MagicMock()
    mock_boto_client.return_value = mock_s3
    mock_s3.head_object.side_effect = _not_found_error("HeadObject")

    client = StorageClient(_settings())
    client.upload("new/key.pdf", b"bytes")

    mock_s3.put_object.assert_called_once_with(
        Bucket="mm-rag-documents", Key="new/key.pdf", Body=b"bytes"
    )


@patch("packages.storage.client.boto3.client")
def test_exists_returns_false_on_not_found(mock_boto_client):
    mock_s3 = MagicMock()
    mock_boto_client.return_value = mock_s3
    mock_s3.head_object.side_effect = _not_found_error("HeadObject")

    client = StorageClient(_settings())
    assert client.exists("missing/key.pdf") is False


@patch("packages.storage.client.boto3.client")
def test_download_wraps_client_error(mock_boto_client):
    mock_s3 = MagicMock()
    mock_boto_client.return_value = mock_s3
    mock_s3.get_object.side_effect = ClientError(
        {"Error": {"Code": "500", "Message": "boom"}}, "GetObject"
    )

    client = StorageClient(_settings())
    with pytest.raises(ObjectStorageError):
        client.download("some/key.pdf")


@patch("packages.storage.client.boto3.client")
def test_download_returns_bytes(mock_boto_client):
    mock_s3 = MagicMock()
    mock_boto_client.return_value = mock_s3
    mock_s3.get_object.return_value = {"Body": BytesIO(b"payload")}

    client = StorageClient(_settings())
    assert client.download("some/key.pdf") == b"payload"


@patch("packages.storage.client.boto3.client")
def test_delete_wraps_client_error(mock_boto_client):
    mock_s3 = MagicMock()
    mock_boto_client.return_value = mock_s3
    mock_s3.delete_object.side_effect = ClientError(
        {"Error": {"Code": "500", "Message": "boom"}}, "DeleteObject"
    )

    client = StorageClient(_settings())
    with pytest.raises(ObjectStorageError):
        client.delete("some/key.pdf")
