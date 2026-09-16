"""Fixtures tích hợp cho LLM Gateway."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.domain.auth import ManagementPrincipal, ProjectPolicy
from app.domain.management import ProjectNameConflictError
from app.main import create_app


class FakeAuthService:
    """Xác thực deterministic, không phụ thuộc PostgreSQL."""

    async def authenticate_runtime(self, token: str) -> ProjectPolicy | None:
        if token != "runtime-valid":
            return None
        return ProjectPolicy(
            project_id="project-vms",
            project_name="VMS",
            allowed_models=("qwen3-8b",),
            rpm=10,
            max_concurrency=2,
            max_input_characters=4000,
            max_output_tokens=1024,
            timeout_seconds=10,
        )

    async def authenticate_management(self, token: str) -> ManagementPrincipal | None:
        if token == "platform-admin":
            return ManagementPrincipal(role="platform_admin", project_id=None)
        if token == "management-vms":
            return ManagementPrincipal(role="client_admin", project_id="project-vms")
        return None


@dataclass
class FakeLease:
    """Lease ghi nhận việc giải phóng concurrency slot."""

    released: bool = False

    async def release(self) -> None:
        self.released = True


@dataclass
class FakeLimiter:
    """Limiter có thể chuyển sang trạng thái từ chối trong từng test."""

    allowed: bool = True
    lease: FakeLease = field(default_factory=FakeLease)

    async def acquire(
        self, policy: ProjectPolicy, request_id: str, estimated_tokens: int = 0
    ) -> FakeLease | None:
        del policy, request_id, estimated_tokens
        return self.lease if self.allowed else None

    async def is_ready(self) -> bool:
        return True


@dataclass
class FakeUpstream:
    """Upstream lưu request để test thứ tự prompt và passthrough."""

    bodies: list[dict[str, Any]] = field(default_factory=list)

    async def complete(
        self, body: dict[str, Any], timeout_seconds: float
    ) -> dict[str, Any]:
        del timeout_seconds
        self.bodies.append(body)
        return {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 1,
            "model": body["model"],
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "xin chào"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
        }

    async def stream(
        self, body: dict[str, Any], timeout_seconds: float
    ) -> AsyncIterator[bytes]:
        del timeout_seconds
        self.bodies.append(body)
        yield b'data: {"id":"chatcmpl-test","choices":[]}\n\n'
        yield b"data: [DONE]\n\n"

    async def is_ready(self) -> bool:
        return True

    async def close(self) -> None:
        return None


@dataclass
class FakeRepository:
    """Repository tối thiểu cho usage và health."""

    usage: list[dict[str, Any]] = field(default_factory=list)
    projects: dict[str, dict[str, Any]] = field(
        default_factory=lambda: {
            "project-vms": {
                "id": "project-vms",
                "name": "VMS",
                "status": "active",
                "version": 1,
            }
        }
    )
    created_key: dict[str, Any] | None = None
    keys: list[dict[str, Any]] = field(
        default_factory=lambda: [
            {
                "id": "key-vms",
                "project_id": "project-vms",
                "kind": "runtime",
                "name": "VMS production",
                "prefix": "lgw_vms",
                "status": "active",
                "expires_at": None,
                "tpm": None,
                "rpm": 60,
                "allowed_models": ["qwen3-8b"],
                "max_concurrency": 2,
                "max_input_characters": 20_000,
                "max_output_tokens": 1024,
                "timeout_seconds": 30,
                "metadata": {},
                "tags": [],
                "last_used_at": None,
                "created_at": None,
                "updated_at": None,
            }
        ]
    )

    async def record_usage(self, event: dict[str, Any]) -> None:
        self.usage.append(event)

    async def list_projects(
        self, project_id: str | None = None
    ) -> list[dict[str, Any]]:
        if project_id is None:
            return list(self.projects.values())
        return [self.projects[project_id]] if project_id in self.projects else []

    async def get_project(self, project_id: str) -> dict[str, Any] | None:
        return self.projects.get(project_id)

    async def list_active_key_prefixes(self, project_id: str) -> list[str]:
        del project_id
        return []

    async def create_project(self, values: dict[str, Any]) -> dict[str, Any]:
        if any(project["name"] == values["name"] for project in self.projects.values()):
            raise ProjectNameConflictError(values["name"])
        project = {"id": "project-created", "status": "active", "version": 1, **values}
        self.projects[project["id"]] = project
        return project

    async def update_project(
        self, project_id: str, expected_version: int, values: dict[str, Any]
    ) -> dict[str, Any] | None:
        project = self.projects.get(project_id)
        if project is None or project["version"] != expected_version:
            return None
        project.update(values)
        project["version"] += 1
        return project

    async def delete_empty_project(self, project_id: str) -> str:
        if project_id not in self.projects:
            return "not_found"
        if any(
            key["project_id"] == project_id and key["status"] != "revoked"
            for key in self.keys
        ) or any(
            event["project_id"] == project_id for event in self.usage
        ):
            return "not_empty"
        self.keys = [key for key in self.keys if key["project_id"] != project_id]
        del self.projects[project_id]
        return "deleted"

    async def create_key(
        self,
        project_id: str,
        kind: str,
        name: str,
        prefix: str,
        digest: str,
        expires_at: Any,
        tpm: int | None = None,
        rpm: int = 60,
        allowed_models: list[str] | None = None,
        max_concurrency: int = 2,
        max_input_characters: int = 20_000,
        max_output_tokens: int = 1024,
        timeout_seconds: float = 30,
        metadata: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        self.created_key = {
            "project_id": project_id,
            "kind": kind,
            "name": name,
            "prefix": prefix,
            "digest": digest,
            "expires_at": expires_at,
            "tpm": tpm,
            "rpm": rpm,
            "allowed_models": allowed_models or [],
            "max_concurrency": max_concurrency,
            "max_input_characters": max_input_characters,
            "max_output_tokens": max_output_tokens,
            "timeout_seconds": timeout_seconds,
            "metadata": metadata or {},
            "tags": tags or [],
        }
        return {
            "id": "key-created",
            "project_id": project_id,
            "kind": kind,
            "name": name,
            "prefix": prefix,
            "status": "active",
            "tpm": tpm,
            "rpm": rpm,
            "allowed_models": allowed_models or [],
            "max_concurrency": max_concurrency,
            "max_input_characters": max_input_characters,
            "max_output_tokens": max_output_tokens,
            "timeout_seconds": timeout_seconds,
            "metadata": metadata or {},
            "tags": tags or [],
        }

    async def get_key(
        self, key_id: str, project_id: str | None = None
    ) -> dict[str, Any] | None:
        for key in self.keys:
            if key["id"] == key_id and (
                project_id is None or key["project_id"] == project_id
            ):
                return key
        return None

    async def update_key_settings(
        self, key_id: str, values: dict[str, Any]
    ) -> dict[str, Any] | None:
        key = await self.get_key(key_id)
        if key is None:
            return None
        key.update(values)
        return key

    async def revoke_key(
        self, key_id: str, project_id: str | None = None
    ) -> str | None:
        del project_id
        return "fake-prefix" if key_id == "key-created" else None

    async def get_usage(self, project_id: str, limit: int) -> list[dict[str, Any]]:
        return [item for item in self.usage if item["project_id"] == project_id][:limit]

    async def list_keys(
        self,
        project_id: str | None = None,
        kind: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        rows = self.keys
        if project_id is not None:
            rows = [row for row in rows if row["project_id"] == project_id]
        if kind is not None:
            rows = [row for row in rows if row["kind"] == kind]
        if status is not None:
            rows = [row for row in rows if row["status"] == status]
        return rows[:limit]

    async def get_usage_summary(
        self, project_id: str | None, hours: int
    ) -> dict[str, Any]:
        rows = [
            item
            for item in self.usage
            if project_id is None or item["project_id"] == project_id
        ]
        total_tokens = sum(item.get("total_tokens") or 0 for item in rows)
        return {
            "period_hours": hours,
            "totals": {
                "requests": len(rows),
                "successful_requests": sum(
                    1 for item in rows if item["status_code"] < 400
                ),
                "failed_requests": sum(
                    1 for item in rows if item["status_code"] >= 400
                ),
                "prompt_tokens": sum(item.get("prompt_tokens") or 0 for item in rows),
                "completion_tokens": sum(
                    item.get("completion_tokens") or 0 for item in rows
                ),
                "total_tokens": total_tokens,
                "avg_latency_ms": (
                    round(sum(item["latency_ms"] for item in rows) / len(rows), 2)
                    if rows
                    else 0
                ),
            },
            "series": [],
        }

    async def get_key_summary(self, project_id: str | None) -> dict[str, int]:
        rows = [
            row
            for row in self.keys
            if project_id is None or row["project_id"] == project_id
        ]
        return {
            "total": len(rows),
            "active": sum(1 for row in rows if row["status"] == "active"),
            "expired": sum(1 for row in rows if row["status"] == "expired"),
            "revoked": sum(1 for row in rows if row["status"] == "revoked"),
        }

    async def record_audit(
        self, actor: str, action: str, target: str, details: dict[str, Any]
    ) -> None:
        del actor, action, target, details

    async def is_ready(self) -> bool:
        return True

    async def close(self) -> None:
        return None


@pytest.fixture
def gateway_components() -> dict[str, Any]:
    return {
        "settings": Settings.for_test(),
        "auth_service": FakeAuthService(),
        "limiter": FakeLimiter(),
        "upstream": FakeUpstream(),
        "repository": FakeRepository(),
    }


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def client(gateway_components: dict[str, Any]) -> AsyncIterator[AsyncClient]:
    app = create_app(**gateway_components)
    transport = ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=transport, base_url="http://test") as test_client,
    ):
        yield test_client
