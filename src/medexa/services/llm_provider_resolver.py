"""Resolve Path B/C LLM backends with Bedrock → Groq failover.

When Bedrock is configured but unavailable (no IAM creds on HF Spaces, explicit
deny, etc.) and a Groq API key is present, we automatically route Path B/C to
Groq so Vercel + HF deployments keep working without AWS.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from medexa.config import MedexaConfig

logger = logging.getLogger(__name__)

PathBBackend = Literal["bedrock", "groq", "noop"]
PathCBackend = Literal["bedrock", "groq", "rules"]

_CACHE: "ResolvedLlmProviders | None" = None


@dataclass(frozen=True)
class ResolvedLlmProviders:
    path_b_backend: PathBBackend
    path_c_backend: PathCBackend
    path_b_reason: str
    path_c_reason: str
    bedrock_path_b_ok: bool | None = None
    bedrock_path_c_ok: bool | None = None


def clear_resolver_cache() -> None:
    global _CACHE
    _CACHE = None


def resolve_llm_providers(
    settings: MedexaConfig,
    *,
    force_refresh: bool = False,
) -> ResolvedLlmProviders:
    global _CACHE
    if _CACHE is not None and not force_refresh:
        return _CACHE

    groq_key = (settings.groq_api_key or "").strip()
    groq_ready = bool(groq_key)
    bedrock_ok_cache: dict[str, bool] = {}

    path_b_backend, path_b_reason = _resolve_path_b(
        settings,
        groq_ready=groq_ready,
        bedrock_ok_cache=bedrock_ok_cache,
    )
    uses_bedrock_c = settings.soap_generator == "bedrock" or settings.summary_generator == "bedrock"
    path_c_backend, path_c_reason = _resolve_path_c(
        settings,
        groq_ready=groq_ready,
        bedrock_ok_cache=bedrock_ok_cache,
    )

    bedrock_b_ok = bedrock_ok_cache.get(f"{settings.aws_region}:{settings.path_b_model_id}")
    bedrock_c_ok = bedrock_ok_cache.get(f"{settings.aws_region}:{settings.path_c_model_id}") if uses_bedrock_c else None

    resolved = ResolvedLlmProviders(
        path_b_backend=path_b_backend,
        path_c_backend=path_c_backend,
        path_b_reason=path_b_reason,
        path_c_reason=path_c_reason,
        bedrock_path_b_ok=bedrock_b_ok,
        bedrock_path_c_ok=bedrock_c_ok,
    )
    _CACHE = resolved
    logger.info(
        "llm_providers_resolved",
        extra={
            "extra_fields": {
                "path_b_backend": path_b_backend,
                "path_c_backend": path_c_backend,
                "path_b_reason": path_b_reason,
                "path_c_reason": path_c_reason,
            }
        },
    )
    return resolved


def _resolve_path_b(
    settings: MedexaConfig,
    *,
    groq_ready: bool,
    bedrock_ok_cache: dict[str, bool],
) -> tuple[PathBBackend, str]:
    if not settings.path_b_enabled:
        return "noop", "path_b_disabled"

    if settings.path_b_provider == "groq":
        if groq_ready:
            return "groq", "configured_groq"
        return "noop", "groq_key_missing"

    bedrock_ok = _bedrock_usable(settings.path_b_model_id, settings.aws_region, bedrock_ok_cache)
    if bedrock_ok:
        return "bedrock", "bedrock_probe_ok"

    if groq_ready:
        logger.warning(
            "path_b_bedrock_unavailable_using_groq",
            extra={"extra_fields": {"model": settings.path_b_model_id}},
        )
        return "groq", "bedrock_unavailable_groq_fallback"

    return "noop", "bedrock_unavailable_no_groq_key"


def _resolve_path_c(
    settings: MedexaConfig,
    *,
    groq_ready: bool,
    bedrock_ok_cache: dict[str, bool],
) -> tuple[PathCBackend, str]:
    uses_groq = settings.soap_generator == "groq" or settings.summary_generator == "groq"
    uses_bedrock = settings.soap_generator == "bedrock" or settings.summary_generator == "bedrock"

    if uses_groq:
        if groq_ready:
            return "groq", "configured_groq"
        return "rules", "groq_key_missing"

    if not uses_bedrock:
        return "rules", "rules_only"

    bedrock_ok = _bedrock_usable(settings.path_c_model_id, settings.aws_region, bedrock_ok_cache)
    if bedrock_ok:
        return "bedrock", "bedrock_probe_ok"

    if groq_ready:
        logger.warning(
            "path_c_bedrock_unavailable_using_groq",
            extra={"extra_fields": {"model": settings.path_c_model_id}},
        )
        return "groq", "bedrock_unavailable_groq_fallback"

    return "rules", "bedrock_unavailable_rules_fallback"


def _bedrock_usable(model_id: str, region: str, cache: dict[str, bool]) -> bool:
    key = f"{region}:{model_id}"
    if key in cache:
        return cache[key]
    ok, detail = _probe_bedrock(model_id, region)
    cache[key] = ok
    if not ok:
        logger.info(
            "bedrock_probe_unavailable",
            extra={"extra_fields": {"model": model_id, "detail": detail[:200]}},
        )
    return ok


def _probe_bedrock(model_id: str, region: str) -> tuple[bool, str]:
    try:
        import boto3  # noqa: PLC0415
    except ImportError:
        return False, "boto3_not_installed"

    try:
        from medexa.adapters.bedrock.health_probe import probe_bedrock_model

        return probe_bedrock_model(model_id, region=region)
    except Exception as exc:
        return False, str(exc)
