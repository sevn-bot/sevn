"""PR #49 / #50 voice TTS RED tests (green after W15 / W16)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from sevn.config.workspace_config import WorkspaceConfig
from sevn.voice.backends import TextToVoiceBackend, build_tts_backend
from sevn.voice.factory import build_tts_pipeline, voice_runtime_settings


def test_handle_voice_preserves_supertonic_code_case(tmp_path: Path) -> None:
    """``/voice F3`` must persist uppercase Supertonic code, not lowercased ``f3``."""
    from sevn.gateway.commands.core_commands import CoreCommandHandler
    from sevn.gateway.config_io.workspace_config_io import load_raw_sevn_json
    from sevn.onboarding.web_app import _get_nested

    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "gateway": {"token": "t"},
                "voice": {"local_tts_engine": "supertonic", "tts_voice_id": "M1"},
            },
        ),
        encoding="utf-8",
    )
    handler = CoreCommandHandler.__new__(CoreCommandHandler)
    handler._workspace = WorkspaceConfig.minimal()
    handler._sevn_json = sevn_json
    handler._sessions = type("S", (), {"set_tts_mode_override": lambda *_a, **_k: None})()
    handler._reload_workspace = lambda: None  # type: ignore[method-assign]
    msg = handler._handle_voice("F3", session_id="sess")
    assert "F3" in msg or "set" in msg.lower()
    raw = load_raw_sevn_json(sevn_json)
    assert _get_nested(raw, "voice.tts_voice_id") == "F3"


@pytest.mark.asyncio
async def test_legacy_kokoro_synthesize_omits_engine_flag(tmp_path: Path) -> None:
    skill = tmp_path / "skills" / "core" / "kokoro-tts" / "scripts"
    skill.mkdir(parents=True)
    (skill / "generate.py").write_text(
        "#!/usr/bin/env python3\nimport sys\n"
        "if '--engine' in sys.argv:\n    raise SystemExit(2)\n"
        "print(sys.argv[-1])\n",
        encoding="utf-8",
    )
    out = tmp_path / "out.wav"
    out.write_bytes(b"wav")
    proc = AsyncMock()
    proc.returncode = 0
    proc.communicate = AsyncMock(return_value=(str(out).encode(), b""))
    with patch("sevn.voice.backends.asyncio.create_subprocess_exec", return_value=proc) as mocked:
        backend = TextToVoiceBackend(workspace_root=tmp_path, engine="kokoro")
        await backend.synthesize(text="hi", voice_id="af_heart", out_path=out)
    cmd = mocked.call_args.args
    assert "--engine" not in cmd


def test_build_tts_pipeline_passes_local_tts_engine(tmp_path: Path) -> None:
    ws = WorkspaceConfig.minimal(
        voice={"local_tts_engine": "supertonic", "tts_providers": ["text_to_voice"]},
    )
    pipeline = build_tts_pipeline(ws, content_root=tmp_path, trace=None)
    backends = getattr(pipeline, "_backends", None) or getattr(pipeline, "backends", None)
    assert backends
    engine = getattr(backends[0], "engine", None)
    assert engine == "supertonic"


@pytest.mark.xfail(
    reason="green after W16: VoiceRuntimeSettings local_tts_engine field", strict=False
)
def test_voice_runtime_settings_exposes_local_tts_engine() -> None:
    ws = WorkspaceConfig.minimal(voice={"local_tts_engine": "supertonic"})
    settings = voice_runtime_settings(ws)
    assert getattr(settings, "local_tts_engine", None) == "supertonic"


@pytest.mark.xfail(
    reason="green after W16: build_tts_backend receives engine from pipeline", strict=False
)
def test_build_tts_backend_engine_from_runtime_settings(tmp_path: Path) -> None:
    backend = build_tts_backend(
        "text_to_voice", workspace_root=tmp_path, local_tts_engine="supertonic"
    )
    assert backend.engine == "supertonic"
    # Pipeline path must thread the same value (see factory.build_tts_pipeline).
    ws = WorkspaceConfig.minimal(
        voice={"local_tts_engine": "supertonic", "tts_providers": ["text_to_voice"]},
    )
    pipeline = build_tts_pipeline(ws, content_root=tmp_path, trace=None)
    backends = getattr(pipeline, "_backends", None) or getattr(pipeline, "backends", None)
    assert backends
    assert backends[0].engine == "supertonic"
