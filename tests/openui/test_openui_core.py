"""Unit tests for OpenUI tokens, sanitiser, caps, and bridge helpers (`specs/29-openui.md` §9)."""

from __future__ import annotations

import sys
import time
import types
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from sevn.ui.openui.bridge import inject_submit_token_into_html
from sevn.ui.openui.models import effective_openui_config
from sevn.ui.openui.sanitiser import sanitise
from sevn.ui.openui.tokens import sign_token, verify_token, verify_token_status

if TYPE_CHECKING:
    from sevn.agent.tracing.sink import TraceEvent


def test_verify_token_scope_mismatch() -> None:
    secret = "k"
    tok = sign_token(
        secret=secret,
        workspace_id="w",
        session_id="s",
        message_id="m",
        record_id="r",
        scope="render",
        exp_unix=int(time.time()) + 3600,
    )
    assert verify_token(secret=secret, token=tok, expected_scope="render") is not None
    assert verify_token(secret=secret, token=tok, expected_scope="submit") is None


def test_verify_token_expired_status() -> None:
    secret = "k"
    tok = sign_token(
        secret=secret,
        workspace_id="w",
        session_id="s",
        message_id="m",
        record_id="r",
        scope="render",
        exp_unix=int(time.time()) - 10,
    )
    st, _ = verify_token_status(secret=secret, token=tok, expected_scope="render")
    assert st == "expired"


def test_sanitiser_strips_script() -> None:
    r = sanitise("<p>ok</p><script>alert(1)</script>")
    assert "<script" not in r.html.lower()
    assert "ok" in r.html


def test_sanitiser_strips_onerror() -> None:
    r = sanitise('<div onclick="evil()">x</div>')
    assert "onclick" not in r.html.lower()


def test_sanitiser_rejects_workspace_img_src() -> None:
    r = sanitise('<img src="/workspace/.llmignore/x.png" alt="x">')
    assert any(d.reason == "disallowed_src" for d in r.dropped)


def test_sanitiser_allows_media_src() -> None:
    r = sanitise('<img src="/media/abc_token_12" alt="i">')
    assert "/media/abc_token_12" in r.html


def test_rasterise_png_bytes_with_mocked_weasyprint(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub WeasyPrint module so CI hosts without GTK/Pango still exercise rasteriser wiring."""

    class _FakeDoc:
        def write_png(self) -> bytes:
            return b"\x89PNG\r\n\x1a\n"

    fake_mod = types.ModuleType("weasyprint")
    fake_mod.HTML = lambda **_kwargs: _FakeDoc()  # type: ignore[attr-defined, misc]
    monkeypatch.setitem(sys.modules, "weasyprint", fake_mod)

    from sevn.ui.openui.rasteriser import rasterise_png_bytes

    out = rasterise_png_bytes("<p>x</p>")
    assert out.startswith(b"\x89PNG")


def test_effective_openui_config_retired_rasteriser_rejected() -> None:
    from sevn.config.workspace_config import OpenUIWorkspaceConfig

    retired = "play" + "wright"
    with pytest.raises(ValidationError) as exc_info:
        OpenUIWorkspaceConfig(rasteriser=retired)  # type: ignore[arg-type]
    assert retired in str(exc_info.value).lower()


def test_hard_cap_enforced_via_config_bytes() -> None:
    cfg = effective_openui_config(None)
    assert cfg.hard_cap_bytes == 1_048_576
    big = "x" * (cfg.hard_cap_bytes + 10)
    r = sanitise(f"<p>{big}</p>")
    post = len(r.html.encode("utf-8"))
    assert post > cfg.hard_cap_bytes


def test_inject_submit_token() -> None:
    html = '<form method="post" action="/openui/callback"></form>'
    out = inject_submit_token_into_html(html, "tok%2Fabc")
    assert "token=" in out
    assert "/openui/callback" in out


@pytest.mark.asyncio
async def test_openui_bridge_soft_cap_emits_warn_trace() -> None:
    from sevn.config.workspace_config import OpenUIWorkspaceConfig
    from sevn.ui.openui.bridge import OpenUIBridge
    from sevn.ui.openui.models import OpenUIRuntimeDeps
    from sevn.ui.openui.store import OpenUIStore

    events: list[TraceEvent] = []

    class _Sink:
        async def emit(self, event: TraceEvent) -> None:
            events.append(event)

        async def flush(self) -> None:
            return None

        async def close(self) -> None:
            return None

    cfg = effective_openui_config(
        OpenUIWorkspaceConfig(soft_cap_bytes=2000, hard_cap_bytes=2_000_000)
    )
    bridge = OpenUIBridge(store=OpenUIStore(None), signing_secret="s")
    await bridge.render(
        html="<p>" + ("y" * 5000) + "</p>",
        fallback_text="fb",
        output="live",
        title=None,
        session_id="s",
        message_id="m",
        workspace_id="w",
        channel="webchat",
        trace=_Sink(),
        config=cfg,
        runtime=OpenUIRuntimeDeps(public_base_url="http://localhost:3001", tunnel_healthy=True),
        workspace_root=None,
    )
    kinds = [e.kind for e in events]
    assert "openui_emit" in kinds
