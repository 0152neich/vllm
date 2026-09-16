"""Xác thực Bearer cho runtime và management endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.errors import authentication_error
from app.domain.auth import ManagementPrincipal, ProjectPolicy

bearer = HTTPBearer(auto_error=False)


def get_container(request: Request) -> Any:
    return request.app.state.container


async def require_runtime_policy(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> ProjectPolicy:
    """Xác thực runtime key mà không phân biệt key không tồn tại với key sai."""

    if credentials is None or credentials.scheme.casefold() != "bearer":
        raise authentication_error()
    policy = await get_container(request).auth_service.authenticate_runtime(
        credentials.credentials
    )
    if policy is None:
        raise authentication_error()
    return policy


async def require_management_principal(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> ManagementPrincipal:
    """Xác thực platform hoặc client management key."""

    if credentials is None or credentials.scheme.casefold() != "bearer":
        raise authentication_error()
    principal = await get_container(request).auth_service.authenticate_management(
        credentials.credentials
    )
    if principal is None:
        raise authentication_error()
    return principal
