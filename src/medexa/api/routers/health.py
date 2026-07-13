from __future__ import annotations

from fastapi import APIRouter

from medexa.config import settings

router = APIRouter(tags=["health"])


@router.get("/")
async def root() -> dict[str, str]:
    return {"service": "medexa-api", "docs": "/docs", "health": "/health"}


def _aws_extras_installed() -> bool:
    try:
        import boto3  # noqa: F401, PLC0415

        return True
    except ImportError:
        return False


@router.get("/health")
async def health() -> dict[str, object]:
    deepgram_configured = bool((settings.deepgram_api_key or "").strip())
    groq_configured = bool((settings.groq_api_key or "").strip())
    aws_ready = _aws_extras_installed()
    path_b_active = settings.path_b_enabled and (
        (settings.path_b_provider == "groq" and groq_configured)
        or (settings.path_b_provider == "bedrock" and aws_ready)
    )
    path_c_active = (
        (settings.soap_generator == "groq" or settings.summary_generator == "groq")
        and groq_configured
    ) or (
        (settings.soap_generator == "bedrock" or settings.summary_generator == "bedrock")
        and aws_ready
    )
    return {
        "status": "ok",
        "transcription_provider": settings.transcription_provider,
        "deepgram_configured": deepgram_configured,
        "deepgram_model": settings.deepgram_model if settings.transcription_provider == "deepgram" else None,
        "path_b_enabled": settings.path_b_enabled,
        "path_b_provider": settings.path_b_provider,
        "path_b_active": path_b_active,
        "soap_generator": settings.soap_generator,
        "summary_generator": settings.summary_generator,
        "path_c_active": path_c_active,
        "aws_extras_installed": aws_ready,
        "aws_region": settings.aws_region,
    }


@router.get("/health/aws")
async def health_aws() -> dict[str, object]:
    try:
        from medexa.aws.health import check_all
    except ImportError:
        return {
            "status": "degraded",
            "detail": "Install aws extras: pip install -e \".[aws]\"",
            "checks": [],
        }

    report = check_all()
    return {
        "status": "ok" if report.healthy else "degraded",
        "aws_region": settings.aws_region,
        "use_dynamodb": settings.use_dynamodb,
        "s3_bucket": settings.s3_bucket or settings.transcribe_s3_bucket,
        "checks": [{"name": c.name, "ok": c.ok, "detail": c.detail} for c in report.checks],
    }
