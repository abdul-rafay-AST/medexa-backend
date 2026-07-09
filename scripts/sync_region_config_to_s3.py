from __future__ import annotations

import argparse
from pathlib import Path

import boto3

from medexa.aws.paths import region_config_key
from medexa.config import settings
from medexa.domain.billing_region import BillingRegion, normalize_billing_region


def sync_region_dir(region: BillingRegion, source_dir: Path, bucket: str) -> int:
    client = boto3.client("s3", region_name=settings.aws_region)
    count = 0
    for path in source_dir.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(source_dir).as_posix()
        key = region_config_key(region, relative)
        client.upload_file(str(path), bucket, key)
        count += 1
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description="Upload config/regions/<region> to S3.")
    parser.add_argument("region", help="Billing region: US, SA, AE, or ALL")
    parser.add_argument(
        "--source",
        type=Path,
        default=None,
        help="Source directory (default: config/regions/<region>)",
    )
    parser.add_argument("--bucket", default=None, help="S3 bucket (default: MEDEXA_S3_BUCKET)")
    args = parser.parse_args()

    region_arg = args.region.upper()
    if region_arg == "ALL":
        regions = ["US", "SA", "AE"]
    else:
        regions = [normalize_billing_region(region_arg)]

    bucket = args.bucket or settings.s3_bucket
    if not bucket:
        raise SystemExit("Set MEDEXA_S3_BUCKET or pass --bucket")

    for r in regions:
        source = args.source or Path("config") / "regions" / r.lower()
        if not source.exists():
            print(f"Warning: Source directory not found: {source}")
            continue
        uploaded = sync_region_dir(r, source, bucket)
        print(f"Uploaded {uploaded} files to s3://{bucket}/regions/{r.lower()}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
