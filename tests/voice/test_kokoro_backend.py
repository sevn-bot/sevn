"""Kokoro TTS backend (`voice-bidirectional` W3)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from sevn.voice.backends import KokoroBackend, _find_kokoro_skill_dir, build_tts_backend


def test_find_kokoro_skill_dir_missing() -> None:
    assert _find_kokoro_skill_dir(Path("/nonexistent")) is None


@pytest.mark.asyncio
async def test_kokoro_is_available_when_skill_present(tmp_path: Path) -> None:
    skill = tmp_path / "skills" / "core" / "kokoro-tts" / "scripts"
    skill.mkdir(parents=True)
    (skill / "generate.py").write_text("print('ok')", encoding="utf-8")
    backend = KokoroBackend(workspace_root=tmp_path)
    assert await backend.is_available()


@pytest.mark.asyncio
async def test_kokoro_synthesize_mock_subprocess(tmp_path: Path) -> None:
    skill = tmp_path / "skills" / "core" / "kokoro-tts" / "scripts"
    skill.mkdir(parents=True)
    (skill / "generate.py").write_text("print('ok')", encoding="utf-8")
    out = tmp_path / "reply.ogg"
    out.write_bytes(b"audio-bytes")
    proc = AsyncMock()
    proc.returncode = 0
    proc.communicate = AsyncMock(return_value=(str(out).encode(), b""))

    with patch("sevn.voice.backends.asyncio.create_subprocess_exec", return_value=proc):
        backend = KokoroBackend(workspace_root=tmp_path)
        await backend.synthesize(text="hi", voice_id=None, out_path=out)
    assert out.read_bytes() == b"audio-bytes"


def test_build_tts_backend_kokoro_tag() -> None:
    assert build_tts_backend("kokoro").id == "kokoro"
