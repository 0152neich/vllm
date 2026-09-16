"""Context xác thực không chứa plaintext API key."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ProjectPolicy:
    """Policy runtime đã resolve theo API key."""

    project_id: str
    project_name: str
    allowed_models: tuple[str, ...]
    rpm: int
    max_concurrency: int
    max_input_characters: int
    max_output_tokens: int
    timeout_seconds: float
    key_id: str | None = None
    key_prefix: str | None = None
    tpm: int | None = None
    rpm_overridden: bool = False


@dataclass(frozen=True)
class ManagementPrincipal:
    """Danh tính gọi Management API."""

    role: Literal["platform_admin", "client_admin"]
    project_id: str | None
