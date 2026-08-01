"""Batch A W1.4 — Telegram triager model picker persists selection (#115)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

from sevn.agent.tracing.sink import NullTraceSink
from sevn.config.loader import load_workspace
from sevn.config.model_resolution import list_catalog_model_ids
from sevn.gateway.agent_turn import build_agent_run_turn
from sevn.gateway.channel_router import ChannelRouter
from sevn.gateway.commands.dispatcher import CommandDispatcher
from sevn.gateway.config_io.workspace_config_io import load_raw_sevn_json
from sevn.gateway.media.media_store import MediaStore
from sevn.gateway.menu.menu import build_config_menu_keyboard
from sevn.gateway.runtime.rate_limit import TokenBucketLimiter
from sevn.gateway.session_manager import SessionManager
from sevn.onboarding.web_app import _get_nested
from sevn.security.llm_guard_scanner import LLMGuardScanner
from sevn.workspace.layout import WorkspaceLayout
from tests.gateway.test_config_menu_actions import _config_callback
from tests.gateway.test_menu import _conn, _MenuCaptureTelegram

if TYPE_CHECKING:
    from sevn.config.workspace_config import WorkspaceConfig

_TRIAGER = "anthropic/claude-sonnet"
_ALT = "openai/gpt-4o-mini"


def _build_triager_picker_router(
    tmp_path: Path,
    *,
    models: dict[str, object] | None = None,
) -> tuple[ChannelRouter, _MenuCaptureTelegram, Path, WorkspaceConfig]:
    """Minimal catalog: triager set, ``providers.models`` may be empty (#115 repro)."""
    root = tmp_path / "w"
    root.mkdir()
    sevn_json = root / "sevn.json"
    model_catalog = models if models is not None else {_TRIAGER: {}, _ALT: {}}
    doc = {
        "schema_version": 1,
        "workspace_root": ".",
        "gateway": {
            "host": "127.0.0.1",
            "port": 3001,
            "queue_mode": "cancel",
            "token": "${SECRET:keychain:sevn.gateway.token}",
        },
        "providers": {
            "use_main_model_for_all": False,
            "models": model_catalog,
            "tier_default": {"triager": _TRIAGER},
        },
    }
    sevn_json.write_text(json.dumps(doc), encoding="utf-8")
    ws, _ = load_workspace(sevn_json=sevn_json)
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
    )
    router.register_adapter(cap)
    build_agent_run_turn(
        router,
        conn,
        ws,
        WorkspaceLayout(sevn_json, root),
        NullTraceSink(),
    )
    router._owner_ids = frozenset({"u1"})
    return router, cap, root, ws


@pytest.mark.xfail(
    reason="green after W4: triager catalog non-empty when only tier_default set",
    strict=False,
)
def test_triager_picker_catalog_includes_resolved_triager_when_models_empty(
    tmp_path: Path,
) -> None:
    """#115: picker must not be empty when only ``tier_default.triager`` is configured."""
    _router, _cap, _root, ws = _build_triager_picker_router(
        tmp_path,
        models={},
    )
    catalog = list_catalog_model_ids(ws)
    assert _TRIAGER in catalog
    assert len(catalog) >= 1


@pytest.mark.asyncio
@pytest.mark.xfail(reason="green after W4: triager pick persists via menu callback", strict=False)
async def test_triager_model_pick_persists_to_sevn_json(tmp_path: Path) -> None:
    """Selecting a triager row writes ``providers.tier_default.triager`` and acks."""
    router, cap, root, ws = _build_triager_picker_router(tmp_path)
    catalog = list_catalog_model_ids(ws)
    pick_idx = catalog.index(_ALT) if _ALT in catalog else 0
    expected = catalog[pick_idx]

    await router.route_incoming(
        _config_callback("cfg:section:agent", callback_query_id="cq-agent"),
    )
    await router.route_incoming(
        _config_callback(
            "cfg:models:page:triager:0",
            callback_query_id="cq-triager-page",
        ),
    )
    await router.route_incoming(
        _config_callback(
            f"cfg:models:pick:triager:{pick_idx}",
            callback_query_id="cq-triager-pick",
        ),
    )

    doc = load_raw_sevn_json(root / "sevn.json")
    assert _get_nested(doc, "providers.tier_default.triager") == expected
    joined_toasts = " ".join(str(t) for _cq, t in cap.answered if t)
    assert "Model set" in joined_toasts or any(
        expected in edit.get("text", "") for edit in cap.edited
    )


@pytest.mark.asyncio
@pytest.mark.xfail(reason="green after W4: triager picker renders pick rows", strict=False)
async def test_triager_picker_page_shows_pick_callbacks(tmp_path: Path) -> None:
    """Triager picker frame must expose ``cfg:models:pick:triager:*`` buttons."""
    router, cap, _root, _ws = _build_triager_picker_router(tmp_path)
    await router.route_incoming(
        _config_callback("cfg:models:page:triager:0", callback_query_id="cq-page"),
    )
    assert cap.edited, "picker must re-render agent menu"
    picker_cbs = [
        btn.get("callback_data")
        for row in cap.edited[-1]["reply_markup"]["inline_keyboard"]
        for btn in row
        if isinstance(btn.get("callback_data"), str)
    ]
    assert any(cb.startswith("cfg:models:pick:triager:") for cb in picker_cbs)


def test_agent_section_exposes_triager_picker_entry(tmp_path: Path) -> None:
    """Navigation contract: agent section lists Pick Triager (baseline — should pass)."""
    _router, _cap, _root, ws = _build_triager_picker_router(tmp_path)
    kb = build_config_menu_keyboard(ws, section="agent")
    callbacks = [
        btn.get("callback_data")
        for row in kb["inline_keyboard"]
        for btn in row
        if btn.get("callback_data")
    ]
    assert "cfg:models:page:triager:0" in callbacks
