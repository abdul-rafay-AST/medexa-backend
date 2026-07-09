from __future__ import annotations

import boto3
from botocore.exceptions import ClientError

from medexa.config import settings


class S3ObjectStorage:
    def __init__(self, bucket: str, *, region_name: str | None = None) -> None:
        self._bucket = bucket
        self._client = boto3.client("s3", region_name=region_name or settings.aws_region)

    def put_bytes(self, key: str, data: bytes, *, content_type: str = "application/octet-stream") -> str:
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
            ServerSideEncryption="AES256",
        )
        return key

    def get_bytes(self, key: str) -> bytes:
        response = self._client.get_object(Bucket=self._bucket, Key=key)
        body = response["Body"].read()
        return bytes(body)

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=key)

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return True
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise

    def uri(self, key: str) -> str:
        return f"s3://{self._bucket}/{key}"
