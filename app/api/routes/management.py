"""Management API cho project, key, policy và usage."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request

from app.api.dependencies import get_container, require_management_principal
from app.core.errors import GatewayError
from app.domain.auth import ManagementPrincipal
from app.domain.management import (
    KeyCreate,
    KeyUpdate,
    ProjectCreate,
    ProjectNameConflictError,
    ProjectUpdate,
)

router = APIRouter(tags=["Management"])
logger = logging.getLogger(__name__)


def _actor(principal: ManagementPrincipal) -> str:
    return (
        principal.role
        if principal.project_id is None
        else f"project:{principal.project_id}"
    )


def _require_platform(principal: ManagementPrincipal) -> None:
    if principal.role != "platform_admin":
        raise GatewayError(
            403,
            "Chỉ Platform Admin được thực hiện thao tác này.",
            "permission_error",
            "forbidden",
        )


def _require_project_access(principal: ManagementPrincipal, project_id: str) -> None:
    if principal.role != "platform_admin" and principal.project_id != project_id:
        raise GatewayError(
            403, "Không có quyền truy cập project này.", "permission_error", "forbidden"
        )


def _project_scope(
    principal: ManagementPrincipal, requested_project_id: str | None
) -> str | None:
    """Resolve project scope và chặn Client Admin thay ID trên query string."""

    if principal.role == "platform_admin":
        return requested_project_id
    if requested_project_id is not None and requested_project_id != principal.project_id:
        raise GatewayError(
            403, "Không có quyền truy cập project này.", "permission_error", "forbidden"
        )
    return principal.project_id


@router.get("/projects")
async def list_projects(
    request: Request,
    principal: ManagementPrincipal = Depends(require_management_principal),
) -> dict[str, Any]:
    """Platform xem tất cả; client chỉ xem project của mình."""

    rows = await get_container(request).repository.list_projects(principal.project_id)
    return {"data": rows}


@router.get("/dashboard")
async def get_dashboard(
    request: Request,
    hours: int = Query(default=24, ge=1, le=2160),
    project_id: str | None = None,
    principal: ManagementPrincipal = Depends(require_management_principal),
) -> dict[str, Any]:
    """KPI tổng quan theo đúng project scope của principal."""

    container = get_container(request)
    scope = _project_scope(principal, project_id)
    projects, keys, usage = await asyncio.gather(
        container.repository.list_projects(scope),
        container.repository.get_key_summary(scope),
        container.repository.get_usage_summary(scope, hours),
    )
    project_statuses = {"active": 0, "suspended": 0, "archived": 0}
    for project in projects:
        status = project["status"]
        project_statuses[status] = project_statuses.get(status, 0) + 1
    return {
        "data": {
            "projects": {"total": len(projects), **project_statuses},
            "keys": keys,
            "usage": usage,
        }
    }


@router.get("/keys")
async def list_keys(
    request: Request,
    project_id: str | None = None,
    kind: Literal["runtime", "management"] | None = None,
    status: Literal["active", "expired", "revoked"] | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    principal: ManagementPrincipal = Depends(require_management_principal),
) -> dict[str, Any]:
    """Liệt kê metadata key trong scope; không bao giờ trả digest/plaintext."""

    scope = _project_scope(principal, project_id)
    rows = await get_container(request).repository.list_keys(
        scope, kind=kind, status=status, limit=limit
    )
    return {"data": rows}


@router.get("/usage/summary")
async def get_usage_summary(
    request: Request,
    hours: int = Query(default=24, ge=1, le=2160),
    project_id: str | None = None,
    principal: ManagementPrincipal = Depends(require_management_principal),
) -> dict[str, Any]:
    """Tổng hợp usage mà không đọc hoặc trả nội dung prompt."""

    scope = _project_scope(principal, project_id)
    return {
        "data": await get_container(request).repository.get_usage_summary(scope, hours)
    }


@router.get("/system/status")
async def get_system_status(
    request: Request,
    principal: ManagementPrincipal = Depends(require_management_principal),
) -> dict[str, Any]:
    """Trả cấu hình public và health dependency, tuyệt đối không trả secret/URL."""

    container = get_container(request)
    checks = await asyncio.gather(
        container.repository.is_ready(),
        container.limiter.is_ready(),
        container.upstream.is_ready(),
        return_exceptions=True,
    )
    names = ("database", "redis", "upstream")
    dependencies = {
        name: "ready" if result is True else "unavailable"
        for name, result in zip(names, checks, strict=True)
    }
    settings = container.settings
    return {
        "data": {
            "principal": {
                "role": principal.role,
                "project_id": principal.project_id,
            },
            "service": {
                "name": settings.service.name,
                "version": settings.service.version,
                "runtime_prefix": settings.service.runtime_prefix,
                "management_prefix": settings.service.management_prefix,
            },
            "models": [
                {"id": alias, "upstream_model": upstream}
                for alias, upstream in settings.upstream.model_map.items()
            ],
            "dependencies": dependencies,
            "status": (
                "ready"
                if all(value == "ready" for value in dependencies.values())
                else "degraded"
            ),
        }
    }


@router.post("/projects", status_code=201)
async def create_project(
    body: ProjectCreate,
    request: Request,
    principal: ManagementPrincipal = Depends(require_management_principal),
) -> dict[str, Any]:
    """Tạo project làm nhóm quản trị, không gán runtime quota."""

    _require_platform(principal)
    container = get_container(request)
    try:
        project = await container.repository.create_project(body.model_dump())
    except ProjectNameConflictError as exc:
        raise GatewayError(
            409,
            "Tên project đã tồn tại.",
            "conflict_error",
            "duplicate_project_name",
            param="name",
        ) from exc
    await container.repository.record_audit(
        _actor(principal), "project.created", project["id"], {"name": project["name"]}
    )
    return {"data": project}


@router.patch("/projects/{project_id}")
async def update_project(
    project_id: str,
    body: ProjectUpdate,
    request: Request,
    principal: ManagementPrincipal = Depends(require_management_principal),
) -> dict[str, Any]:
    """Platform cập nhật metadata và trạng thái project."""

    _require_platform(principal)
    values = body.model_dump(exclude_none=True, exclude={"version"})
    container = get_container(request)
    project = await container.repository.update_project(
        project_id, body.version, values
    )
    if project is None:
        raise GatewayError(
            409,
            "Project không tồn tại hoặc version đã thay đổi.",
            "conflict_error",
            "version_conflict",
        )
    await container.repository.record_audit(
        _actor(principal), "project.updated", project_id, {"fields": sorted(values)}
    )
    return {"data": project}


@router.delete("/projects/{project_id}", status_code=204)
async def delete_project(
    project_id: str,
    request: Request,
    principal: ManagementPrincipal = Depends(require_management_principal),
) -> None:
    """Xóa project không usage khi mọi API key của nó đã bị revoke."""

    _require_platform(principal)
    container = get_container(request)
    result = await container.repository.delete_empty_project(project_id)
    if result == "not_found":
        raise GatewayError(404, "Project không tồn tại.", "invalid_request_error", "not_found")
    if result == "not_empty":
        raise GatewayError(
            409,
            "Không thể xóa project còn usage hoặc API key chưa revoked.",
            "conflict_error",
            "project_not_empty",
        )
    await container.repository.record_audit(
        _actor(principal), "project.deleted", project_id, {}
    )


@router.post("/projects/{project_id}/keys", status_code=201)
async def create_key(
    project_id: str,
    body: KeyCreate,
    request: Request,
    principal: ManagementPrincipal = Depends(require_management_principal),
) -> dict[str, Any]:
    """Phát hành plaintext key đúng một lần."""

    _require_project_access(principal, project_id)
    if principal.role != "platform_admin" and (
        body.tpm is not None
        or body.rpm is not None
        or body.allowed_models is not None
        or body.max_concurrency is not None
        or body.max_input_characters is not None
        or body.max_output_tokens is not None
        or body.timeout_seconds is not None
        or body.metadata
        or body.tags
    ):
        raise GatewayError(
            403,
            "Chỉ Platform Admin được đặt settings theo API key.",
            "permission_error",
            "forbidden",
        )
    if body.kind == "management" and principal.role != "platform_admin":
        raise GatewayError(
            403,
            "Chỉ Platform Admin được cấp management key.",
            "permission_error",
            "forbidden",
        )
    container = get_container(request)
    project = await container.repository.get_project(project_id)
    if project is None:
        raise GatewayError(
            404, "Project không tồn tại.", "invalid_request_error", "not_found"
        )
    if project["status"] != "active":
        raise GatewayError(
            409,
            "Chỉ có thể cấp API key khi project đang active.",
            "conflict_error",
            "project_not_active",
            param="project_id",
        )
    defaults = container.settings.defaults
    allowed_models = body.allowed_models or defaults.allowed_models
    unknown_models = set(allowed_models) - set(container.settings.upstream.model_map)
    if unknown_models:
        raise GatewayError(
            400,
            "allowed_models chứa model chưa được cấu hình.",
            "invalid_request_error",
            "unknown_model",
            param="allowed_models",
        )
    issued = container.key_service.issue()
    record = await container.repository.create_key(
        project_id,
        body.kind,
        body.name,
        issued.prefix,
        issued.digest,
        body.expires_at,
        body.tpm,
        body.rpm or defaults.rpm,
        allowed_models,
        body.max_concurrency or defaults.max_concurrency,
        body.max_input_characters or defaults.max_input_characters,
        body.max_output_tokens or defaults.max_output_tokens,
        body.timeout_seconds or defaults.timeout_seconds,
        body.metadata,
        body.tags,
    )
    await container.repository.record_audit(
        _actor(principal),
        "key.created",
        record["id"],
        {
            "kind": body.kind,
            "prefix": issued.prefix,
            "tpm": body.tpm,
            "rpm": body.rpm or defaults.rpm,
            "allowed_models": allowed_models,
            "tags": body.tags,
        },
    )
    return {"data": {**record, "api_key": issued.plaintext}}


@router.get("/projects/{project_id}/keys")
async def list_project_keys(
    project_id: str,
    request: Request,
    limit: int = Query(default=100, ge=1, le=1000),
    principal: ManagementPrincipal = Depends(require_management_principal),
) -> dict[str, Any]:
    """Liệt kê metadata key của một project được phép truy cập."""

    _require_project_access(principal, project_id)
    return {
        "data": await get_container(request).repository.list_keys(
            project_id, limit=limit
        )
    }


@router.get("/keys/{key_id}")
async def get_key_detail(
    key_id: str,
    request: Request,
    principal: ManagementPrincipal = Depends(require_management_principal),
) -> dict[str, Any]:
    """Trả detail key an toàn trong đúng scope của principal."""

    scope = None if principal.role == "platform_admin" else principal.project_id
    key = await get_container(request).repository.get_key(key_id, scope)
    if key is None:
        raise GatewayError(404, "API key không tồn tại.", "invalid_request_error", "not_found")
    return {"data": key}


@router.patch("/keys/{key_id}")
async def update_key_settings(
    key_id: str,
    body: KeyUpdate,
    request: Request,
    principal: ManagementPrincipal = Depends(require_management_principal),
) -> dict[str, Any]:
    """Platform Admin cập nhật quota/metadata/tags mà không đụng credential."""

    _require_platform(principal)
    values = body.model_dump(exclude_unset=True)
    if not values:
        raise GatewayError(400, "Không có settings để cập nhật.", "invalid_request_error", "empty_update")
    container = get_container(request)
    if "allowed_models" in values:
        unknown_models = set(values["allowed_models"]) - set(
            container.settings.upstream.model_map
        )
        if unknown_models:
            raise GatewayError(
                400,
                "allowed_models chứa model chưa được cấu hình.",
                "invalid_request_error",
                "unknown_model",
                param="allowed_models",
            )
    current = await container.repository.get_key(key_id)
    if current is None:
        raise GatewayError(404, "API key không tồn tại.", "invalid_request_error", "not_found")
    updated = await container.repository.update_key_settings(key_id, values)
    if updated is None:
        raise GatewayError(404, "API key không tồn tại.", "invalid_request_error", "not_found")
    invalidate = getattr(container.limiter, "invalidate_key", None)
    if invalidate is not None:
        try:
            await invalidate(current["prefix"])
        except Exception:
            logger.warning("Không xóa được key policy cache", exc_info=True)
    await container.repository.record_audit(
        _actor(principal), "key.settings_updated", key_id, {"fields": sorted(values)}
    )
    return {"data": updated}


@router.post("/keys/{key_id}/revoke")
async def revoke_key(
    key_id: str,
    request: Request,
    principal: ManagementPrincipal = Depends(require_management_principal),
) -> dict[str, Any]:
    """Thu hồi key trong phạm vi principal."""

    container = get_container(request)
    revoked_prefix = await container.repository.revoke_key(key_id, principal.project_id)
    if revoked_prefix is None:
        raise GatewayError(
            404,
            "API key không tồn tại hoặc đã revoke.",
            "invalid_request_error",
            "not_found",
        )
    invalidate = getattr(container.limiter, "invalidate_key", None)
    if invalidate is not None:
        try:
            await invalidate(revoked_prefix)
        except Exception:
            logger.warning("Không xóa được revoked key cache", exc_info=True)
    await container.repository.record_audit(
        _actor(principal), "key.revoked", key_id, {}
    )
    return {"data": {"id": key_id, "status": "revoked"}}


@router.get("/projects/{project_id}/usage")
async def get_usage(
    project_id: str,
    request: Request,
    limit: int = 100,
    principal: ManagementPrincipal = Depends(require_management_principal),
) -> dict[str, Any]:
    """Trả usage metadata, không trả prompt."""

    _require_project_access(principal, project_id)
    safe_limit = max(1, min(limit, 1000))
    return {
        "data": await get_container(request).repository.get_usage(
            project_id, safe_limit
        )
    }


@router.get("/models")
async def list_models(
    request: Request,
    _: ManagementPrincipal = Depends(require_management_principal),
) -> dict[str, Any]:
    """Liệt kê public alias và upstream mapping cho UI."""

    model_map = get_container(request).settings.upstream.model_map
    return {
        "data": [
            {"id": public_name, "upstream_model": upstream_name}
            for public_name, upstream_name in model_map.items()
        ]
    }
