"""Regression contract cho các chức năng quản trị bắt buộc trên UI."""

from __future__ import annotations

from pathlib import Path

WEB_DIR = Path(__file__).resolve().parents[1] / "app" / "web"


def _assets() -> tuple[str, str]:
    """Đọc static assets trực tiếp để test không phụ thuộc browser."""

    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    script = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    return html, script


def _module(path: str) -> str:
    return (WEB_DIR / path).read_text(encoding="utf-8")


def test_admin_ui_uses_application_shell_with_six_routes() -> None:
    """Admin mới phải là console có sidebar và sáu màn hình độc lập."""

    html, script = _assets()

    assert 'class="sidebar"' in html
    for route in (
        "overview",
        "projects",
        "keys",
        "usage",
        "playground",
        "settings",
    ):
        assert f'data-route="{route}"' in html
        assert f'id="page-{route}"' in html
    assert "hashchange" in script


def test_admin_ui_keeps_management_key_in_tab_session() -> None:
    """Management key phải sống qua reload nhưng mất khi đóng tab."""

    _, script = _assets()

    assert "sessionStorage" in script
    assert "localStorage" in script


def test_playground_models_do_not_depend_on_removed_project_policy() -> None:
    """Đăng nhập phải dùng model catalog hệ thống, không đọc policy project cũ."""

    script = _assets()[1]

    assert "state.models" in script
    assert "project.allowed_models" not in script


def test_admin_ui_has_no_inline_secret_interpolation() -> None:
    """Dữ liệu động phải dùng DOM text thay vì ghép HTML không an toàn."""

    _, script = _assets()

    assert ".innerHTML" not in script


def test_admin_ui_applies_role_aware_controls() -> None:
    """Frontend phải ẩn chức năng platform-only theo principal backend trả về."""

    script = _assets()[1]
    projects = _module("pages/projects.js")
    keys = _module("pages/keys.js")

    assert "principal" in script
    assert "platform_admin" in projects
    assert "platform_admin" in keys


def test_admin_ui_clears_plaintext_credentials_on_logout() -> None:
    """Logout phải xóa runtime key và key plaintext còn trong tab."""

    script = _assets()[1]

    assert 'state.issuedPlaintext = ""' in script
    assert 'elements.runtime_key.value = ""' in script


def test_admin_ui_exposes_project_policy_update_controls() -> None:
    """UI phải cho Platform Admin cập nhật quota bằng optimistic version."""

    html, _ = _assets()
    script = _module("pages/projects.js")

    assert 'id="project-policy-form"' in html
    assert 'method: "PATCH"' in script


def test_project_editor_maps_api_id_to_hidden_project_id() -> None:
    """Project response dùng `id`; UI không được tạo URL chứa undefined."""

    script = _module("pages/projects.js")

    assert "form.elements.project_id.value = project.id" in script
    assert '["project_id", "version"' not in script


def test_project_editor_has_confirmed_delete_for_platform_admin_only() -> None:
    """UI chỉ lộ delete project cho platform và luôn dùng confirm dialog."""

    html, app_script = _assets()
    projects = _module("pages/projects.js")

    assert 'id="delete-project-button"' in html
    assert 'method: "DELETE"' in projects
    assert "confirmAction" in projects
    assert "initProjects(syncProjectSelectors, confirmDialog)" in app_script


def test_management_fetch_accepts_no_content_delete_response() -> None:
    """DELETE 204 thành công không được bị UI hiểu nhầm là JSON lỗi."""

    api = _module("api.js")

    assert "response.status === 204" in api


def test_project_create_keeps_form_reference_across_async_request() -> None:
    """POST thành công không được lỗi reset vì Event.currentTarget đã hết vòng đời."""

    script = _module("pages/projects.js")

    assert "const projectForm = event.currentTarget" in script
    assert "projectForm.reset()" in script
    assert "event.currentTarget.reset()" not in script


def test_admin_ui_exposes_usage_controls() -> None:
    """UI phải đọc và hiển thị usage theo project."""

    html, script = _assets()

    assert 'id="usage-output"' in html
    assert "/usage" in script


def test_admin_ui_exposes_key_revocation_controls() -> None:
    """UI phải có thể thu hồi key bằng ID."""

    html, _ = _assets()
    script = _module("pages/keys.js")

    assert 'id="keys-table"' in html
    assert "/revoke" in script


def test_copy_key_has_fallback_for_internal_http() -> None:
    """Copy phải hoạt động cả khi Clipboard API bị chặn trên HTTP nội bộ."""

    script = _module("pages/keys.js")

    assert "window.isSecureContext" in script
    assert 'document.execCommand("copy")' in script


def test_key_dialog_only_accepts_active_projects() -> None:
    """UI phải loại project suspended/archived khỏi form cấp key."""

    script = _module("pages/keys.js")

    assert 'project.status === "active"' in script


def test_key_console_exposes_optional_settings_and_safe_detail_view() -> None:
    """Key UI phải có quota/metadata/tags và detail, nhưng không có secret lịch sử."""

    html, _ = _assets()
    script = _module("pages/keys.js")

    for field in ('name="tpm"', 'name="rpm"', 'name="metadata"', "key-create-tags"):
        assert field in html
    assert 'id="key-detail"' in html
    assert "GET /management" not in script
    assert "`/keys/${encodeURIComponent(row.id)}`" in script
    assert "key.api_key" not in script
