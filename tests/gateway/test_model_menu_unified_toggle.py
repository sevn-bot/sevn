"""Batch A W1.3 — unified model toggle-off seeds slots from triager (#116).

Toggling ``providers.use_main_model_for_all`` off via Telegram must call
``fill_missing_model_slots_from_triager`` (W4).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from sevn.agent.tracing.sink import NullTraceSink
from sevn.config.loader import load_workspace
from sevn.config.model_resolution import ModelSlot, _slot_value_from_doc
from sevn.gateway.agent_turn import build_agent_run_turn
from sevn.gateway.channel_router import ChannelRouter
from sevn.gateway.commands.dispatcher import CommandDispatcher
from sevn.gateway.config_io.workspace_config_io import load_raw_sevn_json
from sevn.gateway.media.media_store import MediaStore
from sevn.gateway.runtime.rate_limit import TokenBucketLimiter
from sevn.gateway.session_manager import SessionManager
from sevn.security.llm_guard_scanner import LLMGuardScanner
from sevn.workspace.layout import WorkspaceLayout
from tests.gateway.test_config_menu_actions import _config_callback
from tests.gateway.test_menu import _conn, _MenuCaptureTelegram

_MAIN_MODEL = "test/unified-main"


def _build_unified_router(
    tmp_path: Path,
    *,
    unified: bool = True,
    tier_default: dict[str, str] | None = None,
) -> tuple[ChannelRouter, _MenuCaptureTelegram, Path]:
    root = tmp_path / "w"
    root.mkdir()
    sevn_json = root / "sevn.json"
    td = tier_default if tier_default is not None else {"triager": _MAIN_MODEL}
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
            "use_main_model_for_all": unified,
            "models": {_MAIN_MODEL: {}},
            "tier_default": td,
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
    return router, cap, root


@pytest.mark.asyncio
async def test_unified_toggle_off_seeds_all_tier_slots_from_triager(tmp_path: Path) -> None:
    """#116: disabling unified mode copies triager model into unset B/C/D slots."""
    router, cap, root = _build_unified_router(tmp_path, unified=True)
    sevn_json = root / "sevn.json"
    await router.route_incoming(
        _config_callback("cfg:section:agent", callback_query_id="cq-nav"),
    )
    await router.route_incoming(
        _config_callback(
            "cfg:toggle:providers.use_main_model_for_all:false",
            callback_query_id="cq-unified-off",
        ),
    )
    doc = load_raw_sevn_json(sevn_json)
    assert doc["providers"]["use_main_model_for_all"] is False
    for slot in (ModelSlot.tier_b, ModelSlot.tier_c, ModelSlot.tier_d):
        assert _slot_value_from_doc(doc, slot) == _MAIN_MODEL, f"{slot} not seeded"
    assert any(_MAIN_MODEL in edit.get("text", "") for edit in cap.edited), (
        "menu caption should show seeded slot ids"
    )


@pytest.mark.asyncio
async def test_unified_toggle_off_preserves_explicit_slot_overrides(tmp_path: Path) -> None:
    """Seeding must not overwrite slots that already have a distinct model id."""
    custom_b = "test/custom-b"
    router, _cap, root = _build_unified_router(
        tmp_path,
        unified=True,
        tier_default={"triager": _MAIN_MODEL, "B": custom_b},
    )
    await router.route_incoming(
        _config_callback(
            "cfg:toggle:providers.use_main_model_for_all:false",
            callback_query_id="cq-unified-off-2",
        ),
    )
    doc = load_raw_sevn_json(root / "sevn.json")
    assert _slot_value_from_doc(doc, ModelSlot.tier_b) == custom_b
    assert _slot_value_from_doc(doc, ModelSlot.tier_c) == _MAIN_MODEL
    assert _slot_value_from_doc(doc, ModelSlot.tier_d) == _MAIN_MODEL


def test_fill_missing_model_slots_from_triager_reference_behavior() -> None:
    """Document expected helper semantics (already implemented — not the menu gap)."""
    from sevn.config.model_resolution import fill_missing_model_slots_from_triager

    doc: dict[str, object] = {
        "providers": {
            "use_main_model_for_all": False,
            "tier_default": {"triager": _MAIN_MODEL},
        },
    }
    fill_missing_model_slots_from_triager(doc)  # type: ignore[arg-type]
    providers = doc["providers"]
    assert isinstance(providers, dict)
    tier = providers.get("tier_default")
    assert isinstance(tier, dict)
    assert tier.get("C") == _MAIN_MODEL
