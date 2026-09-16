"""Contract tests cho SQL repository bằng session doubles."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Self

import pytest
from sqlalchemy.exc import IntegrityError

from app.domain.management import ProjectNameConflictError
from app.repositories.database import ApiKey, Project, SqlRepository, UsageEvent

pytestmark = pytest.mark.anyio


class Result:
    def __init__(
        self,
        *,
        first: Any = None,
        rowcount: int = 1,
        scalar: Any = None,
        one: Any = None,
        rows: list[Any] | None = None,
    ) -> None:
        self._first = first
        self.rowcount = rowcount
        self._scalar = scalar
        self._one = one
        self._rows = rows or []

    def first(self) -> Any:
        return self._first

    def scalar_one_or_none(self) -> Any:
        return self._scalar

    def one(self) -> Any:
        return self._one

    def all(self) -> list[Any]:
        return self._rows


class Scalars:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows


class Session:
    def __init__(self) -> None:
        self.execute_results: list[Any] = []
        self.scalar_rows: list[list[Any]] = []
        self.get_results: list[Any] = []
        self.added: list[Any] = []
        self.commits = 0
        self.rollbacks = 0
        self.commit_error: Exception | None = None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def execute(self, statement: Any) -> Any:
        del statement
        return self.execute_results.pop(0) if self.execute_results else Result()

    async def scalars(self, statement: Any) -> Scalars:
        del statement
        return Scalars(self.scalar_rows.pop(0))

    async def get(self, model: Any, identity: str) -> Any:
        del model, identity
        return self.get_results.pop(0) if self.get_results else None

    def add(self, value: Any) -> None:
        self.added.append(value)

    async def commit(self) -> None:
        if self.commit_error is not None:
            raise self.commit_error
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    async def refresh(self, value: Any) -> None:
        if isinstance(value, Project):
            value.status = value.status or "active"
            value.version = value.version or 1
            value.created_at = value.created_at or datetime.now(timezone.utc)
            value.updated_at = value.updated_at or datetime.now(timezone.utc)


class Engine:
    def __init__(self) -> None:
        self.disposed = False

    async def dispose(self) -> None:
        self.disposed = True


def _project() -> Project:
    now = datetime.now(timezone.utc)
    return Project(
        id="p1",
        name="VMS",
        status="active",
        version=1,
        created_at=now,
        updated_at=now,
    )


def _repository(session: Session) -> tuple[SqlRepository, Engine]:
    engine = Engine()
    repository = object.__new__(SqlRepository)
    repository._engine = engine
    repository._sessions = lambda: session
    return repository, engine


async def test_repository_reads_key_projects_and_health() -> None:
    """Read paths phải chuyển ORM records thành domain-safe dictionaries."""

    session = Session()
    project = _project()
    key = ApiKey(
        id="k1",
        project_id="p1",
        kind="runtime",
        name="app",
        prefix="abc",
        digest="d" * 64,
        status="active",
        rpm=10,
        allowed_models=["qwen3-8b"],
        max_concurrency=2,
        max_input_characters=4000,
        max_output_tokens=1024,
        timeout_seconds=10,
    )
    session.execute_results = [Result(first=(key, project)), Result()]
    session.scalar_rows = [[project], ["abc"]]
    session.get_results = [project]
    repository, engine = _repository(session)

    stored = await repository.find_active_key("abc", "runtime")
    projects = await repository.list_projects("p1")
    found = await repository.get_project("p1")
    prefixes = await repository.list_active_key_prefixes("p1")
    ready = await repository.is_ready()
    await repository.close()

    assert stored is not None and stored.policy.project_name == "VMS"
    assert projects[0]["id"] == found["id"] == "p1"
    assert prefixes == ["abc"]
    assert ready is True and engine.disposed is True


async def test_repository_write_paths_and_conflict() -> None:
    """Write paths phải commit thành công và rollback optimistic conflict."""

    session = Session()
    project = _project()
    session.execute_results = [
        Result(rowcount=1),
        Result(rowcount=0),
        Result(scalar="abc"),
        Result(rowcount=1),
    ]
    session.get_results = [project]
    repository, _ = _repository(session)

    created = await repository.create_project(
        {"name": "New"}
    )
    updated = await repository.update_project("p1", 1, {"rpm": 20})
    conflict = await repository.update_project("p1", 1, {"rpm": 30})
    key = await repository.create_key("p1", "runtime", "app", "abc", "d" * 64, None)
    revoked = await repository.revoke_key("k1", "p1")
    await repository.record_audit("admin", "key.created", "k1", {})

    assert created["name"] == "New" and updated is not None
    assert conflict is None and key["prefix"] == "abc" and revoked == "abc"
    assert session.rollbacks == 1


async def test_create_project_rolls_back_and_translates_unique_violation() -> None:
    """IntegrityError khi insert project phải thành conflict domain an toàn."""

    session = Session()
    session.commit_error = IntegrityError("INSERT projects", {}, Exception("unique"))
    repository, _ = _repository(session)

    with pytest.raises(ProjectNameConflictError):
        await repository.create_project(
            {"name": "VMS"}
        )

    assert session.rollbacks == 1


async def test_repository_usage_paths() -> None:
    """Usage persistence chỉ trả metadata an toàn."""

    session = Session()
    now = datetime.now(timezone.utc)
    row = UsageEvent(
        id="u1",
        request_id="r1",
        project_id="p1",
        model="qwen3-8b",
        status_code=200,
        latency_ms=12,
        total_tokens=7,
        created_at=now,
    )
    session.scalar_rows = [[row]]
    repository, _ = _repository(session)

    await repository.record_usage(
        {
            "request_id": "r2",
            "project_id": "p1",
            "model": "qwen3-8b",
            "status_code": 200,
            "latency_ms": 10,
        }
    )
    usage = await repository.get_usage("p1", 10)

    assert usage[0]["request_id"] == "r1"
    assert "messages" not in usage[0]


async def test_repository_lists_key_metadata_without_digest() -> None:
    """Key serializer phải tính expiry và loại digest khỏi dữ liệu quản trị."""

    session = Session()
    key = ApiKey(
        id="k1",
        project_id="p1",
        kind="runtime",
        name="production",
        prefix="lgw_safe",
        digest="secret-digest",
        status="active",
        expires_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        created_at=datetime.now(timezone.utc),
    )
    session.scalar_rows = [[key]]
    repository, _ = _repository(session)

    rows = await repository.list_keys("p1", status="expired")

    assert rows[0]["status"] == "expired"
    assert "digest" not in rows[0]


async def test_repository_aggregates_key_and_usage_summaries() -> None:
    """Các aggregate rỗng hoặc null phải được chuẩn hóa thành số an toàn."""

    session = Session()
    now = datetime.now(timezone.utc)
    session.execute_results = [
        Result(one=(3, 1, 1, 1)),
        Result(one=(2, 1, 1, 5, 7, 12, 25.5)),
        Result(rows=[(now, 2, 12, 1, 25.5)]),
    ]
    repository, _ = _repository(session)

    keys = await repository.get_key_summary("p1")
    usage = await repository.get_usage_summary("p1", 24)

    assert keys == {"total": 3, "active": 1, "expired": 1, "revoked": 1}
    assert usage["totals"]["total_tokens"] == 12
    assert usage["series"][0]["errors"] == 1
