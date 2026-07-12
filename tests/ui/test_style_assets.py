"""Tests for packaged shared UI style assets."""

from __future__ import annotations

from importlib import resources
from typing import TYPE_CHECKING

from fastapi.testclient import TestClient

if TYPE_CHECKING:
    import pytest

from sevn.gateway.http_server import MISSION_CONTROL_SPA_ROOT
from sevn.onboarding.web_app import create_onboarding_app
from sevn.ui.shared import serve_shared_ui_asset


def test_packaged_style_index_css_readable() -> None:
    ref = resources.files("sevn.ui.style") / "index.css"
    assert ref.is_file()
    text = ref.read_text(encoding="utf-8")
    assert "@import './tokens/colors.css'" in text


def test_onboarding_serves_style_index_css() -> None:
    app = create_onboarding_app("tok")
    client = TestClient(app)
    r = client.get("/style/index.css")
    assert r.status_code == 200
    assert "text/css" in r.headers.get("content-type", "")
    assert "@import './tokens/colors.css'" in r.text


def test_serve_style_asset_without_disk_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Package data still serves when ``make styles-build`` copy is absent on disk."""
    import sevn.ui.style as style_mod

    empty = style_mod.STYLE_STATIC_ROOT / "_empty_probe"
    empty.mkdir(exist_ok=True)
    monkeypatch.setattr(style_mod, "STYLE_STATIC_ROOT", empty)
    monkeypatch.setattr(style_mod, "_dev_source_style_root", lambda: None)
    r = style_mod.serve_style_asset("index.css")
    assert r.status_code == 200
    assert b"@import './tokens/colors.css'" in r.body


def test_shared_theme_js_serves() -> None:
    r = serve_shared_ui_asset("theme.js")
    assert r.status_code == 200
    body = r.body if hasattr(r, "body") and r.body is not None else b""
    if not body and hasattr(r, "path"):
        body = r.path.read_bytes()  # type: ignore[union-attr]
    assert b"initSevnTheme" in body


def test_mission_control_html_links_sevn_spa_assets() -> None:
    html = (MISSION_CONTROL_SPA_ROOT / "index.html").read_text(encoding="utf-8")
    assert "sevn.bot Mission Control" in html
    assert "/mission/app.js" in html
    assert "/style/index.css" in html
    assert "/style/logos/logo-primary.svg" in html
    assert "/style/logos/logo-dark-bg.svg" in html
    assert (MISSION_CONTROL_SPA_ROOT / "app.js").is_file()


def test_onboarding_serves_shared_theme_js() -> None:
    app = create_onboarding_app("tok")
    client = TestClient(app)
    r = client.get("/shared/theme.js")
    assert r.status_code == 200
    assert "initSevnTheme" in r.text
