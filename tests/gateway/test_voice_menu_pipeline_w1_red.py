"""PR #50 voice menu → pipeline engine RED (green after W16)."""

from __future__ import annotations

from pathlib import Path

import pytest

from sevn.gateway.config_io.workspace_config_io import load_raw_sevn_json
from sevn.onboarding.web_app import _get_nested
from tests.gateway.test_config_menu_actions import _build_router, _config_callback


@pytest.mark.asyncio
async def test_tts_engine_round_trip_updates_router_tts_engine(tmp_path: Path) -> None:
    """Menu cycle must change the live pipeline backend ``.engine``, not only sevn.json."""
    router, cap, _ws = _build_router(tmp_path)
    await router.route_incoming(
        _config_callback("cfg:section:voice", callback_query_id="cq-nav-engine"),
    )
    await router.route_incoming(
        _config_callback("cfg:voice:engine:next", callback_query_id="cq-engine"),
    )
    raw = load_raw_sevn_json(tmp_path / "w" / "sevn.json")
    selected = _get_nested(raw, "voice.local_tts_engine")
    assert selected in {"kokoro", "supertonic"}
    tts = getattr(router, "_tts", None)
    assert tts is not None, "router._tts must be rebuilt after engine cycle"
    backends = getattr(tts, "_backends", None) or getattr(tts, "backends", None)
    assert backends, "TTS pipeline must expose backends"
    engine = getattr(backends[0], "engine", None)
    assert engine == selected
    assert any("TTS engine" in (t or "") for _cq, t in cap.answered) or any(
        "engine" in edit.get("text", "").lower() for edit in cap.edited
    )


def test_tts_pipeline_engine_skips_backends_without_engine() -> None:
    """Toast helper must find .engine even when backends[0] is a remote provider."""
    from types import SimpleNamespace

    from sevn.gateway.commands.menu_action_router import _tts_pipeline_engine

    pipe = SimpleNamespace(_backends=[SimpleNamespace(), SimpleNamespace(engine="supertonic")])
    assert _tts_pipeline_engine(pipe) == "supertonic"
    assert _tts_pipeline_engine(None) is None
