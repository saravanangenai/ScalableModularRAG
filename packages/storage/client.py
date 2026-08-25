import boto3
from botocore.exceptions import BotoCoreError, ClientError

from packages.exceptions import ObjectStorageError
from packages.storage.config import Settings


class StorageClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or Settings()
        self._bucket = self._settings.s3_bucket
        try:
            self._s3 = boto3.client(
                "s3",
                endpoint_url=self._settings.s3_endpoint_url,
                aws_access_key_id=self._settings.minio_root_user,
                aws_secret_access_key=self._settings.minio_root_password,
            )
        except (BotoCoreError, ClientError) as exc:
            raise ObjectStorageError(
                "failed to create S3-compatible client", original_exception=exc
            ) from exc

    def exists(self, key: str) -> bool:
        try:
            self._s3.head_object(Bucket=self._bucket, Key=key)
            return True
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code")
            if error_code in ("404", "NoSuchKey"):
                return False
            raise ObjectStorageError(
                f"failed to check existence of key {key!r}", original_exception=exc
            ) from exc
        except BotoCoreError as exc:
            raise ObjectStorageError(
                f"failed to check existence of key {key!r}", original_exception=exc
            ) from exc

    def upload(self, key: str, data: bytes) -> str:
        """Upload data to key. No-op if key already exists (content-hash-addressed keys
        mean an existing key already holds identical bytes — see plan.md "Storage key
        scheme")."""
        if self.exists(key):
            return key
        try:
            self._s3.put_object(Bucket=self._bucket, Key=key, Body=data)
        except (BotoCoreError, ClientError) as exc:
            raise ObjectStorageError(
                f"failed to upload key {key!r}", original_exception=exc
            ) from exc
        return key

    def download(self, key: str) -> bytes:
        try:
            response = self._s3.get_object(Bucket=self._bucket, Key=key)
            return response["Body"].read()
        except (BotoCoreError, ClientError) as exc:
            raise ObjectStorageError(
                f"failed to download key {key!r}", original_exception=exc
            ) from exc

    def delete(self, key: str) -> None:
        try:
            self._s3.delete_object(Bucket=self._bucket, Key=key)
        except (BotoCoreError, ClientError) as exc:
            raise ObjectStorageError(
                f"failed to delete key {key!r}", original_exception=exc
            ) from exc
