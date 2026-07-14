"""Wave TE-4 — `/config` Logs section (`specs/18-channel-telegram.md` §4.7 / §10.14 TE-4).

The 19th root tile (📜 Logs) renders inside `/config`; the Logs section
keyboard exposes tail / grep / traces / toggle-redaction / deployment-id
buttons. Wave TE-9 flips ``C0.19`` and ``C20.*`` in ``_READY_SPEC_IDS``.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from sevn.agent.tracing.sink import NullTraceSink
from sevn.gateway.agent_turn import build_agent_run_turn
from sevn.gateway.channel_router import ChannelRouter, IncomingMessage
from sevn.gateway.commands.dispatcher import CommandDispatcher
from sevn.gateway.commands.menu_action_router import (
    infer_config_section_from_callback,
    parse_action_callback,
)
from sevn.gateway.commands.menu_form_handler import parse_form_callback
from sevn.gateway.media.media_store import MediaStore
from sevn.gateway.menu.menu import (
    _CONFIG_ROOT_TILES,
    _build_logs_keyboard_rows,
    build_config_menu_keyboard,
    config_menu_message_text,
)
from sevn.gateway.menu.menu_readiness import (
    _READY_SPEC_IDS,
    readiness_for_callback,
)
from sevn.gateway.menu.menu_registry import match_menu_button_spec
from sevn.gateway.runtime.rate_limit import TokenBucketLimiter
from sevn.gateway.session_manager import SessionManager
from sevn.security.llm_guard_scanner import LLMGuardScanner
from sevn.workspace.layout import WorkspaceLayout
from tests.gateway.test_menu import _conn, _MenuCaptureTelegram, _workspace

# --- Static structure ---------------------------------------------------------


def test_logs_tile_appended_to_config_root_tiles() -> None:
    """Logs is followed by sevn.bot and My sevn bot root tiles."""
    sids = [sid for _label, sid, _cb in _CONFIG_ROOT_TILES]
    assert "logs" in sids
    assert sids[-2:] == ["sevn_bot", "my_sevn_bot"]
    assert len(_CONFIG_ROOT_TILES) == 19
    logs_idx = sids.index("logs")
    _label, _, last_cb = _CONFIG_ROOT_TILES[logs_idx]
    assert last_cb == "cfg:section:logs"


def test_config_logs_tile_renders_in_root() -> None:
    """`/config` keyboard exposes 19 root tiles and nav chrome (Help/Home/Close)."""
    ws = _workspace()
    kb = build_config_menu_keyboard(ws, section="root")
    rows = kb["inline_keyboard"]
    body_rows = rows[:-1]
    body_section_callbacks = [
        btn["callback_data"]
        for row in body_rows
        for btn in row
        if btn.get("callback_data", "").startswith("cfg:section:")
    ]
    assert len(body_section_callbacks) == 19
    assert "cfg:section:rlm" not in body_section_callbacks
    assert "cfg:section:advanced" in body_section_callbacks
    assert "cfg:section:logs" in body_section_callbacks
    assert "cfg:section:sevn_bot" in body_section_callbacks
    assert "cfg:section:my_sevn_bot" in body_section_callbacks
    chrome = rows[-1]
    chrome_callbacks = [btn["callback_data"] for btn in chrome]
    assert "cfg:nav:help" in chrome_callbacks
    assert "cfg:nav:home" in chrome_callbacks
    assert "cfg:nav:close" in chrome_callbacks


def test_build_logs_keyboard_rows_includes_all_actions() -> None:
    """All Logs actions appear with the `cfg:logs:*` / `form:logs:*` namespaces."""
    rows = _build_logs_keyboard_rows(_workspace())
    callbacks = [btn["callback_data"] for row in rows for btn in row]
    assert "cfg:logs:tail:gateway:0" in callbacks
    assert "cfg:logs:tail:proxy:0" in callbacks
    assert "form:logs:grep" in callbacks
    assert "cfg:logs:traces:0" in callbacks
    assert "form:logs:span_id" in callbacks
    assert "cfg:logs:toggle_logfire" in callbacks
    assert "form:logs:logfire_token" in callbacks
    assert "cfg:logs:toggle_redaction" in callbacks
    assert "cfg:logs:deployment_id" not in callbacks


def test_logs_section_caption_text() -> None:
    """`section == "logs"` produces a Logs caption with redaction state."""
    text = config_menu_message_text(_workspace(), section="logs")
    assert text.startswith("Logs")
    assert "Logfire export:" in text
    assert "Trace redaction:" in text


# --- Readiness gating ---------------------------------------------------------


def test_logs_tile_and_actions_in_ready_set() -> None:
    """Wave TE-9 flips ``C0.19`` and ``C20.*`` into the pressable set."""
    assert "C0.19" in _READY_SPEC_IDS
    for c20 in ("C20.1", "C20.2", "C20.3", "C20.4", "C20.5", "C20.6", "C20.7"):
        assert c20 in _READY_SPEC_IDS


def test_logs_action_callbacks_report_ready_readiness() -> None:
    """Concrete Logs action callbacks resolve to Ready after TE-9."""
    assert readiness_for_callback("cfg:logs:tail:gateway:0") == "Ready"
    assert readiness_for_callback("cfg:logs:tail:proxy:0") == "Ready"
    assert readiness_for_callback("cfg:logs:traces:0") == "Ready"
    assert readiness_for_callback("cfg:logs:toggle_redaction") == "Ready"
    assert readiness_for_callback("cfg:logs:toggle_logfire") == "Ready"
    assert readiness_for_callback("form:logs:logfire_token") == "Ready"
    assert readiness_for_callback("cfg:logs:deployment_id") == "Ready"
    assert readiness_for_callback("form:logs:grep") == "Ready"
    assert readiness_for_callback("form:logs:span_id") == "Ready"


def test_logs_section_keyboard_exposes_action_callbacks() -> None:
    """The gated section keyboard keeps concrete ``cfg:logs:*`` callbacks pressable."""
    ws = _workspace()
    kb = build_config_menu_keyboard(ws, section="logs")
    from sevn.gateway.menu.menu_readiness import gate_config_keyboard_rows

    rows = kb["inline_keyboard"]
    chrome = rows[-1:]
    body = rows[:-1]
    gated = gate_config_keyboard_rows(body) + chrome
    body_callbacks = [btn.get("callback_data", "") for row in gated[:-1] for btn in row]
    assert "cfg:logs:tail:gateway:0" in body_callbacks
    assert not any(cb.startswith("cfg:disabled:") for cb in body_callbacks if cb)


# --- Registry rows ------------------------------------------------------------


def test_logs_registry_rows_present_with_owner_only_flags() -> None:
    """C20.1-C20.6 are owner-only Logs actions."""
    expected = {
        "cfg:logs:tail:gateway:0": ("C20.1", True),
        "cfg:logs:tail:proxy:0": ("C20.2", True),
        "form:logs:grep": ("C20.3", True),
        "cfg:logs:traces:0": ("C20.4", True),
        "form:logs:span_id": ("C20.5", True),
        "cfg:logs:toggle_redaction": ("C20.6", True),
    }
    for cb, (spec_id, owner_only) in expected.items():
        spec = match_menu_button_spec(cb)
        assert spec is not None, f"missing registry row for {cb}"
        assert spec.spec_id == spec_id
        assert spec.implemented is True
        assert spec.owner_only is owner_only


def test_parse_action_callback_logs_namespace() -> None:
    """`cfg:logs:*` callbacks parse to action rows under the ``logs:`` target."""
    assert parse_action_callback("cfg:logs:tail:gateway:0") == (
        "action",
        "logs:tail:gateway:0",
        None,
    )
    assert parse_action_callback("cfg:logs:traces:1") == ("action", "logs:traces:1", None)
    assert parse_action_callback("cfg:logs:toggle_redaction") == (
        "action",
        "logs:toggle_redaction",
        None,
    )
    assert parse_action_callback("cfg:logs:deployment_id") == (
        "action",
        "logs:deployment_id",
        None,
    )


def test_parse_form_callback_logs_targets() -> None:
    """`form:logs:grep` / `form:logs:span_id` resolve to the new form targets."""
    assert parse_form_callback("form:logs:grep") == "logs_grep"
    assert parse_form_callback("form:logs:span_id") == "logs_span_id"


def test_infer_config_section_from_callback_logs() -> None:
    """`cfg:logs:*` infers the `logs` config section for menu refresh."""
    assert infer_config_section_from_callback("cfg:logs:toggle_redaction") == "logs"


# --- Owner / non-owner runtime ------------------------------------------------


def _build_owner_router(tmp_path: Path) -> tuple[ChannelRouter, _MenuCaptureTelegram, Path]:
    """Mirror tests.gateway.test_config_menu_actions._build_router with owner ids."""
    root = tmp_path / "w"
    root.mkdir()
    sevn_json = root / "sevn.json"
    sevn_json.write_text(
        (
            '{"schema_version":1,"workspace_root":".",'
            '"gateway":{"host":"127.0.0.1","port":3001,"queue_mode":"cancel",'
            '"token":"${SECRET:keychain:sevn.gateway.token}"},'
            '"channels":{"telegram":{"quick_actions":{"show_regen":true}}},'
            '"security":{"scanner":{"heuristic_only":true}},'
            '"providers":{"use_main_model_for_all":false,'
            '"tier_default":{"triager":"test/triager","B":"test/tier-b"}}}'
        ),
        encoding="utf-8",
    )
    ws = _workspace()
    conn = _conn()
    cap = _MenuCaptureTelegram()
    router = ChannelRouter(
        workspace=ws,
        content_root=root,
        sessions=SessionManager(conn),
        dispatcher=CommandDispatcher(),
        scanner=LLMGuardScanner(root, ws),
        trace=NullTraceSink(),
        rate=TokenBucketLimiter(capacity=50.0, refill_per_second=25.0),
        media=MediaStore(conn, root),
        run_turn=AsyncMock(),
        owner_user_ids=frozenset({"owner1"}),
    )
    router.register_adapter(cap)
    build_agent_run_turn(
        router,
        conn,
        ws,
        WorkspaceLayout(sevn_json, root),
        NullTraceSink(),
    )
    return router, cap, root


def _logs_callback(
    data: str,
    *,
    user_id: str = "owner1",
    chat_id: int = 42,
    message_id: int = 99,
    callback_query_id: str = "cq-logs-1",
) -> IncomingMessage:
    return IncomingMessage(
        channel="telegram",
        user_id=user_id,
        text=data,
        metadata={
            "callback_data": data,
            "callback_query_id": callback_query_id,
            "chat_id": chat_id,
            "message_id": message_id,
        },
    )


@pytest.mark.asyncio
async def test_logs_section_navigation_owner(tmp_path: Path) -> None:
    """Opening the Logs section edits the host message with pressable action rows."""
    router, cap, _root = _build_owner_router(tmp_path)
    await router.route_incoming(_logs_callback("cfg:section:logs"))
    assert len(cap.edited) == 1
    edit = cap.edited[0]
    assert edit["message_id"] == 99
    assert "Logs" in edit["text"]
    body_callbacks = [
        btn.get("callback_data", "")
        for row in edit["reply_markup"]["inline_keyboard"]
        for btn in row
    ]
    assert "cfg:logs:tail:gateway:0" in body_callbacks
    assert any(cb == "cfg:nav:close" for cb in body_callbacks)
    assert cap.sent == []


@pytest.mark.asyncio
async def test_logs_tail_callback_owner(tmp_path: Path) -> None:
    """Owner triggers `cfg:logs:tail:gateway:0` → outbound `<pre>` chunks are sent."""
    router, cap, root = _build_owner_router(tmp_path)
    # Seed a log file so tail produces a deterministic payload.
    log_dir = root / "logs"
    log_dir.mkdir(exist_ok=True)
    (log_dir / "gateway.log").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    await router.route_incoming(_logs_callback("cfg:logs:tail:gateway:0"))
    assert cap.sent, "expected tail output to be sent as new chat messages"
    bodies = [body for body, _md in cap.sent]
    joined = "\n".join(bodies)
    assert joined.startswith("<pre>")
    assert joined.endswith("</pre>")
    assert "alpha" in joined
    assert "beta" in joined
    assert "gamma" in joined


@pytest.mark.asyncio
async def test_logs_section_non_owner_blocked(tmp_path: Path) -> None:
    """Non-owner clicking a `cfg:logs:*` action gets the owner-only refusal toast."""
    router, cap, _root = _build_owner_router(tmp_path)
    msg = _logs_callback(
        "cfg:logs:tail:gateway:0",
        user_id="not-owner",
        callback_query_id="cq-block",
    )
    await router.route_incoming(msg)
    # No outbound log chunks; the owner gate runs before any file read.
    assert cap.sent == []
    assert ("cq-block", "Owner only.") in cap.answered


@pytest.mark.asyncio
async def test_logs_toggle_redaction_syncs_deny_keys_both_directions(tmp_path: Path) -> None:
    """Logs redaction toggle writes enabled flag and deny lists together."""
    from sevn.config.defaults import DEFAULT_TRACE_REDACTION_DENY_KEYS
    from sevn.gateway.config_io.workspace_config_io import load_raw_sevn_json

    router, cap, root = _build_owner_router(tmp_path)
    sevn_json = root / "sevn.json"
    await router.route_incoming(
        _logs_callback("cfg:logs:toggle_redaction", callback_query_id="cq-redact-off"),
    )
    doc = load_raw_sevn_json(sevn_json)
    redaction = doc["tracing"]["redaction"]
    assert redaction["enabled"] is False
    assert redaction["deny_keys"] == []
    assert ("cq-redact-off", "Trace redaction: off") in cap.answered

    await router.route_incoming(
        _logs_callback("cfg:logs:toggle_redaction", callback_query_id="cq-redact-on"),
    )
    doc = load_raw_sevn_json(sevn_json)
    redaction = doc["tracing"]["redaction"]
    assert redaction["enabled"] is True
    assert redaction["deny_keys"] == list(DEFAULT_TRACE_REDACTION_DENY_KEYS)
    assert "token" not in redaction["deny_keys"]
    assert ("cq-redact-on", "Trace redaction: on") in cap.answered


@pytest.mark.asyncio
async def test_logs_deployment_id_button_returns_toast(tmp_path: Path) -> None:
    """Deployment id button surfaces the router's `_deployment_id` as a toast."""
    router, cap, _root = _build_owner_router(tmp_path)
    router._deployment_id = "test-deployment-abc123"
    msg = _logs_callback(
        "cfg:logs:deployment_id",
        user_id="not-owner",  # deployment id button is not owner-gated.
        callback_query_id="cq-dep",
    )
    await router.route_incoming(msg)
    answers = dict(cap.answered)
    assert "cq-dep" in answers
    toast = answers["cq-dep"] or ""
    assert "test-deployment-abc123" in toast
