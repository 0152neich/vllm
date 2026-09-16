"""Unit tests cho API key không lưu plaintext."""

from __future__ import annotations

from app.services.key_service import ApiKeyService


def test_generated_key_can_be_verified_without_storing_plaintext() -> None:
    """Digest phải xác thực được key vừa tạo và không chứa plaintext."""

    service = ApiKeyService("test-pepper-at-least-32-characters")
    issued = service.issue()

    assert issued.plaintext.startswith("lgw_")
    assert issued.plaintext not in issued.digest
    assert service.verify(issued.plaintext, issued.digest) is True


def test_modified_key_fails_constant_time_digest_verification() -> None:
    """Thay đổi một ký tự phải làm key không hợp lệ."""

    service = ApiKeyService("test-pepper-at-least-32-characters")
    issued = service.issue()

    assert service.verify(f"{issued.plaintext}x", issued.digest) is False
