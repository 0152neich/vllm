"""SQLAlchemy models và repository PostgreSQL."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    case,
    delete,
    func,
    select,
    update,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.core.config import DatabaseSettings
from app.domain.auth import ProjectPolicy
from app.domain.management import ProjectNameConflictError


def utc_now() -> datetime:
    """Sinh timestamp UTC có timezone."""

    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Base metadata cho migration và test."""


class Project(Base):
    """Nhóm quản trị và trạng thái của các API key."""

    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    keys: Mapped[list[ApiKey]] = relationship(back_populates="project")


class ApiKey(Base):
    """Chỉ lưu prefix và HMAC digest của API key."""

    __tablename__ = "api_keys"
    __table_args__ = (
        Index(
            "ix_api_keys_project_status_created",
            "project_id",
            "status",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20), index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    prefix: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tpm: Mapped[int | None] = mapped_column(Integer)
    rpm: Mapped[int] = mapped_column(Integer, nullable=False)
    allowed_models: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    max_concurrency: Mapped[int] = mapped_column(Integer, nullable=False)
    max_input_characters: Mapped[int] = mapped_column(Integer, nullable=False)
    max_output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    timeout_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    project: Mapped[Project] = relationship(back_populates="keys")


class UsageEvent(Base):
    """Metadata usage không chứa prompt hoặc secret."""

    __tablename__ = "usage_events"
    __table_args__ = (
        Index("ix_usage_events_created_at", "created_at"),
        Index("ix_usage_events_project_created", "project_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(64), index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    total_tokens: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class AuditEvent(Base):
    """Audit cho thao tác quản trị."""

    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    actor: Mapped[str] = mapped_column(String(120), nullable=False)
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    target: Mapped[str] = mapped_column(String(120), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


@dataclass(frozen=True)
class StoredApiKey:
    """Key record nội bộ sau khi join project."""

    key_id: str
    digest: str
    policy: ProjectPolicy
    expires_at: datetime | None = None


def key_to_policy(key: ApiKey, project: Project) -> ProjectPolicy:
    """Resolve policy runtime trực tiếp từ API key đã xác thực."""

    return ProjectPolicy(
        project_id=project.id,
        project_name=project.name,
        allowed_models=tuple(key.allowed_models),
        rpm=key.rpm,
        max_concurrency=key.max_concurrency,
        max_input_characters=key.max_input_characters,
        max_output_tokens=key.max_output_tokens,
        timeout_seconds=key.timeout_seconds,
        key_id=key.id,
        key_prefix=key.prefix,
        tpm=key.tpm,
        rpm_overridden=True,
    )


def project_to_dict(project: Project) -> dict[str, Any]:
    return {
        "id": project.id,
        "name": project.name,
        "status": project.status,
        "version": project.version,
        "created_at": project.created_at,
        "updated_at": project.updated_at,
    }


def key_to_dict(key: ApiKey) -> dict[str, Any]:
    """Chuyển API key thành metadata an toàn, tuyệt đối không trả digest."""

    effective_status = key.status
    if (
        effective_status == "active"
        and key.expires_at is not None
        and key.expires_at <= utc_now()
    ):
        effective_status = "expired"
    return {
        "id": key.id,
        "project_id": key.project_id,
        "kind": key.kind,
        "name": key.name,
        "prefix": key.prefix,
        "status": effective_status,
        "expires_at": key.expires_at,
        "tpm": key.tpm,
        "rpm": key.rpm,
        "allowed_models": key.allowed_models,
        "max_concurrency": key.max_concurrency,
        "max_input_characters": key.max_input_characters,
        "max_output_tokens": key.max_output_tokens,
        "timeout_seconds": key.timeout_seconds,
        "metadata": key.metadata_json or {},
        "tags": key.tags or [],
        "last_used_at": key.last_used_at,
        "created_at": key.created_at,
        "updated_at": key.updated_at,
    }


class SqlRepository:
    """Repository nhỏ gọn, transaction tại từng management operation."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def initialize(self, auto_create_schema: bool) -> None:
        if auto_create_schema:
            async with self._engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)

    async def find_active_key(self, prefix: str, kind: str) -> StoredApiKey | None:
        async with self._sessions() as session:
            result = await session.execute(
                select(ApiKey, Project)
                .join(Project, ApiKey.project_id == Project.id)
                .where(
                    ApiKey.prefix == prefix,
                    ApiKey.kind == kind,
                    ApiKey.status == "active",
                    Project.status == "active",
                )
            )
            row = result.first()
            if row is None:
                return None
            key, project = row
            if key.expires_at is not None and key.expires_at <= utc_now():
                return None
            return StoredApiKey(
                key.id,
                key.digest,
                key_to_policy(key, project),
                key.expires_at,
            )

    async def touch_key(self, key_id: str) -> None:
        async with self._sessions() as session:
            await session.execute(
                update(ApiKey).where(ApiKey.id == key_id).values(last_used_at=utc_now())
            )
            await session.commit()

    async def list_projects(
        self, project_id: str | None = None
    ) -> list[dict[str, Any]]:
        async with self._sessions() as session:
            statement = select(Project).order_by(Project.created_at.desc())
            if project_id is not None:
                statement = statement.where(Project.id == project_id)
            rows = (await session.scalars(statement)).all()
            return [project_to_dict(row) for row in rows]

    async def get_project(self, project_id: str) -> dict[str, Any] | None:
        async with self._sessions() as session:
            project = await session.get(Project, project_id)
            return project_to_dict(project) if project else None

    async def get_key(
        self, key_id: str, project_id: str | None = None
    ) -> dict[str, Any] | None:
        """Đọc metadata key theo project scope; không trả digest/plaintext."""

        async with self._sessions() as session:
            statement = select(ApiKey).where(ApiKey.id == key_id)
            if project_id is not None:
                statement = statement.where(ApiKey.project_id == project_id)
            key = (await session.scalars(statement)).one_or_none()
            return key_to_dict(key) if key else None

    async def list_active_key_prefixes(self, project_id: str) -> list[str]:
        """Lấy prefix để chủ động xóa policy cache khi project đổi."""

        async with self._sessions() as session:
            rows = await session.scalars(
                select(ApiKey.prefix).where(
                    ApiKey.project_id == project_id, ApiKey.status == "active"
                )
            )
            return [str(prefix) for prefix in rows.all()]

    async def create_project(self, values: dict[str, Any]) -> dict[str, Any]:
        project = Project(id=str(uuid4()), **values)
        async with self._sessions() as session:
            session.add(project)
            try:
                await session.commit()
            except IntegrityError as exc:
                # Constraint DB là lớp bảo vệ cuối cùng khi nhiều request tạo
                # cùng tên đồng thời; pre-check riêng sẽ vẫn có race condition.
                await session.rollback()
                raise ProjectNameConflictError(values["name"]) from exc
            await session.refresh(project)
            return project_to_dict(project)

    async def update_project(
        self, project_id: str, expected_version: int, values: dict[str, Any]
    ) -> dict[str, Any] | None:
        async with self._sessions() as session:
            result = await session.execute(
                update(Project)
                .where(Project.id == project_id, Project.version == expected_version)
                .values(**values, version=expected_version + 1, updated_at=utc_now())
            )
            if result.rowcount != 1:
                await session.rollback()
                return None
            await session.commit()
            project = await session.get(Project, project_id)
            return project_to_dict(project) if project else None

    async def delete_empty_project(self, project_id: str) -> str:
        """Xóa project không usage khi mọi key đã được revoke."""

        async with self._sessions() as session:
            project = await session.get(Project, project_id)
            if project is None:
                return "not_found"
            has_non_revoked_key = (await session.scalars(
                select(ApiKey.id)
                .where(
                    ApiKey.project_id == project_id,
                    ApiKey.status != "revoked",
                )
                .limit(1)
            )).first() is not None
            has_usage = (await session.scalars(
                select(UsageEvent.id).where(UsageEvent.project_id == project_id).limit(1)
            )).first() is not None
            if has_non_revoked_key or has_usage:
                return "not_empty"
            # Mọi key còn lại đều đã bị revoke nên có thể dọn cùng project.
            await session.execute(
                delete(ApiKey).where(
                    ApiKey.project_id == project_id,
                    ApiKey.status == "revoked",
                )
            )
            await session.execute(delete(Project).where(Project.id == project_id))
            await session.commit()
            return "deleted"

    async def create_key(
        self,
        project_id: str,
        kind: str,
        name: str,
        prefix: str,
        digest: str,
        expires_at: datetime | None,
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
        record = ApiKey(
            id=str(uuid4()),
            project_id=project_id,
            kind=kind,
            name=name,
            prefix=prefix,
            digest=digest,
            expires_at=expires_at,
            tpm=tpm,
            rpm=rpm,
            allowed_models=allowed_models or [],
            max_concurrency=max_concurrency,
            max_input_characters=max_input_characters,
            max_output_tokens=max_output_tokens,
            timeout_seconds=timeout_seconds,
            metadata_json=metadata or {},
            tags=tags or [],
        )
        async with self._sessions() as session:
            session.add(record)
            await session.commit()
            await session.refresh(record)
            return key_to_dict(record)

    async def update_key_settings(
        self, key_id: str, values: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Cập nhật settings mutable, map metadata API sang tên ORM an toàn."""

        update_values = dict(values)
        if "metadata" in update_values:
            update_values["metadata_json"] = update_values.pop("metadata")
        update_values["updated_at"] = utc_now()
        async with self._sessions() as session:
            result = await session.execute(
                update(ApiKey).where(ApiKey.id == key_id).values(**update_values)
            )
            if result.rowcount != 1:
                await session.rollback()
                return None
            await session.commit()
            record = await session.get(ApiKey, key_id)
            return key_to_dict(record) if record else None

    async def list_keys(
        self,
        project_id: str | None = None,
        kind: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Liệt kê metadata key theo scope mà không đọc cột digest ra response."""

        async with self._sessions() as session:
            statement = select(ApiKey).order_by(ApiKey.created_at.desc())
            if project_id is not None:
                statement = statement.where(ApiKey.project_id == project_id)
            if kind is not None:
                statement = statement.where(ApiKey.kind == kind)
            if status == "active":
                statement = statement.where(
                    ApiKey.status == "active",
                    (ApiKey.expires_at.is_(None)) | (ApiKey.expires_at > utc_now()),
                )
            elif status == "expired":
                statement = statement.where(
                    ApiKey.status == "active",
                    ApiKey.expires_at.is_not(None),
                    ApiKey.expires_at <= utc_now(),
                )
            elif status == "revoked":
                statement = statement.where(ApiKey.status == "revoked")
            statement = statement.limit(limit)
            rows = (await session.scalars(statement)).all()
            return [key_to_dict(row) for row in rows]

    async def get_key_summary(self, project_id: str | None = None) -> dict[str, int]:
        """Đếm trạng thái key, coi key active quá hạn là expired."""

        now = utc_now()
        active_condition = (
            (ApiKey.status == "active")
            & ((ApiKey.expires_at.is_(None)) | (ApiKey.expires_at > now))
        )
        expired_condition = (
            (ApiKey.status == "active")
            & ApiKey.expires_at.is_not(None)
            & (ApiKey.expires_at <= now)
        )
        statement = select(
            func.count(ApiKey.id),
            func.coalesce(func.sum(case((active_condition, 1), else_=0)), 0),
            func.coalesce(func.sum(case((expired_condition, 1), else_=0)), 0),
            func.coalesce(
                func.sum(case((ApiKey.status == "revoked", 1), else_=0)), 0
            ),
        )
        if project_id is not None:
            statement = statement.where(ApiKey.project_id == project_id)
        async with self._sessions() as session:
            total, active, expired, revoked = (await session.execute(statement)).one()
        return {
            "total": int(total or 0),
            "active": int(active or 0),
            "expired": int(expired or 0),
            "revoked": int(revoked or 0),
        }

    async def revoke_key(
        self, key_id: str, project_id: str | None = None
    ) -> str | None:
        async with self._sessions() as session:
            lookup = select(ApiKey.prefix).where(
                ApiKey.id == key_id, ApiKey.status == "active"
            )
            if project_id is not None:
                lookup = lookup.where(ApiKey.project_id == project_id)
            prefix = (await session.execute(lookup)).scalar_one_or_none()
            if prefix is None:
                return None
            await session.execute(
                update(ApiKey).where(ApiKey.id == key_id).values(status="revoked")
            )
            await session.commit()
            return str(prefix)

    async def record_usage(self, event: dict[str, Any]) -> None:
        async with self._sessions() as session:
            session.add(UsageEvent(id=str(uuid4()), **event))
            await session.commit()

    async def get_usage(
        self, project_id: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        async with self._sessions() as session:
            rows = (
                await session.scalars(
                    select(UsageEvent)
                    .where(UsageEvent.project_id == project_id)
                    .order_by(UsageEvent.created_at.desc())
                    .limit(limit)
                )
            ).all()
            return [
                {
                    "request_id": row.request_id,
                    "model": row.model,
                    "status_code": row.status_code,
                    "latency_ms": row.latency_ms,
                    "prompt_tokens": row.prompt_tokens,
                    "completion_tokens": row.completion_tokens,
                    "total_tokens": row.total_tokens,
                    "created_at": row.created_at,
                }
                for row in rows
            ]

    async def get_usage_summary(
        self, project_id: str | None, hours: int
    ) -> dict[str, Any]:
        """Tổng hợp KPI và chuỗi thời gian theo giờ ngay tại PostgreSQL."""

        since = utc_now() - timedelta(hours=hours)
        filters = [UsageEvent.created_at >= since]
        if project_id is not None:
            filters.append(UsageEvent.project_id == project_id)
        totals_statement = select(
            func.count(UsageEvent.id),
            func.coalesce(
                func.sum(case((UsageEvent.status_code < 400, 1), else_=0)), 0
            ),
            func.coalesce(
                func.sum(case((UsageEvent.status_code >= 400, 1), else_=0)), 0
            ),
            func.coalesce(func.sum(UsageEvent.prompt_tokens), 0),
            func.coalesce(func.sum(UsageEvent.completion_tokens), 0),
            func.coalesce(func.sum(UsageEvent.total_tokens), 0),
            func.coalesce(func.avg(UsageEvent.latency_ms), 0),
        ).where(*filters)
        bucket = func.date_trunc("hour", UsageEvent.created_at).label("bucket")
        series_statement = (
            select(
                bucket,
                func.count(UsageEvent.id),
                func.coalesce(func.sum(UsageEvent.total_tokens), 0),
                func.coalesce(
                    func.sum(case((UsageEvent.status_code >= 400, 1), else_=0)), 0
                ),
                func.coalesce(func.avg(UsageEvent.latency_ms), 0),
            )
            .where(*filters)
            .group_by(bucket)
            .order_by(bucket)
        )
        async with self._sessions() as session:
            totals = (await session.execute(totals_statement)).one()
            series = (await session.execute(series_statement)).all()
        return {
            "period_hours": hours,
            "totals": {
                "requests": int(totals[0] or 0),
                "successful_requests": int(totals[1] or 0),
                "failed_requests": int(totals[2] or 0),
                "prompt_tokens": int(totals[3] or 0),
                "completion_tokens": int(totals[4] or 0),
                "total_tokens": int(totals[5] or 0),
                "avg_latency_ms": round(float(totals[6] or 0), 2),
            },
            "series": [
                {
                    "bucket": row[0],
                    "requests": int(row[1] or 0),
                    "total_tokens": int(row[2] or 0),
                    "errors": int(row[3] or 0),
                    "avg_latency_ms": round(float(row[4] or 0), 2),
                }
                for row in series
            ],
        }

    async def record_audit(
        self, actor: str, action: str, target: str, details: dict[str, Any]
    ) -> None:
        async with self._sessions() as session:
            session.add(
                AuditEvent(
                    id=str(uuid4()),
                    actor=actor,
                    action=action,
                    target=target,
                    details=details,
                )
            )
            await session.commit()

    async def is_ready(self) -> bool:
        try:
            async with self._sessions() as session:
                await session.execute(select(1))
            return True
        except (SQLAlchemyError, OSError):
            return False

    async def close(self) -> None:
        await self._engine.dispose()


def create_repository(settings: DatabaseSettings) -> SqlRepository:
    """Tạo engine phù hợp PostgreSQL production."""

    engine = create_async_engine(
        settings.url,
        pool_size=settings.pool_size,
        max_overflow=settings.max_overflow,
        pool_pre_ping=True,
    )
    return SqlRepository(engine)
