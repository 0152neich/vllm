"""Phục vụ Admin UI không cần frontend build toolchain."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, Response

router = APIRouter(tags=["Admin UI"])
WEB_DIR = Path(__file__).resolve().parents[2] / "web"
SCRIPT_ASSETS = {
    "api.js",
    "app.js",
    "components.js",
    "state.js",
    "pages/keys.js",
    "pages/overview.js",
    "pages/playground.js",
    "pages/projects.js",
    "pages/settings.js",
    "pages/usage.js",
}
SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "connect-src 'self'; img-src 'self' data:; object-src 'none'; "
        "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
    ),
    "Referrer-Policy": "no-referrer",
}


@router.get("/admin", include_in_schema=False)
async def admin_ui() -> HTMLResponse:
    return HTMLResponse(
        (WEB_DIR / "index.html").read_text(encoding="utf-8"),
        headers=SECURITY_HEADERS,
    )


@router.get("/admin/app.js", include_in_schema=False)
async def admin_script() -> Response:
    return Response(
        (WEB_DIR / "app.js").read_text(encoding="utf-8"),
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache"},
    )


@router.get("/admin/styles.css", include_in_schema=False)
async def admin_styles() -> Response:
    return Response(
        (WEB_DIR / "styles.css").read_text(encoding="utf-8"),
        media_type="text/css",
        headers={"Cache-Control": "no-cache"},
    )


@router.get("/admin/{asset_path:path}", include_in_schema=False)
async def admin_module(asset_path: str) -> Response:
    """Phục vụ đúng allowlist ES modules, không cho phép đọc path tùy ý."""

    if asset_path not in SCRIPT_ASSETS:
        raise HTTPException(status_code=404)
    return Response(
        (WEB_DIR / asset_path).read_text(encoding="utf-8"),
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache"},
    )
