"""v1 OpenUI delivery gate (`specs/29-openui.md` Wave 11, `plan/v1-tasks-ordered.md` Wave 11)."""

from __future__ import annotations

import json
import sys
import time
import types
from typing import TYPE_CHECKING

import pytest
from starlette.testclient import TestClient

from sevn.gateway.channel_router import OutgoingMessage
from sevn.tools.base import ToolExecutor
from sevn.tools.context import ToolContext
from sevn.ui.openui.bridge import OpenUIBridge, build_content_security_policy
from sevn.ui.openui.delivery import build_openui_delivery_metadata
from sevn.ui.openui.models import OpenUIRuntimeDeps, effective_openui_config
from sevn.ui.openui.sanitiser import sanitise
from sevn.ui.openui.store import OpenUIStore
from sevn.ui.openui.tools_register import openui_render, register_openui_tools

if TYPE_CHECKING:
    from pathlib import Path


def _mock_weasyprint(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeDoc:
        def write_png(self) -> bytes:
            return b"\x89PNG\r\n\x1a\n"

        def write_pdf(self) -> bytes:
            return b"%PDF-1.4\n"

    fake_mod = types.ModuleType("weasyprint")
    fake_mod.HTML = lambda **_kwargs: _FakeDoc()  # type: ignore[attr-defined, misc]
    monkeypatch.setitem(sys.modules, "weasyprint", fake_mod)


@pytest.mark.asyncio
async def test_openui_render_webchat_live_iframe_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tool → bridge → webchat ``openui_iframe_src`` for live HTML."""

    sevn = tmp_path / "sevn.json"
    sevn.write_text(
        '{"schema_version": 1, "workspace_root": ".", "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    store = OpenUIStore(None)
    bridge = OpenUIBridge(store=store, signing_secret="gate-secret")
    ctx = ToolContext(
        workspace_path=tmp_path,
        workspace_id="ws",
        registry_version=1,
        session_id="sess-1",
        turn_id="turn-1",
        openui_bridge=bridge,
        gateway_public_base_url="https://gw.example",
        tunnel_healthy=True,
        delivery_channel="webchat",
    )
    raw = await openui_render(
        ctx,
        html="<p>panel</p><script>alert(1)</script>",
        fallback_text="plain panel",
        output="live",
        title="Report",
    )
    blob = json.loads(raw)
    assert blob["ok"] is True
    assert blob["data"]["live_url"] == blob["data"]["delivery_metadata"]["openui_iframe_src"]
    assert blob["data"]["delivery_metadata"]["openui_iframe_src"].startswith(
        "https://gw.example/openui/"
    )
    assert blob["data"]["cap_status"] == "ok"
    assert "<script" not in sanitise("<p>panel</p><script>alert(1)</script>").html.lower()


@pytest.mark.asyncio
async def test_openui_render_telegram_tunnel_down_raster_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Telegram without tunnel forces WeasyPrint PNG fallback metadata."""

    _mock_weasyprint(monkeypatch)
    sevn = tmp_path / "sevn.json"
    sevn.write_text(
        '{"schema_version": 1, "workspace_root": ".", "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    store = OpenUIStore(None)
    bridge = OpenUIBridge(store=store, signing_secret="gate-secret")
    ctx = ToolContext(
        workspace_path=tmp_path,
        workspace_id="ws",
        registry_version=1,
        session_id="sess-tg",
        turn_id="turn-tg",
        openui_bridge=bridge,
        gateway_public_base_url="https://gw.example",
        tunnel_healthy=False,
        delivery_channel="telegram",
    )
    raw = await openui_render(
        ctx,
        html="<p>budget</p>",
        fallback_text="Budget summary",
        output="live",
        title="Budget",
    )
    blob = json.loads(raw)
    assert blob["ok"] is True
    assert blob["data"]["live_url"] is None
    assert blob["data"]["image_path"]
    md = blob["data"]["delivery_metadata"]
    assert md["openui_image_path"] == blob["data"]["image_path"]
    assert "inline_keyboard" not in md


@pytest.mark.asyncio
async def test_webchat_adapter_emits_openui_frame_from_delivery_metadata() -> None:
    from sevn.channels.webchat import WebChatAdapter
    from sevn.gateway.api.web_transport import WebChannelTransport

    class _WS:
        def __init__(self) -> None:
            self.sent: list[str] = []

        async def send_text(self, data: str) -> None:
            self.sent.append(data)

    ws = _WS()
    transport = WebChannelTransport()
    await transport.register(session_id="sess-w", client_id="c-w", ws=ws)  # type: ignore[arg-type]
    adapter = WebChatAdapter(transport=transport)
    from sevn.ui.openui.models import OpenUIRenderResult

    md = build_openui_delivery_metadata(
        OpenUIRenderResult(live_url="/openui/tok", fallback_text="fb"),
        channel="webchat",
        title="T",
    )
    await adapter.send(
        OutgoingMessage(
            channel="webchat",
            user_id="u",
            text="see panel",
            session_id="sess-w",
            metadata=md,
        )
    )
    assert ws.sent
    frame = json.loads(ws.sent[-1])
    assert frame["type"] == "openui"
    assert frame["iframe_src"] == "/openui/tok"


def test_sanitiser_allowlist_strips_script_and_onerror() -> None:
    r = sanitise('<div onclick="x()">a</div><script>b</script>')
    assert "script" not in r.html.lower()
    assert "onclick" not in r.html.lower()
    assert any(d.tag == "script" for d in r.dropped)


def test_csp_script_src_none_enforced() -> None:
    csp = build_content_security_policy(
        allowed_asset_origins=("https://cdn.example",),
        gateway_origin="https://gw.example",
    )
    assert "script-src 'none'" in csp
    assert "https://cdn.example" in csp


def test_gateway_openui_get_csp_header(tmp_path: Path) -> None:
    from sevn.config.workspace_config import (
        SecurityScannerSubConfig,
        SecurityWorkspaceConfig,
        WorkspaceConfig,
    )
    from sevn.gateway.http_server import create_app
    from sevn.storage.migrate import apply_migrations
    from sevn.ui.openui.store import OpenUIRecord
    from sevn.ui.openui.tokens import sign_token
    from sevn.workspace.layout import WorkspaceLayout

    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "workspace_root": ".", "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    workspace_cfg = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        security=SecurityWorkspaceConfig(
            scanner=SecurityScannerSubConfig(heuristic_only=True),
        ),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    layout = WorkspaceLayout.from_config(sevn_json, workspace_cfg)

    def factory() -> object:
        import sqlite3

        conn = sqlite3.connect(":memory:", check_same_thread=False)
        conn.execute("PRAGMA foreign_keys=ON")
        apply_migrations(conn)
        return conn

    app = create_app(
        workspace=workspace_cfg,
        layout=layout,
        sqlite_connection_factory=factory,
    )
    with TestClient(app, raise_server_exceptions=True) as client:
        client.get("/health")
        secret = str(client.app.state.openui_secret)
        store = client.app.state.openui_store
        record_id = "rec-v1"
        exp_ns = time.time_ns() + 3600 * 10**9
        store.put(
            OpenUIRecord(
                record_id=record_id,
                workspace_id=".",
                session_id="s",
                message_id="m",
                channel="webchat",
                sanitised_html="<p>safe</p>",
                expires_at_ns=exp_ns,
                submit_consumed=False,
                fallback_text="fb",
            )
        )
        tok = sign_token(
            secret=secret,
            workspace_id=".",
            session_id="s",
            message_id="m",
            record_id=record_id,
            scope="render",
            exp_unix=int(time.time()) + 3600,
        )
        resp = client.get(f"/openui/{tok}")
        assert resp.status_code == 200
        csp = resp.headers.get("content-security-policy", "")
        assert "script-src 'none'" in csp


def test_openui_render_registered_on_tier_b_executor() -> None:
    exe = ToolExecutor(default_timeout_seconds=None)
    register_openui_tools(exe)
    assert "openui_render" in exe._tools


@pytest.mark.asyncio
async def test_bridge_webchat_never_rasterises_on_healthy_tunnel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Webchat live path keeps ``live_url`` even when rasteriser is available."""

    _mock_weasyprint(monkeypatch)
    bridge = OpenUIBridge(store=OpenUIStore(None), signing_secret="s")
    out = await bridge.render(
        html="<p>live</p>",
        fallback_text="fb",
        output="live",
        title=None,
        session_id="s",
        message_id="m",
        workspace_id="w",
        channel="webchat",
        trace=__import__("sevn.agent.tracing.sink", fromlist=["NullTraceSink"]).NullTraceSink(),
        config=effective_openui_config(None),
        runtime=OpenUIRuntimeDeps(public_base_url="http://localhost:3001", tunnel_healthy=True),
    )
    assert out.live_url
    assert out.image_path is None
