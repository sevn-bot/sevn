"""Unified text-to-voice TTS backend (kokoro / supertonic engines)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from sevn.voice.backends import (
    KokoroBackend,
    TextToVoiceBackend,
    _find_text_to_voice_skill_dir,
    build_tts_backend,
    validate_voice_backend_tags,
)


def test_find_text_to_voice_skill_dir_missing() -> None:
    assert _find_text_to_voice_skill_dir(Path("/nonexistent")) is None


@pytest.mark.asyncio
async def test_text_to_voice_is_available_when_skill_present(tmp_path: Path) -> None:
    """Skill discovery + engine tag; synthesize CLI routing covered in sibling tests."""
    skill = tmp_path / "skills" / "core" / "text-to-voice" / "scripts"
    skill.mkdir(parents=True)
    (skill / "generate.py").write_text("print('ok')\n# --engine\n", encoding="utf-8")
    backend = TextToVoiceBackend(workspace_root=tmp_path, engine="supertonic")
    assert await backend.is_available()
    assert backend.engine == "supertonic"


@pytest.mark.asyncio
async def test_legacy_kokoro_tts_skill_path_still_discovered(tmp_path: Path) -> None:
    skill = tmp_path / "skills" / "core" / "kokoro-tts" / "scripts"
    skill.mkdir(parents=True)
    (skill / "generate.py").write_text("print('ok')", encoding="utf-8")
    assert _find_text_to_voice_skill_dir(tmp_path) == skill.parent
    backend = TextToVoiceBackend(workspace_root=tmp_path, engine="kokoro")
    assert await backend.is_available()
    # Legacy scripts lack ``--engine``; synthesize must omit the flag (W15.2).
    out = tmp_path / "legacy.wav"
    out.write_bytes(b"wav")
    proc = AsyncMock()
    proc.returncode = 0
    proc.communicate = AsyncMock(return_value=(str(out).encode(), b""))
    with patch("sevn.voice.backends.asyncio.create_subprocess_exec", return_value=proc) as mocked:
        await backend.synthesize(text="hi", voice_id="af_heart", out_path=out)
    assert "--engine" not in mocked.call_args.args


@pytest.mark.asyncio
async def test_text_to_voice_synthesize_passes_engine(tmp_path: Path) -> None:
    skill = tmp_path / "skills" / "core" / "text-to-voice" / "scripts"
    skill.mkdir(parents=True)
    (skill / "generate.py").write_text(
        'print("ok")  # argparse: "--engine"\n',
        encoding="utf-8",
    )
    (tmp_path / "skills" / "core" / "text-to-voice" / "requirements-supertonic.txt").write_text(
        "supertonic\n",
        encoding="utf-8",
    )
    out = tmp_path / "reply.wav"
    out.write_bytes(b"audio-bytes")
    proc = AsyncMock()
    proc.returncode = 0
    proc.communicate = AsyncMock(return_value=(str(out).encode(), b""))

    with patch("sevn.voice.backends.asyncio.create_subprocess_exec", return_value=proc) as mocked:
        backend = TextToVoiceBackend(workspace_root=tmp_path, engine="supertonic")
        await backend.synthesize(text="hi", voice_id="M1", out_path=out)
    assert out.read_bytes() == b"audio-bytes"
    cmd = mocked.call_args.args
    assert "--engine" in cmd
    assert cmd[cmd.index("--engine") + 1] == "supertonic"
    assert "--voice" in cmd
    assert cmd[cmd.index("--voice") + 1] == "M1"
    assert any("requirements-supertonic.txt" in str(part) for part in cmd)


def test_build_tts_backend_text_to_voice_and_kokoro_alias() -> None:
    tv = build_tts_backend("text_to_voice", local_tts_engine="supertonic")
    assert tv.id == "text_to_voice"
    assert isinstance(tv, TextToVoiceBackend)
    assert tv.engine == "supertonic"

    alias = build_tts_backend("kokoro")
    assert alias.id == "kokoro"
    assert isinstance(alias, KokoroBackend)
    assert alias.engine == "kokoro"


def test_validate_voice_backend_tags_accepts_text_to_voice() -> None:
    validate_voice_backend_tags(["whisper_cpp"], ["text_to_voice", "edge_tts"])
