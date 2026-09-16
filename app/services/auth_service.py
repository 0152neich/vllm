"""Xác thực runtime và management key theo project."""

from __future__ import annotations

import hmac
import logging
from datetime import datetime, timezone
from typing import Any

from app.domain.auth import ManagementPrincipal, ProjectPolicy
from app.services.key_service import ApiKeyService

logger = logging.getLogger(__name__)


class AuthService:
    """Resolve API key qua prefix và verify digest constant-time."""

    def __init__(
        self,
        repository: Any,
        key_service: ApiKeyService,
        admin_key: str,
        cache: Any | None = None,
        cache_ttl_seconds: int = 30,
    ) -> None:
        self._repository = repository
        self._key_service = key_service
        self._admin_key = admin_key
        self._cache = cache
        self._cache_ttl_seconds = cache_ttl_seconds

    async def _find_key(self, prefix: str, kind: str) -> tuple[Any | None, bool]:
        """Ưu tiên Redis cache, fallback PostgreSQL khi cache miss/lỗi."""

        from app.repositories.database import StoredApiKey

        if self._cache is not None:
            try:
                cached = await self._cache.get_cached_key(kind, prefix)
                if cached is not None:
                    expires_at = (
                        datetime.fromisoformat(cached["expires_at"])
                        if cached.get("expires_at")
                        else None
                    )
                    return StoredApiKey(
                        cached["key_id"],
                        cached["digest"],
                        ProjectPolicy(
                            project_id=cached["policy"]["project_id"],
                            project_name=cached["policy"]["project_name"],
                            allowed_models=tuple(cached["policy"]["allowed_models"]),
                            rpm=cached["policy"]["rpm"],
                            max_concurrency=cached["policy"]["max_concurrency"],
                            max_input_characters=cached["policy"][
                                "max_input_characters"
                            ],
                            max_output_tokens=cached["policy"]["max_output_tokens"],
                            timeout_seconds=cached["policy"]["timeout_seconds"],
                            key_id=cached["policy"].get("key_id"),
                            key_prefix=cached["policy"].get("key_prefix"),
                            tpm=cached["policy"].get("tpm"),
                            rpm_overridden=True,
                        ),
                        expires_at,
                    ), True
            except Exception:
                logger.warning("Không đọc được API key cache", exc_info=True)
        stored = await self._repository.find_active_key(prefix, kind)
        if stored is not None and self._cache is not None:
            try:
                await self._cache.set_cached_key(
                    kind,
                    prefix,
                    {
                        "key_id": stored.key_id,
                        "digest": stored.digest,
                        "expires_at": (
                            stored.expires_at.isoformat() if stored.expires_at else None
                        ),
                        "policy": {
                            "project_id": stored.policy.project_id,
                            "project_name": stored.policy.project_name,
                            "allowed_models": list(stored.policy.allowed_models),
                            "rpm": stored.policy.rpm,
                            "max_concurrency": stored.policy.max_concurrency,
                            "max_input_characters": stored.policy.max_input_characters,
                            "max_output_tokens": stored.policy.max_output_tokens,
                            "timeout_seconds": stored.policy.timeout_seconds,
                            "key_id": stored.policy.key_id,
                            "key_prefix": stored.policy.key_prefix,
                            "tpm": stored.policy.tpm,
                            "rpm_overridden": True,
                        },
                    },
                    self._cache_ttl_seconds,
                )
            except Exception:
                logger.warning("Không ghi được API key cache", exc_info=True)
        return stored, False

    async def authenticate_runtime(self, token: str) -> ProjectPolicy | None:
        """Trả policy khi runtime key hợp lệ và project đang active."""

        prefix = self._key_service.parse_prefix(token)
        if prefix is None:
            return None
        stored, from_cache = await self._find_key(prefix, "runtime")
        if (
            stored is None
            or (
                stored.expires_at is not None
                and stored.expires_at <= datetime.now(timezone.utc)
            )
            or not self._key_service.verify(token, stored.digest)
        ):
            return None
        if not from_cache:
            await self._repository.touch_key(stored.key_id)
        return stored.policy

    async def authenticate_management(self, token: str) -> ManagementPrincipal | None:
        """Ưu tiên platform bootstrap key, sau đó kiểm tra client management key."""

        if hmac.compare_digest(token, self._admin_key):
            return ManagementPrincipal(role="platform_admin", project_id=None)
        prefix = self._key_service.parse_prefix(token)
        if prefix is None:
            return None
        stored, from_cache = await self._find_key(prefix, "management")
        if (
            stored is None
            or (
                stored.expires_at is not None
                and stored.expires_at <= datetime.now(timezone.utc)
            )
            or not self._key_service.verify(token, stored.digest)
        ):
            return None
        if not from_cache:
            await self._repository.touch_key(stored.key_id)
        return ManagementPrincipal(
            role="client_admin", project_id=stored.policy.project_id
        )
