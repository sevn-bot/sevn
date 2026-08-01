"""Batch A W1.5 — voice activation menu toggles ack + setup doctor guidance (#124, D9)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sevn.gateway.channel_router import IncomingMessage
from sevn.gateway.menu.menu import _build_voice_keyboard_rows
from tests.gateway.test_config_menu_actions import _build_router, _config_callback

_VOICE_SETUP_CALLBACK = "act:voice:activation:setup"


def _activation_workspace_doc(*, enabled: bool = False) -> dict[str, object]:
    return {
        "schema_version": 1,
        "workspace_root": ".",
        "gateway": {
            "host": "127.0.0.1",
            "port": 3001,
            "queue_mode": "cancel",
            "token": "${SECRET:keychain:sevn.gateway.token}",
        },
        "voice": {
            "activation": {
                "enabled": enabled,
                "engine": "openwakeword",
                "wake_word": "hey_sevn",
            },
        },
        "security": {"scanner": {"heuristic_only": True}},
        "providers": {"use_main_model_for_all": False},
    }


def _import_voice_activation_module() -> None:
    pytest.importorskip("openwakeword", reason="voice-wake extra optional in CI")


@pytest.mark.asyncio
async def test_voice_activation_toggle_answers_callback(tmp_path: Path) -> None:
    """``cfg:toggle:voice.activation.enabled`` must ack (not silent no-op)."""
    _import_voice_activation_module()
    router, cap, _ws = _build_router(tmp_path)
    root = tmp_path / "w"
    (root / "sevn.json").write_text(
        json.dumps(_activation_workspace_doc(enabled=False)),
        encoding="utf-8",
    )
    router._menu_action_router._reload_workspace()
    await router.route_incoming(
        _config_callback("cfg:section:chat_voice", callback_query_id="cq-voice-nav"),
    )
    await router.route_incoming(
        _config_callback(
            "cfg:toggle:voice.activation.enabled:true",
            callback_query_id="cq-act-on",
        ),
    )
    assert cap.answered, "activation toggle must answer callback_query"
    toast_text = " ".join(str(t) for _cq, t in cap.answered if t)
    assert toast_text.strip(), "activation toggle must surface a toast or ✅ ack"
    assert cap.edited, "activation toggle must refresh config menu caption"


@pytest.mark.asyncio
async def test_wake_phrase_cycle_answers_when_runtime_dict_missing(tmp_path: Path) -> None:
    """Without ``_voice_activation_runtime``, wake cycle must not fail silently."""
    _import_voice_activation_module()
    router, cap, _ws = _build_router(tmp_path)
    await router.route_incoming(
        _config_callback(
            "cfg:voice:activation:wake:next",
            callback_query_id="cq-wake-cycle",
        ),
    )
    assert cap.answered or cap.edited, "wake phrase cycle must produce user-visible feedback"


def test_voice_keyboard_includes_setup_wake_word_button() -> None:
    """D9: menu-first setup entry — not gateway ``uv sync``."""
    from sevn.config.workspace_config import WorkspaceConfig

    ws = WorkspaceConfig.minimal()
    rows = _build_voice_keyboard_rows(ws)
    callbacks = [
        btn.get("callback_data")
        for row in rows
        for btn in row
        if isinstance(btn.get("callback_data"), str)
    ]
    assert _VOICE_SETUP_CALLBACK in callbacks


@pytest.mark.asyncio
async def test_voice_activation_setup_posts_doctor_guidance(tmp_path: Path) -> None:
    """Setup action runs doctor subset and documents ``voice-wake`` extra — no ``uv sync``."""
    _import_voice_activation_module()
    router, cap, _ws = _build_router(tmp_path)
    msg = IncomingMessage(
        channel="telegram",
        user_id="u1",
        text="",
        metadata={
            "callback_query_id": "cq-setup",
            "chat_id": 42,
            "message_id": 99,
            "callback_data": _VOICE_SETUP_CALLBACK,
        },
    )
    handler = getattr(router, "_menu_action_router", None)
    assert handler is not None
    route = getattr(handler, "route", None)
    assert route is not None
    await route(msg)
    combined = "\n".join(
        [str(t) for _cq, t in cap.answered if t]
        + [edit.get("text", "") for edit in cap.edited]
        + [sent[0] for sent in cap.sent],
    ).lower()
    assert "doctor" in combined or "voice-wake" in combined or "openwakeword" in combined
    assert "uv sync" not in combined
