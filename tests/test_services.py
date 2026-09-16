"""Unit tests cho auth, limiter và upstream adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
import pytest

from app.core.config import Settings
from app.core.errors import GatewayError
from app.domain.auth import ProjectPolicy
from app.integrations.upstream import OpenAIUpstream
from app.repositories.database import StoredApiKey
from app.services.auth_service import AuthService
from app.services.key_service import ApiKeyService
from app.services.limit_service import RedisLimitService

pytestmark = pytest.mark.anyio


@dataclass
class KeyRepository:
    stored: StoredApiKey | None
    touched: list[str]

    async def find_active_key(self, prefix: str, kind: str) -> StoredApiKey | None:
        del prefix, kind
        return self.stored

    async def touch_key(self, key_id: str) -> None:
        self.touched.append(key_id)


def _policy() -> ProjectPolicy:
    return ProjectPolicy("p1", "VMS", ("qwen3-8b",), 10, 2, 4000, 1024, 10)


async def test_auth_service_accepts_runtime_digest_and_touches_key() -> None:
    """Runtime auth phải verify HMAC trước khi trả project policy."""

    key_service = ApiKeyService("test-pepper-at-least-32-characters")
    issued = key_service.issue()
    repository = KeyRepository(StoredApiKey("k1", issued.digest, _policy()), [])
    service = AuthService(repository, key_service, "platform-admin")

    result = await service.authenticate_runtime(issued.plaintext)

    assert result == _policy()
    assert repository.touched == ["k1"]


async def test_auth_service_rejects_bad_format_and_wrong_digest() -> None:
    """Sai format hoặc digest đều trả None, không làm lộ key tồn tại."""

    key_service = ApiKeyService("test-pepper-at-least-32-characters")
    repository = KeyRepository(StoredApiKey("k1", "0" * 64, _policy()), [])
    service = AuthService(repository, key_service, "platform-admin")

    malformed = await service.authenticate_runtime("bad")
    wrong = await service.authenticate_runtime("lgw_prefix_wrong")

    assert malformed is None and wrong is None


async def test_auth_service_scopes_platform_and_client_management() -> None:
    """Platform key và project management key phải tạo principal khác nhau."""

    key_service = ApiKeyService("test-pepper-at-least-32-characters")
    issued = key_service.issue()
    repository = KeyRepository(StoredApiKey("k1", issued.digest, _policy()), [])
    service = AuthService(repository, key_service, "platform-admin")

    platform = await service.authenticate_management("platform-admin")
    client = await service.authenticate_management(issued.plaintext)

    assert platform is not None and platform.role == "platform_admin"
    assert client is not None and client.project_id == "p1"


class FakeRedis:
    def __init__(self, results: list[Any]) -> None:
        self.results = results
        self.calls: list[tuple[Any, ...]] = []
        self.closed = False
        self.values: dict[str, str] = {}

    async def eval(self, *args: Any) -> Any:
        self.calls.append(args)
        return self.results.pop(0)

    async def ping(self) -> bool:
        return True

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: str, ex: int) -> None:
        del ex
        self.values[key] = value

    async def delete(self, *keys: str) -> None:
        for key in keys:
            self.values.pop(key, None)

    async def aclose(self) -> None:
        self.closed = True


async def test_redis_limiter_acquires_and_releases_idempotently() -> None:
    """Lease release hai lần chỉ thực hiện một ZREM."""

    redis = FakeRedis([[1, 59], 1, 1])
    limiter = RedisLimitService(redis, 5)

    lease = await limiter.acquire(_policy(), "request-1")
    assert lease is not None
    await lease.release()
    await lease.release()

    assert len(redis.calls) == 3


async def test_redis_limiter_rejects_when_rpm_or_concurrency_full() -> None:
    """Hai loại hard limit đều fail-fast."""

    rpm_limiter = RedisLimitService(FakeRedis([[11, 30]]), 5)
    concurrency_limiter = RedisLimitService(FakeRedis([[1, 30], 0]), 5)

    assert await rpm_limiter.acquire(_policy(), "r1") is None
    assert await concurrency_limiter.acquire(_policy(), "r2") is None


async def test_redis_limiter_uses_independent_key_rpm_and_tpm_buckets() -> None:
    """Key override phải không chia RPM/TPM với quota mặc định của project."""

    policy = ProjectPolicy(
        "p1", "VMS", ("qwen3-8b",), 600, 2, 4000, 1024, 10,
        key_id="key-burst", tpm=120_000, rpm_overridden=True,
    )
    redis = FakeRedis([[1, 59], [1_000, 59], 1])
    limiter = RedisLimitService(redis, 5)

    lease = await limiter.acquire(policy, "request-1", estimated_tokens=1_000)

    assert lease is not None
    assert "key-burst" in str(redis.calls[0])
    assert "tokens:key-burst" in str(redis.calls[1])


async def test_redis_key_cache_round_trip_and_invalidation() -> None:
    """Policy cache phải serialize ổn định và xóa được sau revoke."""

    redis = FakeRedis([])
    limiter = RedisLimitService(redis, 5)
    value = {"key_id": "k1", "digest": "abc", "policy": {"rpm": 10}}

    assert await limiter.get_cached_key("runtime", "pfx") is None
    await limiter.set_cached_key("runtime", "pfx", value, 30)
    cached = await limiter.get_cached_key("runtime", "pfx")
    await limiter.invalidate_key("pfx")

    assert cached == value
    assert await limiter.get_cached_key("runtime", "pfx") is None


class PolicyCache:
    def __init__(self, value: dict[str, Any] | None = None) -> None:
        self.value = value
        self.written: dict[str, Any] | None = None

    async def get_cached_key(self, kind: str, prefix: str) -> dict[str, Any] | None:
        del kind, prefix
        return self.value

    async def set_cached_key(
        self, kind: str, prefix: str, value: dict[str, Any], ttl_seconds: int
    ) -> None:
        del kind, prefix, ttl_seconds
        self.written = value


async def test_auth_service_reads_and_populates_policy_cache() -> None:
    """Cache hit bỏ qua DB; cache miss ghi digest/policy không có plaintext."""

    key_service = ApiKeyService("test-pepper-at-least-32-characters")
    issued = key_service.issue()
    cached_value = {
        "key_id": "cached-key",
        "digest": issued.digest,
        "policy": {
            "project_id": "p1",
            "project_name": "VMS",
            "allowed_models": ["qwen3-8b"],
            "rpm": 10,
            "max_concurrency": 2,
            "max_input_characters": 4000,
            "max_output_tokens": 1024,
            "timeout_seconds": 10,
        },
    }
    hit_repository = KeyRepository(None, [])
    hit_service = AuthService(
        hit_repository, key_service, "admin", PolicyCache(cached_value), 30
    )

    hit = await hit_service.authenticate_runtime(issued.plaintext)

    miss_cache = PolicyCache()
    stored = StoredApiKey("db-key", issued.digest, _policy())
    miss_service = AuthService(
        KeyRepository(stored, []), key_service, "admin", miss_cache, 30
    )
    miss = await miss_service.authenticate_runtime(issued.plaintext)

    assert hit is not None and hit.project_id == "p1"
    assert miss is not None and miss_cache.written is not None
    assert issued.plaintext not in str(miss_cache.written)


async def test_upstream_complete_forwards_key_and_maps_timeout() -> None:
    """Adapter chuyển Authorization nhưng trả lỗi an toàn khi timeout."""

    settings = Settings.for_test().upstream
    upstream = OpenAIUpstream(settings)

    def success(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer upstream-test"
        return httpx.Response(200, json={"choices": []})

    await upstream._client.aclose()
    upstream._client = httpx.AsyncClient(transport=httpx.MockTransport(success))
    result = await upstream.complete({"model": "test"}, 2)
    assert result == {"choices": []}

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    await upstream._client.aclose()
    upstream._client = httpx.AsyncClient(transport=httpx.MockTransport(timeout))
    with pytest.raises(GatewayError) as raised:
        await upstream.complete({"model": "test"}, 2)
    await upstream.close()

    assert raised.value.code == "upstream_timeout"


async def test_upstream_stream_proxies_chunks_and_readiness() -> None:
    """Adapter giữ nguyên SSE raw chunks và kiểm tra models endpoint."""

    upstream = OpenAIUpstream(Settings.for_test().upstream)

    class TestStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"data: one\n\n"
            yield b"data: [DONE]\n\n"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": []})
        return httpx.Response(200, stream=TestStream())

    await upstream._client.aclose()
    upstream._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    chunks = [chunk async for chunk in upstream.stream({"stream": True}, 2)]
    ready = await upstream.is_ready()
    await upstream.close()

    assert b"".join(chunks).endswith(b"data: [DONE]\n\n")
    assert ready is True


async def test_upstream_rejects_server_error_invalid_json_and_failed_readiness() -> (
    None
):
    """Các failure mode upstream phải được che bằng error code ổn định."""

    upstream = OpenAIUpstream(Settings.for_test().upstream)

    await upstream._client.aclose()
    upstream._client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(500))
    )
    with pytest.raises(GatewayError) as server_error:
        await upstream.complete({"model": "test"}, 2)

    await upstream._client.aclose()
    upstream._client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text="not-json"))
    )
    with pytest.raises(GatewayError) as invalid_json:
        await upstream.complete({"model": "test"}, 2)

    def offline(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    await upstream._client.aclose()
    upstream._client = httpx.AsyncClient(transport=httpx.MockTransport(offline))
    ready = await upstream.is_ready()
    await upstream.close()

    assert server_error.value.code == "upstream_error"
    assert invalid_json.value.code == "invalid_upstream_response"
    assert ready is False


async def test_upstream_stream_rejected_status_raises_safe_error() -> None:
    """Streaming upstream 5xx phải thất bại trước khi trả chunk."""

    upstream = OpenAIUpstream(Settings.for_test().upstream)
    await upstream._client.aclose()
    upstream._client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(503))
    )

    with pytest.raises(GatewayError) as raised:
        _ = [chunk async for chunk in upstream.stream({"stream": True}, 2)]
    await upstream.close()

    assert raised.value.code == "upstream_error"
