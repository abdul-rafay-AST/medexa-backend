from __future__ import annotations

import boto3
from botocore.exceptions import ClientError

from medexa.config import settings
from medexa.logging_setup import get_logger

logger = get_logger("medexa.aws.s3_setup")


def _client() -> "boto3.client":
    return boto3.client("s3", region_name=settings.aws_region)


def bucket_exists(client: "boto3.client", bucket_name: str) -> bool:
    try:
        client.head_bucket(Bucket=bucket_name)
        return True
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in {"404", "NoSuchBucket", "NotFound"}:
            return False
        raise


def default_bucket_name(environment: str, account_id: str) -> str:
    return "medexa-storage"


def fallback_bucket_name(environment: str, account_id: str) -> str:
    slug = environment.strip().lower().replace("_", "-")
    return f"medexa-storage-{slug}-{account_id}"


def default_bucket_candidates(environment: str, account_id: str) -> list[str]:
    return [
        default_bucket_name(environment, account_id),
        f"medexa-storage-{environment.strip().lower().replace('_', '-')}",
        fallback_bucket_name(environment, account_id),
    ]


def resolve_bucket_name(explicit: str | None = None) -> str:
    if explicit:
        return explicit
    if settings.s3_bucket:
        return settings.s3_bucket
    sts = boto3.client("sts", region_name=settings.aws_region)
    account_id = sts.get_caller_identity()["Account"]
    return default_bucket_name(settings.aws_environment, account_id)


def create_bucket(client: "boto3.client", bucket_name: str) -> None:
    params: dict[str, object] = {"Bucket": bucket_name}
    if settings.aws_region != "us-east-1":
        params["CreateBucketConfiguration"] = {"LocationConstraint": settings.aws_region}
    client.create_bucket(**params)
    client.put_public_access_block(
        Bucket=bucket_name,
        PublicAccessBlockConfiguration={
            "BlockPublicAcls": True,
            "IgnorePublicAcls": True,
            "BlockPublicPolicy": True,
            "RestrictPublicBuckets": True,
        },
    )
    client.put_bucket_encryption(
        Bucket=bucket_name,
        ServerSideEncryptionConfiguration={
            "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]
        },
    )
    client.put_bucket_lifecycle_configuration(
        Bucket=bucket_name,
        LifecycleConfiguration={
            "Rules": [
                {
                    "ID": "expire-transcribe-temp",
                    "Status": "Enabled",
                    "Filter": {"Prefix": "transcribe/"},
                    "Expiration": {"Days": 7},
                },
                {
                    "ID": "expire-exports-temp",
                    "Status": "Enabled",
                    "Filter": {"Prefix": "exports/"},
                    "Expiration": {"Days": 30},
                },
            ]
        },
    )
    logger.info(
        "s3_bucket_created",
        extra={"extra_fields": {"bucket": bucket_name, "region": settings.aws_region}},
    )


def provision(bucket_name: str | None = None) -> str:
    client = _client()
    if bucket_name or settings.s3_bucket:
        name = resolve_bucket_name(bucket_name)
        if bucket_exists(client, name):
            logger.info("s3_bucket_already_exists", extra={"extra_fields": {"bucket": name}})
            return name
        create_bucket(client, name)
        return name

    sts = boto3.client("sts", region_name=settings.aws_region)
    account_id = sts.get_caller_identity()["Account"]
    for name in default_bucket_candidates(settings.aws_environment, account_id):
        try:
            if bucket_exists(client, name):
                logger.info("s3_bucket_already_exists", extra={"extra_fields": {"bucket": name}})
                return name
            create_bucket(client, name)
            return name
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in {"403", "AccessDenied", "BucketAlreadyExists"}:
                continue
            raise

    raise RuntimeError("Unable to provision an S3 bucket from the default Medexa naming scheme.")
