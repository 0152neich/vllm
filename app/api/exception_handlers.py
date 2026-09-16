"""Chuẩn hóa lỗi API và che chi tiết nội bộ."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.errors import GatewayError


def register_exception_handlers(app: FastAPI) -> None:
    """Đăng ký OpenAI-style error envelope."""

    @app.exception_handler(GatewayError)
    async def handle_gateway_error(_: Request, exc: GatewayError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.envelope(),
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _: Request, exc: RequestValidationError
    ) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        location = first.get("loc", [])
        param = str(location[-1]) if location else None
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "message": "Dữ liệu request không hợp lệ.",
                    "type": "invalid_request_error",
                    "param": param,
                    "code": "validation_error",
                }
            },
        )
