"""S3-compatible object storage (MinIO locally). Uses only the standard S3 API."""

from typing import TYPE_CHECKING

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.config import Settings, get_settings

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client


def create_s3_client(settings: Settings, timeout_seconds: float | None = None) -> "S3Client":
    timeout = timeout_seconds or 60.0
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
        region_name=settings.s3_region,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            connect_timeout=timeout,
            read_timeout=timeout,
            retries={"max_attempts": 1},
        ),
    )


def bucket_exists(client: "S3Client", bucket: str) -> bool:
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchBucket"}:
            return False
        raise
    return True


def ensure_bucket(client: "S3Client", bucket: str) -> bool:
    """Create the bucket if missing. Returns True if it was created."""
    if bucket_exists(client, bucket):
        return False
    client.create_bucket(Bucket=bucket)
    return True


def main() -> None:
    settings = get_settings()
    created = ensure_bucket(create_s3_client(settings), settings.s3_bucket)
    state = "created" if created else "already exists"
    print(f"Bucket '{settings.s3_bucket}' {state}.")


if __name__ == "__main__":
    main()
