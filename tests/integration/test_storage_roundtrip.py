"""Requires `docker compose up -d minio` (infra/docker-compose.yml) and infra/.env
populated from infra/.env.example. Not runnable in a sandbox without Docker/MinIO."""

import boto3
import pytest
from botocore.exceptions import ClientError

from packages.storage.client import StorageClient
from packages.storage.config import Settings


@pytest.fixture(scope="session")
def storage_settings() -> Settings:
    return Settings()


@pytest.fixture(scope="session", autouse=True)
def ensure_bucket(storage_settings):
    s3 = boto3.client(
        "s3",
        endpoint_url=storage_settings.s3_endpoint_url,
        aws_access_key_id=storage_settings.minio_root_user,
        aws_secret_access_key=storage_settings.minio_root_password,
    )
    try:
        s3.create_bucket(Bucket=storage_settings.s3_bucket)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") not in (
            "BucketAlreadyOwnedByYou",
            "BucketAlreadyExists",
        ):
            raise


def test_upload_download_delete_round_trips_bytes_exactly(storage_settings):
    client = StorageClient(storage_settings)
    key = "integration-test/roundtrip.bin"
    payload = b"\x00\x01hello mm-rag\xff"

    client.upload(key, payload)
    assert client.exists(key) is True
    assert client.download(key) == payload

    client.delete(key)
    assert client.exists(key) is False


def test_upload_is_idempotent_for_identical_content_hash_key(storage_settings):
    client = StorageClient(storage_settings)
    key = "integration-test/idempotent.bin"
    payload = b"same bytes every time"

    try:
        client.upload(key, payload)
        client.upload(key, payload)  # second call must no-op, not error
        assert client.download(key) == payload
    finally:
        client.delete(key)
