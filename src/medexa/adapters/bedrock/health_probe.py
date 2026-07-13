from __future__ import annotations

import logging
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from medexa.adapters.bedrock.model_resolver import bedrock_model_candidates
from medexa.config import settings

logger = logging.getLogger(__name__)


def probe_bedrock_model(model_id: str, *, region: str | None = None) -> tuple[bool, str]:
    """Invoke a 1-token Bedrock Converse call to verify model access."""
    region_name = (region or settings.aws_region).strip()
    last_error = "unknown"
    try:
        import boto3  # noqa: PLC0415

        client = boto3.client("bedrock-runtime", region_name=region_name)
    except Exception as exc:
        return False, f"bedrock client init failed: {exc}"

    for candidate in bedrock_model_candidates(model_id):
        try:
            response = client.converse(
                modelId=candidate,
                messages=[{"role": "user", "content": [{"text": "ping"}]}],
                inferenceConfig={"maxTokens": 8, "temperature": 0.0},
            )
            text = _extract_text(response)
            detail = f"ok model={candidate} response={text[:40]!r}"
            return True, detail
        except (ClientError, BotoCoreError) as exc:
            last_error = f"{candidate}: {exc}"
            logger.warning("bedrock_probe_failed", extra={"extra_fields": {"detail": last_error}})
        except Exception as exc:
            last_error = f"{candidate}: {exc}"
            logger.warning("bedrock_probe_failed", extra={"extra_fields": {"detail": last_error}})

    return False, last_error


def _extract_text(response: dict[str, Any]) -> str:
    content = response.get("output", {}).get("message", {}).get("content", [])
    if not isinstance(content, list) or not content:
        return ""
    first = content[0]
    if isinstance(first, dict):
        return str(first.get("text", ""))
    return ""
