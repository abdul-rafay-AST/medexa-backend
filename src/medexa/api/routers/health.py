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
    """Fast config check — use /health/bedrock for a live Bedrock Converse probe."""
    deepgram_configured = bool((settings.deepgram_api_key or "").strip())
    groq_configured = bool((settings.groq_api_key or "").strip())
    aws_ready = _aws_extras_installed()
    return {
        "status": "ok",
        "transcription_provider": settings.transcription_provider,
        "deepgram_configured": deepgram_configured,
        "deepgram_model": settings.deepgram_model if settings.transcription_provider == "deepgram" else None,
        "deepgram_diarize_model": settings.deepgram_diarize_model or None,
        "path_b_enabled": settings.path_b_enabled,
        "path_b_provider": settings.path_b_provider,
        "path_b_model": settings.path_b_model_id,
        "path_b_configured": settings.path_b_enabled
        and (
            (settings.path_b_provider == "groq" and groq_configured)
            or (settings.path_b_provider == "bedrock" and aws_ready)
        ),
        "path_c_model": settings.path_c_model_id,
        "soap_generator": settings.soap_generator,
        "summary_generator": settings.summary_generator,
        "path_c_configured": (
            (settings.soap_generator == "groq" or settings.summary_generator == "groq")
            and groq_configured
        )
        or (
            (settings.soap_generator == "bedrock" or settings.summary_generator == "bedrock")
            and aws_ready
        ),
        "aws_extras_installed": aws_ready,
        "aws_region": settings.aws_region,
        "verify_bedrock": "/health/bedrock",
        "verify_transcribe": "/health/transcribe",
        "transcribe_s3_bucket": settings.transcribe_s3_bucket or settings.s3_bucket,
        "transcribe_speaker_labels": settings.transcribe_enable_speaker_labels
        if settings.transcription_provider == "aws_transcribe"
        else None,
    }


@router.get("/health/bedrock")
async def health_bedrock() -> dict[str, object]:
    """Live Bedrock probe — calls Converse with 1 token per configured model."""
    if not _aws_extras_installed():
        return {"status": "degraded", "detail": "boto3 not installed", "path_b": None, "path_c": None}

    from medexa.adapters.bedrock.health_probe import probe_bedrock_model

    path_b = {"ok": False, "detail": "not configured"}
    if settings.path_b_enabled and settings.path_b_provider == "bedrock":
        ok, detail = probe_bedrock_model(settings.path_b_model_id)
        path_b = {"ok": ok, "detail": detail, "model": settings.path_b_model_id}

    path_c = {"ok": False, "detail": "not configured"}
    if settings.soap_generator == "bedrock" or settings.summary_generator == "bedrock":
        ok, detail = probe_bedrock_model(settings.path_c_model_id)
        path_c = {"ok": ok, "detail": detail, "model": settings.path_c_model_id}

    healthy = (
        (not settings.path_b_enabled or settings.path_b_provider != "bedrock" or path_b.get("ok"))
        and (
            not (settings.soap_generator == "bedrock" or settings.summary_generator == "bedrock")
            or path_c.get("ok")
        )
    )
    return {
        "status": "ok" if healthy else "degraded",
        "aws_region": settings.aws_region,
        "path_b": path_b,
        "path_c": path_c,
        "try_other_models": "/health/bedrock/models",
    }


@router.get("/health/bedrock/models")
async def health_bedrock_models() -> dict[str, object]:
    """Probe common Haiku model IDs with the deployed AWS credentials."""
    if not _aws_extras_installed():
        return {"status": "degraded", "detail": "boto3 not installed", "models": []}

    from medexa.adapters.bedrock.health_probe import probe_bedrock_model

    candidates = [
        "us.anthropic.claude-haiku-4-5-20251001-v1:0",
        "us.anthropic.claude-3-haiku-20240307-v1:0",
        "anthropic.claude-3-haiku-20240307-v1:0",
        "us.anthropic.claude-3-5-haiku-20241022-v1:0",
    ]
    models: list[dict[str, object]] = []
    for model_id in candidates:
        ok, detail = probe_bedrock_model(model_id)
        models.append({"model": model_id, "ok": ok, "detail": detail})

    any_ok = any(item["ok"] for item in models)
    return {
        "status": "ok" if any_ok else "degraded",
        "aws_region": settings.aws_region,
        "models": models,
    }


@router.get("/health/transcribe")
async def health_transcribe() -> dict[str, object]:
    """Verify Amazon Transcribe (standard) API + S3 staging bucket (no job started)."""
    bucket = settings.transcribe_s3_bucket or settings.s3_bucket
    configured = settings.transcription_provider == "aws_transcribe"
    if not _aws_extras_installed():
        return {
            "status": "degraded",
            "configured": configured,
            "detail": "boto3 not installed",
            "bucket": bucket,
        }

    from medexa.adapters.aws.transcribe_health import probe_transcribe

    ok, detail = probe_transcribe(region=settings.aws_region, bucket=bucket)
    return {
        "status": "ok" if ok else "degraded",
        "configured_as_default": configured,
        "aws_region": settings.aws_region,
        "bucket": bucket,
        "speaker_labels": settings.transcribe_enable_speaker_labels,
        "max_speakers": settings.transcribe_max_speakers,
        "ok": ok,
        "detail": detail,
        "note": (
            "Batch Amazon Transcribe is higher latency than Deepgram; "
            "set MEDEXA_TRANSCRIPTION_PROVIDER=aws_transcribe to use it for ambient."
        ),
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
