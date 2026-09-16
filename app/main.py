"""Composition root của LLM Gateway."""

from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from app.api.exception_handlers import register_exception_handlers
from app.api.routes import admin_ui, chat, health, management, models
from app.core.config import Settings, get_settings
from app.integrations.upstream import OpenAIUpstream
from app.repositories.database import create_repository
from app.services.auth_service import AuthService
from app.services.key_service import ApiKeyService
from app.services.limit_service import create_redis_limiter


@dataclass
class ApplicationContainer:
    """Các dependency sống theo vòng đời ứng dụng."""

    settings: Settings
    repository: Any
    limiter: Any
    upstream: Any
    auth_service: Any
    key_service: ApiKeyService


async def _close(component: Any) -> None:
    close = getattr(component, "close", None)
    if close is not None:
        await close()


def create_app(
    settings: Settings | None = None,
    repository: Any | None = None,
    limiter: Any | None = None,
    upstream: Any | None = None,
    auth_service: Any | None = None,
) -> FastAPI:
    """Tạo app và cho phép inject fake dependency trong integration tests."""

    runtime_settings = settings or get_settings()
    runtime_repository = repository or create_repository(runtime_settings.database)
    runtime_limiter = limiter or create_redis_limiter(
        runtime_settings.redis.url, runtime_settings.redis.lease_grace_seconds
    )
    runtime_upstream = upstream or OpenAIUpstream(runtime_settings.upstream)
    key_service = ApiKeyService(runtime_settings.security.key_pepper)
    runtime_auth = auth_service or AuthService(
        runtime_repository,
        key_service,
        runtime_settings.security.platform_admin_key,
        runtime_limiter,
        runtime_settings.redis.policy_cache_seconds,
    )
    container = ApplicationContainer(
        runtime_settings,
        runtime_repository,
        runtime_limiter,
        runtime_upstream,
        runtime_auth,
        key_service,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if runtime_settings.service.version != "test":
            forbidden = ("replace-with", "change-me")
            secrets_to_check = (
                runtime_settings.security.key_pepper,
                runtime_settings.security.platform_admin_key,
            )
            if any(
                marker in value for value in secrets_to_check for marker in forbidden
            ):
                raise RuntimeError("Gateway secrets chưa được cấu hình an toàn")
        initialize = getattr(runtime_repository, "initialize", None)
        if initialize is not None:
            await initialize(runtime_settings.database.auto_create_schema)
        yield
        await _close(runtime_upstream)
        await _close(runtime_limiter)
        await _close(runtime_repository)

    logging.basicConfig(level=logging.INFO)
    app = FastAPI(
        title=runtime_settings.service.name,
        version=runtime_settings.service.version,
        lifespan=lifespan,
    )
    app.state.container = container

    @app.middleware("http")
    async def request_context(request: Request, call_next: Any) -> Response:
        supplied_request_id = request.headers.get("X-Request-Id", "")
        request_id = (
            supplied_request_id
            if re.fullmatch(r"[A-Za-z0-9._-]{1,64}", supplied_request_id)
            else uuid4().hex
        )
        request.state.request_id = request_id
        content_length = request.headers.get("content-length")
        try:
            declared_length = int(content_length) if content_length else 0
        except ValueError:
            declared_length = runtime_settings.service.request_body_limit_bytes + 1
        if declared_length > runtime_settings.service.request_body_limit_bytes:
            return JSONResponse(
                status_code=413,
                content={
                    "error": {
                        "message": "Request body vượt giới hạn.",
                        "type": "invalid_request_error",
                        "param": None,
                        "code": "request_too_large",
                    }
                },
                headers={"X-Request-Id": request_id},
            )
        response = await call_next(request)
        response.headers.setdefault("X-Request-Id", request_id)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        return response

    register_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(chat.router, prefix=runtime_settings.service.runtime_prefix)
    app.include_router(models.router, prefix=runtime_settings.service.runtime_prefix)
    app.include_router(
        management.router, prefix=runtime_settings.service.management_prefix
    )
    app.include_router(admin_ui.router)
    return app


app = create_app()
