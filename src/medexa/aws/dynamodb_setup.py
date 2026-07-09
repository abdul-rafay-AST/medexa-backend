from __future__ import annotations

import sys

import boto3
from botocore.exceptions import ClientError

from medexa.config import settings
from medexa.logging_setup import get_logger

logger = get_logger("medexa.aws.dynamodb_setup")

_TABLE_SCHEMA = {
    "TableName": settings.dynamodb_table_name,
    "KeySchema": [
        {"AttributeName": "session_id", "KeyType": "HASH"},
    ],
    "AttributeDefinitions": [
        {"AttributeName": "session_id", "AttributeType": "S"},
    ],
    "BillingMode": "PAY_PER_REQUEST",
    "SSESpecification": {
        "Enabled": True,
        "SSEType": "KMS",
    },
}

_TTL_SPEC = {
    "TableName": settings.dynamodb_table_name,
    "TimeToLiveSpecification": {
        "AttributeName": "ttl",
        "Enabled": True,
    },
}


def _client() -> "boto3.client":
    return boto3.client("dynamodb", region_name=settings.aws_region)


def table_exists(client: "boto3.client") -> bool:
    try:
        client.describe_table(TableName=settings.dynamodb_table_name)
        return True
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ResourceNotFoundException":
            return False
        raise


def create_table(client: "boto3.client") -> None:
    client.create_table(**_TABLE_SCHEMA)
    waiter = client.get_waiter("table_exists")
    waiter.wait(TableName=settings.dynamodb_table_name)
    logger.info(
        "dynamodb_table_created",
        extra={"extra_fields": {"table": settings.dynamodb_table_name}},
    )


def enable_ttl(client: "boto3.client") -> None:
    client.update_time_to_live(**_TTL_SPEC)
    logger.info(
        "dynamodb_ttl_enabled",
        extra={"extra_fields": {"table": settings.dynamodb_table_name, "attribute": "ttl"}},
    )


def provision() -> None:
    client = _client()
    if table_exists(client):
        logger.info(
            "dynamodb_table_already_exists",
            extra={"extra_fields": {"table": settings.dynamodb_table_name}},
        )
        _ensure_ttl(client)
        return
    create_table(client)
    enable_ttl(client)


def _ensure_ttl(client: "boto3.client") -> None:
    try:
        description = client.describe_time_to_live(TableName=settings.dynamodb_table_name)
        status = description.get("TimeToLiveDescription", {}).get("TimeToLiveStatus")
        if status in {"ENABLED", "ENABLING"}:
            return
        enable_ttl(client)
    except ClientError:
        enable_ttl(client)


if __name__ == "__main__":
    provision()
    sys.exit(0)
