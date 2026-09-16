"""Rate limit và concurrency lease phân tán trên Redis."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from redis.exceptions import RedisError

from app.domain.auth import ProjectPolicy

logger = logging.getLogger(__name__)


RPM_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
local ttl = redis.call('TTL', KEYS[1])
return {current, ttl}
"""

TPM_SCRIPT = """
local current = redis.call('INCRBY', KEYS[1], ARGV[1])
if current == tonumber(ARGV[1]) then redis.call('EXPIRE', KEYS[1], ARGV[2]) end
local ttl = redis.call('TTL', KEYS[1])
return {current, ttl}
"""

CONCURRENCY_SCRIPT = """
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', ARGV[1])
local current = redis.call('ZCARD', KEYS[1])
if current >= tonumber(ARGV[2]) then return 0 end
redis.call('ZADD', KEYS[1], ARGV[3], ARGV[4])
redis.call('EXPIRE', KEYS[1], ARGV[5])
return 1
"""

RELEASE_SCRIPT = """
return redis.call('ZREM', KEYS[1], ARGV[1])
"""


@dataclass
class RedisLease:
    """Lease idempotent, chỉ release member thuộc request hiện tại."""

    client: Any
    key: str
    member: str
    released: bool = False

    async def release(self) -> None:
        if self.released:
            return
        try:
            await self.client.eval(RELEASE_SCRIPT, 1, self.key, self.member)
        except Exception:
            logger.warning(
                "Không release được concurrency lease; TTL sẽ tự thu hồi", exc_info=True
            )
        finally:
            self.released = True


class RedisLimitService:
    """Fixed-window RPM và sorted-set concurrency lease."""

    def __init__(self, client: Any, lease_grace_seconds: int) -> None:
        self._client = client
        self._lease_grace_seconds = lease_grace_seconds

    async def get_cached_key(self, kind: str, prefix: str) -> dict[str, Any] | None:
        """Đọc key policy cache; dữ liệu không chứa plaintext secret."""

        value = await self._client.get(f"llmgw:key:{kind}:{prefix}")
        if value is None:
            return None
        return json.loads(value)

    async def set_cached_key(
        self, kind: str, prefix: str, value: dict[str, Any], ttl_seconds: int
    ) -> None:
        """Cache key digest và policy trong TTL ngắn."""

        await self._client.set(
            f"llmgw:key:{kind}:{prefix}",
            json.dumps(value, separators=(",", ":")),
            ex=ttl_seconds,
        )

    async def invalidate_key(self, prefix: str) -> None:
        """Xóa cả runtime và management cache sau revoke."""

        await self._client.delete(
            f"llmgw:key:runtime:{prefix}", f"llmgw:key:management:{prefix}"
        )

    async def acquire(
        self, policy: ProjectPolicy, request_id: str, estimated_tokens: int = 0
    ) -> RedisLease | None:
        """Chiếm RPM/TPM rồi concurrency; quota key tách bucket với project."""

        import time

        scope = policy.key_id or policy.project_id
        minute = int(time.time() // 60)
        rpm_key = f"llmgw:rate:{scope}:{minute}"
        count, _ = await self._client.eval(RPM_SCRIPT, 1, rpm_key, 60)
        if int(count) > policy.rpm:
            return None

        if policy.tpm is not None and policy.key_id is not None:
            token_key = f"llmgw:tokens:{policy.key_id}:{minute}"
            token_count, _ = await self._client.eval(
                TPM_SCRIPT, 1, token_key, max(1, estimated_tokens), 60
            )
            if int(token_count) > policy.tpm:
                return None

        now_ms = int(time.time() * 1000)
        lease_ms = int((policy.timeout_seconds + self._lease_grace_seconds) * 1000)
        concurrency_key = f"llmgw:concurrency:{scope}"
        acquired = await self._client.eval(
            CONCURRENCY_SCRIPT,
            1,
            concurrency_key,
            now_ms,
            policy.max_concurrency,
            now_ms + lease_ms,
            request_id,
            max(1, lease_ms // 1000),
        )
        if int(acquired) != 1:
            return None
        return RedisLease(self._client, concurrency_key, request_id)

    async def is_ready(self) -> bool:
        try:
            return bool(await self._client.ping())
        except (RedisError, OSError):
            return False

    async def close(self) -> None:
        await self._client.aclose()


def create_redis_limiter(url: str, lease_grace_seconds: int) -> RedisLimitService:
    """Khởi tạo redis client trễ để test không cần Redis package/runtime."""

    from redis.asyncio import Redis

    return RedisLimitService(
        Redis.from_url(url, decode_responses=True), lease_grace_seconds
    )
