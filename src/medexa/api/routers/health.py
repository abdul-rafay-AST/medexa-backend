from __future__ import annotations

from fastapi import APIRouter

from medexa.config import settings

router = APIRouter(tags=["health"])


@router.get("/")
async def root() -> dict[str, str]:
    return {"service": "medexa-api", "docs": "/docs", "health": "/health"}


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


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
