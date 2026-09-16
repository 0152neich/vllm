"""Contract tests cho OpenAI-compatible Chat Completions."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient

from app.core.errors import GatewayError

pytestmark = pytest.mark.anyio


def _body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": "qwen3-8b",
        "messages": [
            {"role": "system", "content": "Bạn là trợ lý VMS."},
            {"role": "user", "content": "Xin chào"},
        ],
        "temperature": 0.2,
        "max_tokens": 128,
    }
    body.update(overrides)
    return body


async def test_chat_without_api_key_returns_openai_401(client: AsyncClient) -> None:
    """Runtime endpoint bắt buộc Bearer key."""

    response = await client.post("/v1/chat/completions", json=_body())

    assert response.status_code == 401
    assert response.json()["error"]["type"] == "authentication_error"


async def test_chat_injects_safety_before_client_system_prompt(
    client: AsyncClient, gateway_components: dict[str, Any]
) -> None:
    """Safety prompt phải đứng trước prompt nghiệp vụ của client."""

    response = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer runtime-valid"},
        json=_body(),
    )

    assert response.status_code == 200
    forwarded = gateway_components["upstream"].bodies[0]
    assert forwarded["messages"][0]["role"] == "system"
    assert "hạ tầng" in forwarded["messages"][0]["content"]
    assert forwarded["messages"][1]["content"] == "Bạn là trợ lý VMS."


async def test_chat_model_outside_project_allowlist_returns_403(
    client: AsyncClient,
) -> None:
    """Project không thể gọi model ngoài allowlist."""

    response = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer runtime-valid"},
        json=_body(model="forbidden-model"),
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "model_not_allowed"


async def test_chat_with_tools_returns_unsupported_parameter(
    client: AsyncClient,
) -> None:
    """Gateway không nhận trách nhiệm tool calling."""

    response = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer runtime-valid"},
        json=_body(tools=[{"type": "function", "function": {"name": "camera_list"}}]),
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unsupported_parameter"


async def test_chat_over_project_output_limit_returns_400(client: AsyncClient) -> None:
    """Client không được vượt hard limit của project."""

    response = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer runtime-valid"},
        json=_body(max_tokens=2048),
    )

    assert response.status_code == 400
    assert response.json()["error"]["param"] == "max_tokens"


async def test_chat_rate_limited_returns_429(
    client: AsyncClient, gateway_components: dict[str, Any]
) -> None:
    """Limiter từ chối trước khi request tới upstream."""

    gateway_components["limiter"].allowed = False
    response = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer runtime-valid"},
        json=_body(),
    )

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "60"
    assert gateway_components["upstream"].bodies == []


async def test_chat_stream_proxies_sse_and_releases_lease(
    client: AsyncClient, gateway_components: dict[str, Any]
) -> None:
    """Streaming phải giữ contract SSE và giải phóng concurrency lease."""

    async with client.stream(
        "POST",
        "/v1/chat/completions",
        headers={"Authorization": "Bearer runtime-valid"},
        json=_body(stream=True),
    ) as response:
        payload = b"".join([chunk async for chunk in response.aiter_bytes()])

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert b"data: [DONE]" in payload
    assert gateway_components["limiter"].lease.released is True


async def test_chat_upstream_error_records_usage_and_releases_lease(
    client: AsyncClient, gateway_components: dict[str, Any]
) -> None:
    """Lỗi model vẫn phải giải phóng slot và ghi status usage."""

    async def fail(body: dict[str, Any], timeout_seconds: float) -> dict[str, Any]:
        del body, timeout_seconds
        raise GatewayError(502, "Model lỗi.", "server_error", "upstream_error")

    gateway_components["upstream"].complete = fail
    response = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer runtime-valid"},
        json=_body(),
    )

    assert response.status_code == 502
    assert gateway_components["limiter"].lease.released is True
    assert gateway_components["repository"].usage[0]["status_code"] == 502


async def test_chat_stream_error_before_first_chunk_returns_502(
    client: AsyncClient, gateway_components: dict[str, Any]
) -> None:
    """Lỗi trước chunk đầu phải giữ được HTTP status thay vì trả stream 200 rỗng."""

    async def fail_stream(body: dict[str, Any], timeout_seconds: float):
        del body, timeout_seconds
        raise GatewayError(502, "Model lỗi.", "server_error", "upstream_error")
        yield b""  # pragma: no cover - giữ hàm là async generator

    gateway_components["upstream"].stream = fail_stream
    response = await client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer runtime-valid"},
        json=_body(stream=True),
    )

    assert response.status_code == 502
    assert gateway_components["limiter"].lease.released is True
