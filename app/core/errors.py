"""Lỗi nghiệp vụ theo envelope tương thích OpenAI."""

from __future__ import annotations

from typing import Any


class GatewayError(Exception):
    """Lỗi an toàn có thể trả về client."""

    def __init__(
        self,
        status_code: int,
        message: str,
        error_type: str,
        code: str,
        *,
        param: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.error_type = error_type
        self.code = code
        self.param = param
        self.headers = headers or {}

    def envelope(self) -> dict[str, dict[str, Any]]:
        """Tạo body lỗi không chứa chi tiết nội bộ."""

        return {
            "error": {
                "message": self.message,
                "type": self.error_type,
                "param": self.param,
                "code": self.code,
            }
        }


def authentication_error() -> GatewayError:
    return GatewayError(
        401,
        "API key không hợp lệ hoặc đã hết hiệu lực.",
        "authentication_error",
        "invalid_api_key",
    )
