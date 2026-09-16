"""OpenAI-compatible Chat Completions runtime endpoint."""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.api.dependencies import get_container, require_runtime_policy
from app.core.errors import GatewayError
from app.domain.auth import ProjectPolicy
from app.domain.chat import ChatCompletionRequest

router = APIRouter(tags=["Chat Completions"])
logger = logging.getLogger(__name__)


async def _record_usage(repository: Any, event: dict[str, Any]) -> None:
    """Usage lỗi không được làm hỏng response model đã sinh."""

    try:
        await repository.record_usage(event)
    except Exception:
        logger.exception(
            "Không thể ghi usage", extra={"request_id": event["request_id"]}
        )


@router.post("/chat/completions", response_model=None)
async def create_chat_completion(
    body: ChatCompletionRequest,
    request: Request,
    policy: ProjectPolicy = Depends(require_runtime_policy),
) -> JSONResponse | StreamingResponse:
    """Validate project policy rồi proxy request sang model backend."""

    container = get_container(request)
    if body.model not in policy.allowed_models:
        raise GatewayError(
            403,
            "Project không được phép sử dụng model này.",
            "permission_error",
            "model_not_allowed",
            param="model",
        )
    if body.input_character_count() > policy.max_input_characters:
        raise GatewayError(
            400,
            "Tổng nội dung messages vượt giới hạn project.",
            "invalid_request_error",
            "context_length_exceeded",
            param="messages",
        )
    if body.max_tokens is not None and body.max_tokens > policy.max_output_tokens:
        raise GatewayError(
            400,
            "max_tokens vượt giới hạn project.",
            "invalid_request_error",
            "max_tokens_exceeded",
            param="max_tokens",
        )

    request_id = request.state.request_id
    lease_id = f"{request_id}:{uuid4().hex}"
    try:
        # vLLM chỉ trả token thực tế sau response; reserve ước tính để chặn TPM từ đầu.
        estimated_tokens = max(1, body.input_character_count() // 4) + (
            body.max_tokens or policy.max_output_tokens
        )
        lease = await container.limiter.acquire(policy, lease_id, estimated_tokens)
    except Exception as exc:
        raise GatewayError(
            503,
            "Dịch vụ hạn mức tạm thời không khả dụng.",
            "server_error",
            "gateway_unavailable",
        ) from exc
    if lease is None:
        raise GatewayError(
            429,
            "API key hoặc project đã vượt hạn mức request, token hoặc concurrency.",
            "rate_limit_error",
            "rate_limit_exceeded",
            headers={"Retry-After": "60"},
        )

    upstream_name = container.settings.upstream.model_map.get(body.model)
    if upstream_name is None:
        await lease.release()
        raise GatewayError(
            503,
            "Model chưa có route khả dụng.",
            "server_error",
            "model_route_unavailable",
        )
    upstream_body = body.upstream_body(
        container.settings.security.safety_prompt, upstream_name
    )
    started = time.perf_counter()

    if body.stream:
        stream_iterator = container.upstream.stream(
            upstream_body, policy.timeout_seconds
        ).__aiter__()
        try:
            first_chunk = await anext(stream_iterator)
        except StopAsyncIteration:
            first_chunk = b""
        except GatewayError as exc:
            await lease.release()
            await _record_usage(
                container.repository,
                {
                    "request_id": request_id,
                    "project_id": policy.project_id,
                    "model": body.model,
                    "status_code": exc.status_code,
                    "latency_ms": int((time.perf_counter() - started) * 1000),
                },
            )
            raise

        async def generate() -> AsyncIterator[bytes]:
            status_code = 200
            try:
                if first_chunk:
                    yield first_chunk
                async for chunk in stream_iterator:
                    yield chunk
            except GatewayError as exc:
                status_code = exc.status_code
                logger.warning(
                    "Streaming upstream kết thúc lỗi",
                    extra={"request_id": request_id, "error_code": exc.code},
                )
            finally:
                close_stream = getattr(stream_iterator, "aclose", None)
                if close_stream is not None:
                    await close_stream()
                await lease.release()
                await _record_usage(
                    container.repository,
                    {
                        "request_id": request_id,
                        "project_id": policy.project_id,
                        "model": body.model,
                        "status_code": status_code,
                        "latency_ms": int((time.perf_counter() - started) * 1000),
                    },
                )

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "X-Request-Id": request_id,
                "Cache-Control": "no-store",
                "X-Accel-Buffering": "no",
            },
        )

    try:
        result = await container.upstream.complete(
            upstream_body, policy.timeout_seconds
        )
    except GatewayError as exc:
        await _record_usage(
            container.repository,
            {
                "request_id": request_id,
                "project_id": policy.project_id,
                "model": body.model,
                "status_code": exc.status_code,
                "latency_ms": int((time.perf_counter() - started) * 1000),
            },
        )
        raise
    finally:
        await lease.release()
    usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
    await _record_usage(
        container.repository,
        {
            "request_id": request_id,
            "project_id": policy.project_id,
            "model": body.model,
            "status_code": 200,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "total_tokens": usage.get("total_tokens"),
        },
    )
    return JSONResponse(
        result,
        headers={"X-Request-Id": request_id, "Cache-Control": "no-store"},
    )
