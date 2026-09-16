"""Acceptance tests cho health, model listing, UI và management edge cases."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.anyio


async def test_health_models_and_admin_assets_are_available(
    client: AsyncClient,
) -> None:
    """Các bề mặt vận hành chính phải truy cập được."""

    live = await client.get("/health/live")
    ready = await client.get("/health/ready")
    models = await client.get(
        "/v1/models", headers={"Authorization": "Bearer runtime-valid"}
    )
    html = await client.get("/admin")
    script = await client.get("/admin/app.js")
    module = await client.get("/admin/pages/overview.js")
    styles = await client.get("/admin/styles.css")
    rejected = await client.get("/admin/../../resources/configs/app.yaml")

    assert live.status_code == ready.status_code == models.status_code == 200
    assert models.json()["data"][0]["id"] == "qwen3-8b"
    assert (
        "LLM Gateway" in html.text
        and script.status_code == module.status_code == styles.status_code == 200
    )
    assert "default-src 'self'" in html.headers["content-security-policy"]
    assert rejected.status_code == 404


async def test_client_management_is_scoped_to_own_project(client: AsyncClient) -> None:
    """Client chỉ nhìn thấy project gắn với management key."""

    response = await client.get(
        "/management/v1/projects",
        headers={"Authorization": "Bearer management-vms"},
    )

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["data"]] == ["project-vms"]


async def test_management_update_conflict_and_unknown_model_are_rejected(
    client: AsyncClient,
) -> None:
    """Platform update phải kiểm tra model route và optimistic version."""

    headers = {"Authorization": "Bearer platform-admin"}
    unknown = await client.patch(
        "/management/v1/keys/key-vms",
        headers=headers,
        json={"version": 1, "allowed_models": ["unknown"]},
    )
    conflict = await client.patch(
        "/management/v1/projects/project-vms",
        headers=headers,
        json={"version": 99, "name": "VMS renamed"},
    )

    assert unknown.status_code == 400
    assert conflict.status_code == 409


async def test_client_cannot_issue_management_key_or_access_other_usage(
    client: AsyncClient,
) -> None:
    """Management key không được tự nhân bản quyền hoặc đọc project khác."""

    headers = {"Authorization": "Bearer management-vms"}
    issue = await client.post(
        "/management/v1/projects/project-vms/keys",
        headers=headers,
        json={"name": "escalation", "kind": "management"},
    )
    usage = await client.get(
        "/management/v1/projects/project-other/usage", headers=headers
    )

    assert issue.status_code == usage.status_code == 403


async def test_validation_and_context_limit_use_safe_error_envelope(
    client: AsyncClient, gateway_components: dict[str, Any]
) -> None:
    """Schema sai và input vượt project limit không được tới upstream."""

    headers = {"Authorization": "Bearer runtime-valid"}
    invalid = await client.post(
        "/v1/chat/completions",
        headers=headers,
        json={"model": "qwen3-8b", "messages": [], "unknown": True},
    )
    oversized = await client.post(
        "/v1/chat/completions",
        headers=headers,
        json={
            "model": "qwen3-8b",
            "messages": [{"role": "user", "content": "x" * 4001}],
        },
    )

    assert invalid.status_code == oversized.status_code == 400
    assert gateway_components["upstream"].bodies == []


async def test_management_update_revoke_usage_and_models_happy_paths(
    client: AsyncClient,
) -> None:
    """Các thao tác quản trị thường dùng phải hoạt động với Platform Admin."""

    headers = {"Authorization": "Bearer platform-admin"}
    updated = await client.patch(
        "/management/v1/keys/key-vms",
        headers=headers,
        json={"rpm": 20},
    )
    revoked = await client.post(
        "/management/v1/keys/key-created/revoke", headers=headers
    )
    usage = await client.get(
        "/management/v1/projects/project-vms/usage?limit=10", headers=headers
    )
    models = await client.get("/management/v1/models", headers=headers)

    assert updated.status_code == revoked.status_code == usage.status_code == 200
    assert models.json()["data"][0]["id"] == "qwen3-8b"


async def test_invalid_management_key_and_oversized_body_are_rejected(
    client: AsyncClient,
) -> None:
    """Management auth và global request size phải fail-closed."""

    unauthorized = await client.get(
        "/management/v1/projects",
        headers={"Authorization": "Bearer invalid"},
    )
    oversized = await client.post(
        "/v1/chat/completions",
        headers={
            "Authorization": "Bearer runtime-valid",
            "Content-Length": "100001",
            "Content-Type": "application/json",
        },
        content=b"{}",
    )

    assert unauthorized.status_code == 401
    assert oversized.status_code == 413
