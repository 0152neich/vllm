"""Integration tests cho quyền Management API."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient

from app.domain.management import KeyUpdate

pytestmark = pytest.mark.anyio


def _project_body() -> dict[str, Any]:
    return {"name": "Camera Analytics"}


def test_key_update_accepts_tags_and_metadata() -> None:
    """Schema update phải validate được trên mọi Pydantic 2.x runtime."""

    body = KeyUpdate.model_validate(
        {"tpm": 50_000, "metadata": {"owner": "vms"}, "tags": ["prod"]}
    )

    assert body.tags == ["prod"]
    assert body.metadata == {"owner": "vms"}


async def test_platform_admin_can_create_project(client: AsyncClient) -> None:
    """Project mới chỉ cần tên, không mang runtime policy."""

    response = await client.post(
        "/management/v1/projects",
        headers={"Authorization": "Bearer platform-admin"},
        json=_project_body(),
    )

    assert response.status_code == 201
    assert response.json()["data"]["name"] == "Camera Analytics"
    assert "allowed_models" not in response.json()["data"]


async def test_duplicate_project_name_returns_conflict(client: AsyncClient) -> None:
    """Tên project trùng phải trả lỗi nghiệp vụ thay vì làm API crash 500."""

    body = _project_body()
    body["name"] = "VMS"

    response = await client.post(
        "/management/v1/projects",
        headers={"Authorization": "Bearer platform-admin"},
        json=body,
    )

    assert response.status_code == 409
    assert response.json()["error"] == {
        "message": "Tên project đã tồn tại.",
        "type": "conflict_error",
        "param": "name",
        "code": "duplicate_project_name",
    }


async def test_client_admin_cannot_update_project(client: AsyncClient) -> None:
    """Client management key không được đổi trạng thái project."""

    response = await client.patch(
        "/management/v1/projects/project-vms",
        headers={"Authorization": "Bearer management-vms"},
        json={"version": 1, "status": "suspended"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


async def test_platform_admin_can_delete_an_empty_project(client: AsyncClient) -> None:
    """Chỉ project không có key/usage mới được hard-delete."""

    created = await client.post(
        "/management/v1/projects",
        headers={"Authorization": "Bearer platform-admin"},
        json=_project_body(),
    )
    project_id = created.json()["data"]["id"]
    deleted = await client.delete(
        f"/management/v1/projects/{project_id}",
        headers={"Authorization": "Bearer platform-admin"},
    )

    assert deleted.status_code == 204
    assert (await client.get("/management/v1/projects", headers={"Authorization": "Bearer platform-admin"})).json()["data"] == [
        {
            "id": "project-vms", "name": "VMS", "status": "active",
            "version": 1,
        }
    ]


async def test_delete_project_with_keys_or_usage_is_rejected(client: AsyncClient) -> None:
    """Không được hard-delete project còn dữ liệu vận hành."""

    response = await client.delete(
        "/management/v1/projects/project-vms",
        headers={"Authorization": "Bearer platform-admin"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "project_not_empty"


async def test_platform_admin_can_delete_project_when_all_keys_are_revoked(
    client: AsyncClient, gateway_components: dict[str, Any]
) -> None:
    """Key đã revoke không giữ project lại nếu project chưa có usage."""

    gateway_components["repository"].keys[0]["status"] = "revoked"

    response = await client.delete(
        "/management/v1/projects/project-vms",
        headers={"Authorization": "Bearer platform-admin"},
    )

    assert response.status_code == 204
    assert "project-vms" not in gateway_components["repository"].projects
    assert gateway_components["repository"].keys == []


async def test_client_admin_cannot_delete_project(client: AsyncClient) -> None:
    """Client Admin không được xóa project của mình hay project khác."""

    response = await client.delete(
        "/management/v1/projects/project-vms",
        headers={"Authorization": "Bearer management-vms"},
    )

    assert response.status_code == 403


async def test_runtime_key_plaintext_is_returned_once_but_repository_receives_digest(
    client: AsyncClient, gateway_components: dict[str, Any]
) -> None:
    """Management response trả secret một lần; persistence chỉ nhận digest."""

    response = await client.post(
        "/management/v1/projects/project-vms/keys",
        headers={"Authorization": "Bearer management-vms"},
        json={"name": "VMS production", "kind": "runtime"},
    )

    plaintext = response.json()["data"]["api_key"]
    persisted = gateway_components["repository"].created_key
    assert response.status_code == 201
    assert plaintext.startswith("lgw_")
    assert persisted is not None and persisted["digest"] != plaintext


async def test_platform_admin_can_create_key_with_optional_key_settings(
    client: AsyncClient, gateway_components: dict[str, Any]
) -> None:
    """Settings per-key phải được validate, persist và trả metadata an toàn."""

    response = await client.post(
        "/management/v1/projects/project-vms/keys",
        headers={"Authorization": "Bearer platform-admin"},
        json={
            "name": "VMS burst",
            "kind": "runtime",
            "tpm": 120_000,
            "rpm": 600,
            "allowed_models": ["qwen3-8b"],
            "max_concurrency": 4,
            "max_input_characters": 12_000,
            "max_output_tokens": 2_048,
            "timeout_seconds": 45,
            "metadata": {"environment": "prod", "owner": "vms"},
            "tags": ["production", "vms"],
        },
    )

    assert response.status_code == 201
    assert response.json()["data"]["tpm"] == 120_000
    assert response.json()["data"]["max_output_tokens"] == 2_048
    assert response.json()["data"]["tags"] == ["production", "vms"]
    assert gateway_components["repository"].created_key is not None
    assert gateway_components["repository"].created_key["tpm"] == 120_000
    assert gateway_components["repository"].created_key["allowed_models"] == ["qwen3-8b"]
    assert gateway_components["repository"].created_key["metadata"] == {
        "environment": "prod",
        "owner": "vms",
    }


async def test_key_settings_are_platform_only_and_key_detail_is_scoped(
    client: AsyncClient,
) -> None:
    """Client Admin xem được detail scope mình nhưng không được sửa quota hay tags."""

    detail = await client.get(
        "/management/v1/keys/key-vms",
        headers={"Authorization": "Bearer management-vms"},
    )
    denied = await client.patch(
        "/management/v1/keys/key-vms",
        headers={"Authorization": "Bearer management-vms"},
        json={"tpm": 120_000, "tags": ["prod"]},
    )

    assert detail.status_code == 200
    assert detail.json()["data"]["id"] == "key-vms"
    assert denied.status_code == 403


async def test_client_admin_cannot_create_key_with_key_level_settings(
    client: AsyncClient,
) -> None:
    """Client Admin có thể cấp key thường nhưng không tự tăng quota qua create."""

    response = await client.post(
        "/management/v1/projects/project-vms/keys",
        headers={"Authorization": "Bearer management-vms"},
        json={"name": "self-escalation", "rpm": 500},
    )

    assert response.status_code == 403


async def test_platform_admin_can_update_key_settings_and_invalidate_cache(
    client: AsyncClient, gateway_components: dict[str, Any]
) -> None:
    """Platform update settings của key, không thay đổi plaintext hay credential."""

    response = await client.patch(
        "/management/v1/keys/key-vms",
        headers={"Authorization": "Bearer platform-admin"},
        json={"rpm": 500, "metadata": {"team": "platform"}, "tags": ["priority"]},
    )

    assert response.status_code == 200
    assert response.json()["data"]["rpm"] == 500
    assert gateway_components["repository"].keys[0]["tags"] == ["priority"]


@pytest.mark.parametrize("status", ["suspended", "archived"])
async def test_cannot_create_key_for_inactive_project(
    client: AsyncClient, gateway_components: dict[str, Any], status: str
) -> None:
    """Project không active không được phát hành thêm bất kỳ API key nào."""

    gateway_components["repository"].projects["project-vms"]["status"] = status

    response = await client.post(
        "/management/v1/projects/project-vms/keys",
        headers={"Authorization": "Bearer platform-admin"},
        json={"name": "blocked-key", "kind": "runtime"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "project_not_active"
    assert gateway_components["repository"].created_key is None


async def test_platform_admin_lists_safe_key_metadata(client: AsyncClient) -> None:
    """Danh sách key không được trả plaintext hoặc digest."""

    response = await client.get(
        "/management/v1/keys",
        headers={"Authorization": "Bearer platform-admin"},
    )

    assert response.status_code == 200
    payload = response.json()["data"][0]
    assert payload["prefix"] == "lgw_vms"
    assert "api_key" not in payload and "digest" not in payload


async def test_client_admin_cannot_list_another_project_keys(
    client: AsyncClient,
) -> None:
    """Project scope phải được kiểm tra ở backend thay vì chỉ lọc trên UI."""

    response = await client.get(
        "/management/v1/keys?project_id=project-other",
        headers={"Authorization": "Bearer management-vms"},
    )

    assert response.status_code == 403


async def test_usage_summary_uses_principal_project_scope(
    client: AsyncClient, gateway_components: dict[str, Any]
) -> None:
    """Client Admin chỉ nhận usage thuộc project của mình."""

    gateway_components["repository"].usage.extend(
        [
            {
                "request_id": "vms-request",
                "project_id": "project-vms",
                "model": "qwen3-8b",
                "status_code": 200,
                "latency_ms": 20,
                "total_tokens": 10,
            },
            {
                "request_id": "other-request",
                "project_id": "project-other",
                "model": "qwen3-8b",
                "status_code": 500,
                "latency_ms": 40,
                "total_tokens": 30,
            },
        ]
    )

    response = await client.get(
        "/management/v1/usage/summary?hours=24",
        headers={"Authorization": "Bearer management-vms"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["totals"]["requests"] == 1
    assert response.json()["data"]["totals"]["total_tokens"] == 10


async def test_dashboard_returns_real_zero_safe_aggregates(
    client: AsyncClient,
) -> None:
    """Dashboard rỗng phải trả số 0 và metadata project/key thật."""

    response = await client.get(
        "/management/v1/dashboard?hours=24",
        headers={"Authorization": "Bearer platform-admin"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["projects"]["total"] == 1
    assert data["keys"]["active"] == 1
    assert data["usage"]["totals"]["requests"] == 0


async def test_system_status_only_exposes_safe_configuration(
    client: AsyncClient,
) -> None:
    """System status không được lộ URL kết nối hoặc secret."""

    response = await client.get(
        "/management/v1/system/status",
        headers={"Authorization": "Bearer platform-admin"},
    )

    assert response.status_code == 200
    body = response.json()
    serialized = response.text
    assert body["data"]["service"]["version"] == "test"
    assert body["data"]["principal"] == {
        "role": "platform_admin",
        "project_id": None,
    }
    assert body["data"]["dependencies"]["database"] == "ready"
    assert "test-pepper" not in serialized
    assert "platform-admin-test-key" not in serialized
    assert "redis.test" not in serialized


async def test_client_status_identifies_project_scope(client: AsyncClient) -> None:
    """UI phải biết role để không hiện thao tác Platform Admin cho client."""

    response = await client.get(
        "/management/v1/system/status",
        headers={"Authorization": "Bearer management-vms"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["principal"] == {
        "role": "client_admin",
        "project_id": "project-vms",
    }


async def test_summary_rejects_period_outside_supported_range(
    client: AsyncClient,
) -> None:
    """Khoảng thống kê ngoài 1-2160 giờ phải bị validation từ chối."""

    response = await client.get(
        "/management/v1/usage/summary?hours=0",
        headers={"Authorization": "Bearer platform-admin"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["param"] == "hours"
