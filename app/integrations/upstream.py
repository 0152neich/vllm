"""OpenAI-compatible upstream adapter cho JSON và SSE."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.core.config import UpstreamSettings
from app.core.errors import GatewayError


class OpenAIUpstream:
    """Proxy tối thiểu, không phụ thuộc riêng vLLM hay SGLang."""

    def __init__(self, settings: UpstreamSettings) -> None:
        self._settings = settings
        self._base_url = str(settings.base_url).rstrip("/")
        limits = httpx.Limits(
            max_connections=settings.max_connections,
            max_keepalive_connections=settings.max_keepalive_connections,
        )
        self._client = httpx.AsyncClient(limits=limits)

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._settings.api_key:
            headers["Authorization"] = f"Bearer {self._settings.api_key}"
        return headers

    async def complete(
        self, body: dict[str, Any], timeout_seconds: float
    ) -> dict[str, Any]:
        """Gọi non-stream và chuẩn hóa lỗi dependency."""

        try:
            response = await self._client.post(
                f"{self._base_url}/chat/completions",
                headers=self._headers(),
                json=body,
                timeout=httpx.Timeout(
                    timeout_seconds,
                    connect=self._settings.connect_timeout_seconds,
                ),
            )
        except httpx.TimeoutException as exc:
            raise GatewayError(
                504,
                "Model backend quá thời gian phản hồi.",
                "server_error",
                "upstream_timeout",
            ) from exc
        except httpx.NetworkError as exc:
            raise GatewayError(
                502,
                "Model backend tạm thời không khả dụng.",
                "server_error",
                "upstream_error",
            ) from exc
        if response.status_code >= 400:
            status = 400 if response.status_code < 500 else 502
            raise GatewayError(
                status,
                "Model backend từ chối request."
                if status == 400
                else "Model backend gặp lỗi.",
                "invalid_request_error" if status == 400 else "server_error",
                "upstream_rejected" if status == 400 else "upstream_error",
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise GatewayError(
                502,
                "Model backend trả dữ liệu không hợp lệ.",
                "server_error",
                "invalid_upstream_response",
            ) from exc
        if not isinstance(payload, dict):
            raise GatewayError(
                502,
                "Model backend trả dữ liệu không hợp lệ.",
                "server_error",
                "invalid_upstream_response",
            )
        return payload

    async def stream(
        self, body: dict[str, Any], timeout_seconds: float
    ) -> AsyncIterator[bytes]:
        """Chuyển từng raw SSE chunk, không buffer toàn response."""

        try:
            async with self._client.stream(
                "POST",
                f"{self._base_url}/chat/completions",
                headers=self._headers(),
                json=body,
                timeout=httpx.Timeout(
                    timeout_seconds,
                    connect=self._settings.connect_timeout_seconds,
                ),
            ) as response:
                if response.status_code >= 400:
                    raise GatewayError(
                        502,
                        "Model backend từ chối streaming request.",
                        "server_error",
                        "upstream_error",
                    )
                async for chunk in response.aiter_raw():
                    yield chunk
        except httpx.TimeoutException as exc:
            raise GatewayError(
                504,
                "Model backend quá thời gian phản hồi.",
                "server_error",
                "upstream_timeout",
            ) from exc
        except httpx.NetworkError as exc:
            raise GatewayError(
                502,
                "Model backend tạm thời không khả dụng.",
                "server_error",
                "upstream_error",
            ) from exc

    async def is_ready(self) -> bool:
        try:
            response = await self._client.get(
                f"{self._base_url}/models",
                headers=self._headers(),
                timeout=self._settings.connect_timeout_seconds,
            )
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def close(self) -> None:
        await self._client.aclose()
