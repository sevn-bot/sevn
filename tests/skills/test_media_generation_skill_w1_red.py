"""PR #36 / #48 RED media execute + script coverage (green after W3 / W14).

Companion RED suite for ``test_media_generation_skill.py`` — audit-required
behavioral paths that were missing from the structural suite.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from sevn.agent.subagents.media_worker import execute_media_generator_task
from sevn.config.sections.subagents import SpecialistConfig, SubAgentsWorkspaceConfig
from sevn.storage.migrate import apply_migrations
from sevn.storage.paths import sevn_db_path

_SKILL_ROOT = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "sevn"
    / "data"
    / "bundled_skills"
    / "core"
    / "media_generation"
)
_SCRIPTS = _SKILL_ROOT / "scripts"

_MEDIA_CFG = SubAgentsWorkspaceConfig(
    specialists={
        "media_generator": SpecialistConfig(
            model="minimax-3",
            provider="minimax",
            assigned_to=["tier_b"],
            requestable_by=["triager", "tier_b"],
            max_concurrent=2,
            skill="media_generation",
        ),
    },
)


@pytest.fixture
def media_workspace(tmp_path: Path) -> tuple[Path, sqlite3.Connection]:
    """Minimal workspace with migrated DB and sevn.json stub."""
    dot_sevn = tmp_path / ".sevn"
    dot_sevn.mkdir(parents=True)
    conn = sqlite3.connect(str(sevn_db_path(dot_sevn)))
    apply_migrations(conn)
    (tmp_path / "sevn.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "gateway": {"token": "test-token"},
                "providers": {"minimax": {"api_key": "sk-test-minimax"}},
                "subagents": {
                    "specialists": {
                        "media_generator": {
                            "model": "minimax-3",
                            "provider": "minimax",
                            "assigned_to": ["tier_b"],
                            "requestable_by": ["triager", "tier_b"],
                            "max_concurrent": 2,
                            "skill": "media_generation",
                        },
                    },
                },
            },
        ),
        encoding="utf-8",
    )
    return tmp_path, conn


def _load_script(script_name: str) -> Any:
    script = _SCRIPTS / script_name
    assert script.is_file(), f"missing bundled script {script_name}"
    spec = importlib.util.spec_from_file_location(f"media_{script.stem}", script)
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    if str(_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS))
    spec.loader.exec_module(mod)
    return mod


class TestExtendedMediaKindsW3:
    """PR #36 — five execute paths lacking behavioral coverage."""

    @pytest.mark.asyncio
    async def test_image_i2i_returns_trace(
        self,
        media_workspace: tuple[Path, sqlite3.Connection],
    ) -> None:
        workspace, conn = media_workspace
        ref = workspace / "ref.jpg"
        ref.write_bytes(b"\xff\xd8\xff ref")
        image_bytes = b"\xff\xd8\xff out"
        with (
            patch.dict(os.environ, {"MINIMAX_API_KEY": "sk-test-minimax"}),
            patch(
                "sevn.agent.subagents.media_worker.generate_image_from_reference_bytes",
                new=AsyncMock(return_value=image_bytes),
            ),
        ):
            result = await execute_media_generator_task(
                json.dumps(
                    {
                        "kind": "image_i2i",
                        "prompt": "oil paint",
                        "reference_image": str(ref),
                    },
                ),
                session_id="sess-i2i",
                content_root=workspace,
                conn=conn,
                subagents_cfg=_MEDIA_CFG,
            )
        assert result["kind"] == "image_i2i"
        assert "trace" in result
        artifact = workspace / str(result["artifact_path"])
        assert artifact.is_file()
        assert artifact.read_bytes() == image_bytes

    @pytest.mark.asyncio
    async def test_video_s2v_returns_trace(
        self,
        media_workspace: tuple[Path, sqlite3.Connection],
    ) -> None:
        workspace, conn = media_workspace
        subject = workspace / "subject.jpg"
        subject.write_bytes(b"\xff\xd8\xff subject")
        video_bytes = b"\x00\x00\x00\x18ftypmp4"
        with (
            patch.dict(os.environ, {"MINIMAX_API_KEY": "sk-test-minimax"}),
            patch(
                "sevn.agent.subagents.media_worker.generate_video_subject_reference_bytes",
                new=AsyncMock(return_value=video_bytes),
            ),
        ):
            result = await execute_media_generator_task(
                json.dumps(
                    {
                        "kind": "video_s2v",
                        "prompt": "walk cycle",
                        "subject_reference": str(subject),
                    },
                ),
                session_id="sess-s2v",
                content_root=workspace,
                conn=conn,
                subagents_cfg=_MEDIA_CFG,
            )
        assert result["kind"] == "video_s2v"
        assert (workspace / str(result["artifact_path"])).read_bytes() == video_bytes

    @pytest.mark.asyncio
    async def test_video_fl2v_returns_trace(
        self,
        media_workspace: tuple[Path, sqlite3.Connection],
    ) -> None:
        workspace, conn = media_workspace
        first = workspace / "first.jpg"
        last = workspace / "last.jpg"
        first.write_bytes(b"\xff\xd8\xff a")
        last.write_bytes(b"\xff\xd8\xff b")
        video_bytes = b"\x00\x00\x00\x18ftypmp4"
        with (
            patch.dict(os.environ, {"MINIMAX_API_KEY": "sk-test-minimax"}),
            patch(
                "sevn.agent.subagents.media_worker.generate_video_first_last_frame_bytes",
                new=AsyncMock(return_value=video_bytes),
            ),
        ):
            result = await execute_media_generator_task(
                json.dumps(
                    {
                        "kind": "video_fl2v",
                        "prompt": "morph",
                        "first_frame_image": str(first),
                        "last_frame_image": str(last),
                    },
                ),
                session_id="sess-fl2v",
                content_root=workspace,
                conn=conn,
                subagents_cfg=_MEDIA_CFG,
            )
        assert result["kind"] == "video_fl2v"
        assert (workspace / str(result["artifact_path"])).read_bytes() == video_bytes

    @pytest.mark.asyncio
    async def test_video_template_returns_trace(
        self,
        media_workspace: tuple[Path, sqlite3.Connection],
    ) -> None:
        workspace, conn = media_workspace
        media = workspace / "pet.jpg"
        media.write_bytes(b"\xff\xd8\xff pet")
        video_bytes = b"\x00\x00\x00\x18ftypmp4"
        with (
            patch.dict(os.environ, {"MINIMAX_API_KEY": "sk-test-minimax"}),
            patch(
                "sevn.agent.subagents.media_worker.generate_video_template_bytes",
                new=AsyncMock(return_value=video_bytes),
            ),
        ):
            result = await execute_media_generator_task(
                json.dumps(
                    {
                        "kind": "video_template",
                        "template_id": "pet_pilot",
                        "media_inputs": [str(media)],
                    },
                ),
                session_id="sess-tmpl",
                content_root=workspace,
                conn=conn,
                subagents_cfg=_MEDIA_CFG,
            )
        assert result["kind"] == "video_template"
        assert (workspace / str(result["artifact_path"])).read_bytes() == video_bytes

    @pytest.mark.asyncio
    async def test_voice_clone_returns_trace(
        self,
        media_workspace: tuple[Path, sqlite3.Connection],
    ) -> None:
        workspace, conn = media_workspace
        sample = workspace / "sample.mp3"
        sample.write_bytes(b"ID3sample")
        audio_bytes = b"ID3out"
        clone = AsyncMock(return_value=("voice-id-1", audio_bytes))
        with (
            patch.dict(os.environ, {"MINIMAX_API_KEY": "sk-test-minimax"}),
            patch(
                "sevn.agent.subagents.media_worker.clone_voice_bytes",
                new=clone,
            ),
        ):
            result = await execute_media_generator_task(
                json.dumps(
                    {
                        "kind": "voice",
                        "prompt": "narrator",
                        "source_audio": str(sample),
                        "preview_text": "Hello clone",
                    },
                ),
                session_id="sess-clone",
                content_root=workspace,
                conn=conn,
                subagents_cfg=_MEDIA_CFG,
            )
        assert result["kind"] == "voice"
        assert clone.await_args is not None
        assert (workspace / str(result["artifact_path"])).read_bytes() == audio_bytes


class TestMediaGenerationScriptsW3:
    """PR #36 — bundled scripts without subprocess coverage."""

    def test_generate_image_from_reference_script_mocked(
        self,
        media_workspace: tuple[Path, sqlite3.Connection],
    ) -> None:
        workspace, _conn = media_workspace
        ref = workspace / "ref.jpg"
        ref.write_bytes(b"\xff\xd8\xff")
        mod = _load_script("generate_image_from_reference.py")
        with (
            patch.object(sys, "argv", ["generate_image_from_reference.py", "style", str(ref)]),
            patch.dict(
                os.environ,
                {
                    "SEVN_CONTENT_ROOT": str(workspace),
                    "SEVN_SESSION_ID": "sess-script",
                    "MINIMAX_API_KEY": "sk-test-minimax",
                },
            ),
            patch.object(mod, "run_media_generation", return_value=0) as mocked,
        ):
            assert mod.main() == 0
        mocked.assert_called_once()
        assert mocked.call_args.args[0] == "image_i2i"

    def test_generate_video_from_image_script_mocked(
        self,
        media_workspace: tuple[Path, sqlite3.Connection],
    ) -> None:
        workspace, _conn = media_workspace
        frame = workspace / "frame.jpg"
        frame.write_bytes(b"\xff\xd8\xff")
        mod = _load_script("generate_video_from_image.py")
        with (
            patch.object(sys, "argv", ["generate_video_from_image.py", "wind", str(frame)]),
            patch.dict(
                os.environ,
                {
                    "SEVN_CONTENT_ROOT": str(workspace),
                    "SEVN_SESSION_ID": "sess-script",
                    "MINIMAX_API_KEY": "sk-test-minimax",
                },
            ),
            patch.object(mod, "run_media_generation", return_value=0) as mocked,
        ):
            assert mod.main() == 0
        mocked.assert_called_once()

    def test_generate_video_template_script_mocked(
        self,
        media_workspace: tuple[Path, sqlite3.Connection],
    ) -> None:
        workspace, _conn = media_workspace
        mod = _load_script("generate_video_template.py")
        with (
            patch.object(sys, "argv", ["generate_video_template.py", "pet_pilot"]),
            patch.dict(
                os.environ,
                {
                    "SEVN_CONTENT_ROOT": str(workspace),
                    "SEVN_SESSION_ID": "sess-script",
                    "MINIMAX_API_KEY": "sk-test-minimax",
                },
            ),
            patch.object(mod, "run_media_generation", return_value=0) as mocked,
        ):
            assert mod.main() == 0
        mocked.assert_called_once()

    def test_replicate_voice_script_mocked(
        self,
        media_workspace: tuple[Path, sqlite3.Connection],
    ) -> None:
        workspace, _conn = media_workspace
        sample = workspace / "s.mp3"
        sample.write_bytes(b"ID3")
        mod = _load_script("replicate_voice.py")
        with (
            patch.object(
                sys,
                "argv",
                ["replicate_voice.py", "clone", "Hello", str(sample)],
            ),
            patch.dict(
                os.environ,
                {
                    "SEVN_CONTENT_ROOT": str(workspace),
                    "SEVN_SESSION_ID": "sess-script",
                    "MINIMAX_API_KEY": "sk-test-minimax",
                },
            ),
            patch.object(mod, "run_media_generation", return_value=0) as mocked,
        ):
            assert mod.main() == 0
        mocked.assert_called_once()

    def test_list_prompt_templates_script(self) -> None:
        mod = _load_script("list_prompt_templates.py")
        with patch.object(sys, "argv", ["list_prompt_templates.py"]):
            assert mod.main() == 0

    def test_list_video_templates_script(self) -> None:
        mod = _load_script("list_video_templates.py")
        with patch.object(sys, "argv", ["list_video_templates.py"]):
            assert mod.main() == 0


class TestMediaGenerationScriptsW14:
    """PR #48 — S2V / FL2V CLIs + voice-clone literal text."""

    @pytest.mark.xfail(reason="green after W14: generate_video_subject script", strict=False)
    def test_generate_video_subject_script_mocked(
        self,
        media_workspace: tuple[Path, sqlite3.Connection],
    ) -> None:
        workspace, _conn = media_workspace
        subject = workspace / "face.jpg"
        subject.write_bytes(b"\xff\xd8\xff")
        mod = _load_script("generate_video_subject.py")
        with (
            patch.object(
                sys,
                "argv",
                ["generate_video_subject.py", "walk", str(subject)],
            ),
            patch.dict(
                os.environ,
                {
                    "SEVN_CONTENT_ROOT": str(workspace),
                    "SEVN_SESSION_ID": "sess-script",
                    "MINIMAX_API_KEY": "sk-test-minimax",
                },
            ),
            patch.object(mod, "run_media_generation", return_value=0) as mocked,
        ):
            assert mod.main() == 0
        assert mocked.call_args.args[0] == "video_s2v"

    @pytest.mark.xfail(reason="green after W14: generate_video_first_last script", strict=False)
    def test_generate_video_first_last_script_mocked(
        self,
        media_workspace: tuple[Path, sqlite3.Connection],
    ) -> None:
        workspace, _conn = media_workspace
        first = workspace / "a.jpg"
        last = workspace / "b.jpg"
        first.write_bytes(b"\xff\xd8\xff")
        last.write_bytes(b"\xff\xd8\xff")
        mod = _load_script("generate_video_first_last.py")
        with (
            patch.object(
                sys,
                "argv",
                ["generate_video_first_last.py", "morph", str(first), str(last)],
            ),
            patch.dict(
                os.environ,
                {
                    "SEVN_CONTENT_ROOT": str(workspace),
                    "SEVN_SESSION_ID": "sess-script",
                    "MINIMAX_API_KEY": "sk-test-minimax",
                },
            ),
            patch.object(mod, "run_media_generation", return_value=0) as mocked,
        ):
            assert mod.main() == 0
        assert mocked.call_args.args[0] == "video_fl2v"

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="green after W14: voice-clone literal preview_text", strict=False)
    async def test_voice_clone_passes_literal_preview_text(
        self,
        media_workspace: tuple[Path, sqlite3.Connection],
    ) -> None:
        workspace, conn = media_workspace
        sample = workspace / "sample.mp3"
        sample.write_bytes(b"ID3sample")
        clone = AsyncMock(return_value=("vid-1", b"ID3out"))
        with (
            patch.dict(os.environ, {"MINIMAX_API_KEY": "sk-test-minimax"}),
            patch(
                "sevn.agent.subagents.media_worker.clone_voice_bytes",
                new=clone,
            ),
        ):
            await execute_media_generator_task(
                json.dumps(
                    {
                        "kind": "voice",
                        "prompt": "warm narrator character notes",
                        "source_audio": str(sample),
                        "preview_text": "Literal spoken words",
                    },
                ),
                session_id="sess-lit",
                content_root=workspace,
                conn=conn,
                subagents_cfg=_MEDIA_CFG,
            )
        assert clone.await_args is not None
        kwargs = dict(clone.await_args.kwargs)
        assert kwargs.get("preview_text") == "Literal spoken words"
