from __future__ import annotations

from dataclasses import dataclass

from medexa.aws import dynamodb_setup, health, s3_setup
from medexa.config import settings
from medexa.logging_setup import configure_logging, get_logger

logger = get_logger("medexa.aws.bootstrap")


@dataclass(frozen=True)
class BootstrapResult:
    dynamodb_table: str
    s3_bucket: str | None
    health: health.AwsHealthReport


def provision(*, create_s3: bool = True, bucket_name: str | None = None) -> BootstrapResult:
    configure_logging(settings.log_level)
    dynamodb_setup.provision()
    bucket: str | None = None
    if create_s3:
        bucket = s3_setup.provision(bucket_name=bucket_name)
    report = health.check_all()
    logger.info(
        "aws_bootstrap_complete",
        extra={
            "extra_fields": {
                "dynamodb_table": settings.dynamodb_table_name,
                "s3_bucket": bucket,
                "healthy": report.healthy,
            }
        },
    )
    return BootstrapResult(
        dynamodb_table=settings.dynamodb_table_name,
        s3_bucket=bucket,
        health=report,
    )
