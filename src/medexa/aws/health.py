from __future__ import annotations

from dataclasses import dataclass, field

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from medexa.aws import s3_setup
from medexa.config import settings


@dataclass(frozen=True)
class ServiceCheck:
    name: str
    ok: bool
    detail: str


@dataclass
class AwsHealthReport:
    healthy: bool
    checks: list[ServiceCheck] = field(default_factory=list)


def _check_dynamodb() -> ServiceCheck:
    if not settings.use_dynamodb:
        return ServiceCheck("dynamodb", True, "disabled (in-memory mode)")
    try:
        client = boto3.client("dynamodb", region_name=settings.aws_region)
        client.describe_table(TableName=settings.dynamodb_table_name)
        return ServiceCheck("dynamodb", True, settings.dynamodb_table_name)
    except (ClientError, BotoCoreError) as exc:
        return ServiceCheck("dynamodb", False, str(exc))


def _check_s3() -> ServiceCheck:
    bucket = settings.s3_bucket or settings.transcribe_s3_bucket
    if not bucket:
        return ServiceCheck("s3", True, "not configured")
    try:
        client = boto3.client("s3", region_name=settings.aws_region)
        if s3_setup.bucket_exists(client, bucket):
            return ServiceCheck("s3", True, bucket)
        return ServiceCheck("s3", False, f"bucket not found: {bucket}")
    except (ClientError, BotoCoreError) as exc:
        return ServiceCheck("s3", False, str(exc))


def _check_sts() -> ServiceCheck:
    try:
        sts = boto3.client("sts", region_name=settings.aws_region)
        identity = sts.get_caller_identity()
        return ServiceCheck("sts", True, identity.get("Arn", "ok"))
    except (ClientError, BotoCoreError) as exc:
        return ServiceCheck("sts", False, str(exc))


def check_all() -> AwsHealthReport:
    checks = [_check_sts(), _check_dynamodb(), _check_s3()]
    return AwsHealthReport(healthy=all(c.ok for c in checks), checks=checks)
