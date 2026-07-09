from __future__ import annotations

import argparse
import sys

from medexa.aws.bootstrap import provision
from medexa.config import settings


def main() -> int:
    parser = argparse.ArgumentParser(description="Provision Medexa AWS resources (DynamoDB + S3).")
    parser.add_argument("--skip-s3", action="store_true", help="Only provision DynamoDB.")
    parser.add_argument("--bucket", default=None, help="Explicit S3 bucket name.")
    args = parser.parse_args()

    result = provision(create_s3=not args.skip_s3, bucket_name=args.bucket)

    print("Medexa AWS bootstrap complete")
    print(f"  AWS region:      {settings.aws_region}")
    print(f"  Environment:     {settings.aws_environment}")
    print(f"  DynamoDB table:  {result.dynamodb_table}")
    print(f"  S3 bucket:       {result.s3_bucket or '(skipped)'}")
    print()
    print("Add to your .env:")
    print(f"  MEDEXA_USE_DYNAMODB=true")
    print(f"  MEDEXA_DYNAMODB_TABLE_NAME={result.dynamodb_table}")
    print(f"  MEDEXA_AWS_REGION={settings.aws_region}")
    if result.s3_bucket:
        print(f"  MEDEXA_S3_BUCKET={result.s3_bucket}")
        print(f"  MEDEXA_TRANSCRIBE_S3_BUCKET={result.s3_bucket}")
    print()
    print("Health checks:")
    for check in result.health.checks:
        status = "ok" if check.ok else "FAIL"
        print(f"  [{status}] {check.name}: {check.detail}")

    return 0 if result.health.healthy else 1


if __name__ == "__main__":
    sys.exit(main())
