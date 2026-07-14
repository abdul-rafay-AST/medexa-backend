"""S3-backed config loader — downloads region rule files at startup and caches them.

When ``MEDEXA_CONFIG_SOURCE=s3`` the loader pulls rule files from the
``regions/<region>/...`` key prefix in the configured S3 bucket and writes
them into a local cache directory. All subsequent file reads hit the local
cache, so the application never blocks on S3 after boot.

Falls back to local ``config/`` if S3 is unreachable.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any

from medexa.config import settings

logger = logging.getLogger(__name__)


class S3ConfigLoader:
    """Download config/rules files from S3 into a local temp cache at startup."""

    def __init__(
        self,
        bucket: str,
        region_name: str | None = None,
        *,
        cache_dir: Path | None = None,
    ) -> None:
        self._bucket = bucket
        self._region_name = region_name or settings.aws_region
        self._cache_dir = cache_dir or Path(tempfile.mkdtemp(prefix="medexa_cfg_"))
        self._client: Any = None
        self._loaded_keys: set[str] = set()

    def _get_client(self) -> Any:
        if self._client is None:
            import boto3  # noqa: PLC0415

            self._client = boto3.client("s3", region_name=self._region_name)
        return self._client

    @property
    def cache_dir(self) -> Path:
        return self._cache_dir

    def warm_cache(self, prefix: str = "regions/") -> int:
        """Download all objects under *prefix* into the local cache.

        Returns the number of files downloaded. Errors are logged but
        do not raise — the caller falls back to local config.
        """
        client = self._get_client()
        count = 0
        try:
            paginator = client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
                for obj in page.get("Contents", []):
                    key: str = obj["Key"]
                    if key.endswith("/"):
                        continue
                    local_path = self._cache_dir / key
                    local_path.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        client.download_file(self._bucket, key, str(local_path))
                        self._loaded_keys.add(key)
                        count += 1
                    except Exception:
                        logger.warning(
                            "s3_config_download_failed",
                            extra={"extra_fields": {"bucket": self._bucket, "key": key}},
                            exc_info=True,
                        )
        except Exception:
            logger.error(
                "s3_config_warm_cache_failed",
                extra={"extra_fields": {"bucket": self._bucket, "prefix": prefix}},
                exc_info=True,
            )
        logger.info(
            "s3_config_cache_warmed",
            extra={
                "extra_fields": {
                    "bucket": self._bucket,
                    "prefix": prefix,
                    "files_cached": count,
                    "cache_dir": str(self._cache_dir),
                }
            },
        )
        return count

    def resolve_path(self, s3_key: str) -> Path | None:
        """Return the local cached path for a given S3 key, or ``None``."""
        local = self._cache_dir / s3_key
        if local.exists():
            return local
        # Try on-demand download for keys not in the warm cache.
        try:
            client = self._get_client()
            local.parent.mkdir(parents=True, exist_ok=True)
            client.download_file(self._bucket, s3_key, str(local))
            self._loaded_keys.add(s3_key)
            return local
        except Exception:
            logger.debug(
                "s3_config_on_demand_miss",
                extra={"extra_fields": {"key": s3_key}},
            )
            return None

    @property
    def loaded_count(self) -> int:
        return len(self._loaded_keys)
