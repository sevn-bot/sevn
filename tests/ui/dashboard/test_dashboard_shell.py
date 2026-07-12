"""Mission Control shell parity (`specs/24-dashboard.md` Wave MC-3)."""

from __future__ import annotations

import re
from pathlib import Path

from sevn.gateway.http_server import MISSION_CONTROL_SPA_ROOT

SPA_ROOT = MISSION_CONTROL_SPA_ROOT
STYLE_CSS = SPA_ROOT / "style.css"


def test_shared_modal_css_hides_scrim_when_hidden() -> None:
    modal_css = (
        Path(__file__).resolve().parents[3]
        / "styles"
        / "sevn"
        / "style"
        / "components"
        / "modal.css"
    ).read_text(encoding="utf-8")
    assert ".modal-scrim[hidden]" in modal_css
    assert "display: none" in modal_css


def test_mission_style_css_is_layout_only() -> None:
    text = STYLE_CSS.read_text(encoding="utf-8")
    assert not re.search(r"^\s*--(bg|panel|text|muted|line|accent|fg)\s*:", text, re.MULTILINE)
    assert not re.search(r"#[0-9a-fA-F]{3,8}", text)


def test_mission_index_shell_markup() -> None:
    html = (SPA_ROOT / "index.html").read_text(encoding="utf-8")
    assert "/style/index.css" in html
    assert "/style/logos/logo-primary.svg" in html
    assert "/style/logos/logo-dark-bg.svg" in html
    assert "logo-mark" not in html
    assert "logo-all-white" not in html
    assert "/shared/theme.js" in html
    assert 'id="system-menu-panel"' in html
    assert 'id="command-palette"' in html
    assert 'id="proxy-health-badge"' in html
    assert 'id="provider-health-badge"' in html
    assert 'id="log-retention-modal"' in html


def test_mission_app_js_shell_wiring() -> None:
    js = (SPA_ROOT / "app.js").read_text(encoding="utf-8")
    assert "/api/v1/system/upgrade-restart" in js
    assert "/api/v1/system/logging" in js
    assert "/api/v1/auth/logout" in js
    assert "/api/v1/search" in js
    assert "provider.health" in js
    assert "proxy.health" in js
    assert "initSevnTheme" in js
    assert "connectDashboardHealthWs" in js
    assert 'event.key.toLowerCase() === "k"' in js or "metaKey" in js
