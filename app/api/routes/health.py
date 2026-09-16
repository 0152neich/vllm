"""Liveness và dependency readiness."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.api.dependencies import get_container

router = APIRouter(prefix="/health", tags=["Health"])


@router.get("/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def ready(request: Request) -> JSONResponse:
    container = get_container(request)
    database = await container.repository.is_ready()
    redis = await container.limiter.is_ready()
    upstream = await container.upstream.is_ready()
    is_ready = database and redis and upstream
    return JSONResponse(
        status_code=200 if is_ready else 503,
        content={
            "status": "ready" if is_ready else "degraded",
            "database": "ready" if database else "unavailable",
            "redis": "ready" if redis else "unavailable",
            "upstream": "ready" if upstream else "unavailable",
        },
    )
