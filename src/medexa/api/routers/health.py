from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/")
async def root() -> dict:
    return {"service": "medexa-api", "docs": "/docs", "health": "/health"}


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}
