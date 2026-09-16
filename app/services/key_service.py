"""Sinh và xác thực API key bằng HMAC digest."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass


@dataclass(frozen=True)
class IssuedApiKey:
    """Plaintext chỉ tồn tại trong kết quả phát hành một lần."""

    plaintext: str
    prefix: str
    digest: str


class ApiKeyService:
    """API key ngẫu nhiên có prefix tra cứu và digest không đảo ngược."""

    def __init__(self, pepper: str) -> None:
        self._pepper = pepper.encode("utf-8")

    def issue(self) -> IssuedApiKey:
        """Phát hành key entropy cao."""

        prefix = secrets.token_hex(6)
        secret = secrets.token_urlsafe(32)
        plaintext = f"lgw_{prefix}_{secret}"
        return IssuedApiKey(plaintext, prefix, self.digest(plaintext))

    def digest(self, plaintext: str) -> str:
        """Tính HMAC-SHA256 với pepper chỉ có tại Gateway."""

        return hmac.new(
            self._pepper, plaintext.encode("utf-8"), hashlib.sha256
        ).hexdigest()

    def verify(self, plaintext: str, expected_digest: str) -> bool:
        """So sánh constant-time để giảm timing side-channel."""

        return hmac.compare_digest(self.digest(plaintext), expected_digest)

    @staticmethod
    def parse_prefix(plaintext: str) -> str | None:
        """Tách prefix mà không chấp nhận key sai format."""

        parts = plaintext.split("_", 2)
        if len(parts) != 3 or parts[0] != "lgw" or not parts[1] or not parts[2]:
            return None
        return parts[1]
