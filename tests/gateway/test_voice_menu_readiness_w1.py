"""Wave W1 tests: voice/TTS menu readiness (`build-plan-from-review/waves/
voice-duplex-tts-menu-log-fixes-wave-plan.md` W1.4-W1.5).

``C3.1``/``C3.2``/``C3.3`` (``cfg:voice:mode:off|all|when_asked``) are
``implemented=True`` in the registry but omitted from ``_READY_SPEC_IDS``, so
today they render as ``cfg:disabled:C3.x`` and are gated out of the live
keyboard. ``C3.4`` (STT provider cycle) has no handler yet. These assertions
are expected to be RED until Wave W4 lands.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sevn.gateway.commands.menu_action_router import parse_action_callback
from sevn.gateway.config_io.workspace_config_io import load_raw_sevn_json
from sevn.gateway.menu.menu_readiness import gate_config_keyboard_rows, readiness_for_callback
from sevn.gateway.menu.menu_registry import match_menu_button_spec
from sevn.onboarding.web_app import _get_nested
from tests.gateway.test_config_menu_actions import _build_router, _config_callback

# --- W1.4: menu readiness --------------------------------------------------


@pytest.mark.parametrize("mode", ["off", "all", "when_asked"])
def test_voice_mode_callback_is_ready(mode: str) -> None:
    assert readiness_for_callback(f"cfg:voice:mode:{mode}") == "Ready"


@pytest.mark.parametrize("mode", ["off", "all", "when_asked"])
def test_voice_mode_button_not_rewritten_to_disabled(mode: str) -> None:
    rows = [[{"text": f"TTS: {mode}", "callback_data": f"cfg:voice:mode:{mode}"}]]
    gated = gate_config_keyboard_rows(rows)
    cb = gated[0][0]["callback_data"]
    assert not cb.startswith("cfg:disabled:"), f"{mode} button was locked: {gated}"
    assert cb == f"cfg:voice:mode:{mode}"


def test_stt_cycle_spec_resolves_to_c3_4() -> None:
    """``C3.4`` is registered — the readiness gate, not spec matching, is what's missing."""
    spec = match_menu_button_spec("cfg:voice:stt:next")
    assert spec is not None
    assert spec.spec_id == "C3.4"


def test_stt_cycle_callback_parses_and_cycles() -> None:
    """W4.2: ``cfg:voice:stt:*`` must resolve through the action router like ``voice:mode``."""
    parsed = parse_action_callback("cfg:voice:stt:next")
    assert parsed is not None, "cfg:voice:stt:next does not parse — C3.4 handler is missing"
    kind, target, _value = parsed
    assert kind in {"toggle", "action"}
    assert "stt" in target


# --- W1.5: round trip mutates config + menu reflects new value -------------


@pytest.mark.asyncio
async def test_voice_mode_round_trip_persists_to_sevn_json(tmp_path: Path) -> None:
    router, cap, ws = _build_router(tmp_path)
    await router.route_incoming(
        _config_callback("cfg:section:voice", callback_query_id="cq-nav"),
    )
    await router.route_incoming(
        _config_callback("cfg:voice:mode:when_asked", callback_query_id="cq-toggle"),
    )
    raw = load_raw_sevn_json(tmp_path / "w" / "sevn.json")
    assert _get_nested(raw, "voice.tts_mode") == "when_asked"
    assert any("TTS mode: when_asked" in edit.get("text", "") for edit in cap.edited)
    assert cap.sent == []
    _ = ws
