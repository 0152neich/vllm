"""Schema request của Management API."""

from __future__ import annotations

from datetime import datetime
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _validate_metadata(value: dict[str, Any] | None) -> dict[str, Any] | None:
    """Metadata là JSON nhỏ, không biến API key thành kho payload/secret."""

    if value is None:
        return None
    try:
        serialized = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ValueError("metadata phải là JSON hợp lệ") from exc
    if len(serialized.encode("utf-8")) > 8_192:
        raise ValueError("metadata không được vượt quá 8 KB")
    return value


def _normalize_tags(value: list[str] | None) -> list[str] | None:
    """Tags là nhãn ngắn, không trùng để lọc/hiển thị nhất quán."""

    if value is None:
        return None
    normalized: list[str] = []
    for tag in value:
        clean = tag.strip()
        if not clean or len(clean) > 64:
            raise ValueError("mỗi tag phải dài từ 1 đến 64 ký tự")
        if clean not in normalized:
            normalized.append(clean)
    return normalized


class ProjectNameConflictError(Exception):
    """Tên project đã tồn tại tại thời điểm transaction được commit."""


class ProjectCreate(BaseModel):
    """Project chỉ là nhóm quản trị của các API key."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=120)


class ProjectUpdate(BaseModel):
    """Optimistic update bắt buộc version hiện tại."""

    model_config = ConfigDict(extra="forbid")

    version: int = Field(gt=0)
    name: str | None = Field(default=None, min_length=2, max_length=120)
    status: Literal["active", "suspended", "archived"] | None = None


class KeyCreate(BaseModel):
    """Yêu cầu phát hành runtime hoặc client management key."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=120)
    kind: Literal["runtime", "management"] = "runtime"
    expires_at: datetime | None = None
    tpm: int | None = Field(default=None, gt=0, le=10_000_000)
    rpm: int | None = Field(default=None, gt=0, le=1_000_000)
    allowed_models: list[str] | None = Field(default=None, min_length=1)
    max_concurrency: int | None = Field(default=None, gt=0, le=10_000)
    max_input_characters: int | None = Field(default=None, gt=0, le=10_000_000)
    max_output_tokens: int | None = Field(default=None, gt=0, le=1_000_000)
    timeout_seconds: float | None = Field(default=None, gt=0, le=3600)
    metadata: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("expires_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        """Không chấp nhận expiry mơ hồ theo timezone của server."""

        if value is not None and value.tzinfo is None:
            raise ValueError("expires_at phải chứa timezone")
        return value

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _validate_metadata(value) or {}

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, value: list[str]) -> list[str]:
        return _normalize_tags(value) or []


class KeyUpdate(BaseModel):
    """Settings sửa được của key, tuyệt đối không đổi credential hay expiry."""

    model_config = ConfigDict(extra="forbid")

    tpm: int | None = Field(default=None, gt=0, le=10_000_000)
    rpm: int | None = Field(default=None, gt=0, le=1_000_000)
    allowed_models: list[str] | None = Field(default=None, min_length=1)
    max_concurrency: int | None = Field(default=None, gt=0, le=10_000)
    max_input_characters: int | None = Field(default=None, gt=0, le=10_000_000)
    max_output_tokens: int | None = Field(default=None, gt=0, le=1_000_000)
    timeout_seconds: float | None = Field(default=None, gt=0, le=3600)
    metadata: dict[str, Any] | None = None
    tags: list[str] | None = Field(default=None, max_length=50)

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        return _validate_metadata(value)

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, value: list[str] | None) -> list[str] | None:
        return _normalize_tags(value)
