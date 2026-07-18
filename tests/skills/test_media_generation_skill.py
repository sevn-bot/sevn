"""Tests for ``media_generation`` skill + ``media_generator`` specialist (W8.4)."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from sevn.agent.subagents.media_worker import (
    MEDIA_GENERATOR_UNCONFIGURED,
    execute_media_generator_task,
    parse_media_task,
    require_media_generator,
)
from sevn.agent.subagents.registry import SubAgentRegistry
from sevn.agent.subagents.specialists import merge_specialist_grants
from sevn.agent.subagents.supervisor import SubAgentSupervisor
from sevn.config.sections.subagents import SpecialistConfig, SubAgentsWorkspaceConfig
from sevn.storage.migrate import apply_migrations
from sevn.storage.paths import sevn_db_path
from sevn.tools.context import ToolContext
from sevn.tools.subagent_spawn import spawn_subagent_tool

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
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
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


def _ctx(
    *,
    supervisor: SubAgentSupervisor | None,
    parent_id: str | None = "l1-parent",
    workspace: Path | None = None,
) -> ToolContext:
    return ToolContext(
        session_id="sess-media",
        workspace_path=workspace or Path("/tmp/w"),
        workspace_id="w1",
        registry_version=1,
        delivery_channel="telegram",
        subagent_supervisor=supervisor,
        subagent_role="tier_b",
        subagent_parent_id=parent_id,
    )


async def _register_parent(registry: SubAgentRegistry) -> str:
    run = await registry.register(
        level=1,
        role="tier_b",
        session_id="sess-media",
        channel="telegram",
        task_summary="parent",
    )
    await registry.mark_running(run.id)
    return run.id


class TestParseMediaTask:
    """Unit tests for task parsing."""

    def test_json_task(self) -> None:
        task = parse_media_task('{"kind":"video","prompt":"waves"}')
        assert task.kind == "video"
        assert task.prompt == "waves"

    def test_shorthand_task(self) -> None:
        task = parse_media_task("music:lofi beat")
        assert task.kind == "music"

    def test_video_i2v_task(self) -> None:
        task = parse_media_task(
            '{"kind":"video_i2v","prompt":"wind","first_frame_image":"photo.jpg","template":"subtle"}',
        )
        assert task.kind == "video_i2v"
        assert task.first_frame_image == "photo.jpg"
        assert task.template_key == "subtle"

    def test_video_template_task(self) -> None:
        task = parse_media_task(
            '{"kind":"video_template","template_id":"pet_pilot","media_inputs":["pet.jpg"]}',
        )
        assert task.kind == "video_template"
        assert task.template_id == "pet_pilot"

    def test_voice_clone_task(self) -> None:
        task = parse_media_task(
            '{"kind":"voice","prompt":"narrator","source_audio":"sample.mp3","preview_text":"Hi"}',
        )
        assert task.kind == "voice"
        assert task.source_audio == "sample.mp3"

    def test_voice_shorthand_rejected(self) -> None:
        """``voice:`` shorthand is rejected; JSON task required."""
        with pytest.raises(ValueError, match="voice shorthand unsupported"):
            parse_media_task("voice:hello there")


class TestSkillSpecialistBinding:
    """W8.3 skill→specialist grant merge."""

    def test_merge_grants_from_skill_name(self) -> None:
        grants = merge_specialist_grants([], ["media_generation"], _MEDIA_CFG)
        assert grants == frozenset({"media_generator"})


class TestMediaGeneratorSpawn:
    """End-to-end spawn path with mocked MiniMax transport."""

    @pytest.mark.asyncio
    async def test_spawn_wait_returns_artifact_path(
        self,
        media_workspace: tuple[Path, sqlite3.Connection],
    ) -> None:
        workspace, conn = media_workspace
        image_bytes = b"\xff\xd8\xff fake jpeg"
        registry = SubAgentRegistry()
        supervisor = SubAgentSupervisor(registry, config=_MEDIA_CFG)
        parent_id = await _register_parent(registry)
        ctx = _ctx(supervisor=supervisor, parent_id=parent_id, workspace=workspace)

        with (
            patch.dict(os.environ, {"MINIMAX_API_KEY": "sk-test-minimax"}),
            patch(
                "sevn.lcm.script_cli.open_workspace_db",
                return_value=conn,
            ),
            patch(
                "sevn.agent.subagents.media_worker.generate_image_bytes",
                new=AsyncMock(return_value=image_bytes),
            ),
        ):
            out = json.loads(
                await spawn_subagent_tool(
                    ctx,
                    task='{"kind":"image","prompt":"a fox"}',
                    specialist="media_generator",
                    wait=True,
                ),
            )

        assert out["ok"] is True
        result = json.loads(out["data"]["result"])
        assert result["kind"] == "image"
        assert str(result["artifact_path"]).startswith("channel_files/sess-media/")
        assert "trace" in result
        assert result["trace"]["user_request"] == "a fox"
        artifact = workspace / str(result["artifact_path"])
        assert artifact.is_file()
        assert artifact.read_bytes() == image_bytes

    @pytest.mark.asyncio
    async def test_unconfigured_specialist_error(self) -> None:
        from sevn.agent.subagents.media_minimax import MiniMaxMediaError

        with pytest.raises(MiniMaxMediaError) as exc:
            require_media_generator(None)
        assert MEDIA_GENERATOR_UNCONFIGURED in str(exc.value)


class TestMediaGenerationScripts:
    """Bundled skill script subprocess tests."""

    def _run_script(
        self,
        script_name: str,
        workspace: Path,
        cli_args: list[str],
    ) -> dict[str, Any]:
        script = _SCRIPTS / script_name
        env = os.environ.copy()
        env["SEVN_CONTENT_ROOT"] = str(workspace)
        env["SEVN_SESSION_ID"] = "sess-script"
        env["MINIMAX_API_KEY"] = "sk-test-minimax"
        proc = subprocess.run(
            [sys.executable, str(script), *cli_args],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        return json.loads(proc.stdout.strip())

    def test_generate_image_script_mocked(
        self,
        media_workspace: tuple[Path, sqlite3.Connection],
    ) -> None:
        workspace, _conn = media_workspace
        image_bytes = b"\xff\xd8\xff jpeg"
        spec = importlib.util.spec_from_file_location(
            "generate_image",
            _SCRIPTS / "generate_image.py",
        )
        assert spec is not None
        assert spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        if str(_SCRIPTS) not in sys.path:
            sys.path.insert(0, str(_SCRIPTS))
        spec.loader.exec_module(mod)
        with (
            patch.object(sys, "argv", ["generate_image.py", "a blue moon"]),
            patch.dict(
                os.environ,
                {
                    "SEVN_CONTENT_ROOT": str(workspace),
                    "SEVN_SESSION_ID": "sess-script",
                    "MINIMAX_API_KEY": "sk-test-minimax",
                },
            ),
            patch(
                "sevn.agent.subagents.media_worker.generate_image_bytes",
                new=AsyncMock(return_value=image_bytes),
            ),
        ):
            rc = mod.main()
        assert rc == 0

    def test_generate_image_unconfigured(self, tmp_path: Path) -> None:
        dot_sevn = tmp_path / ".sevn"
        dot_sevn.mkdir(parents=True)
        (tmp_path / "sevn.json").write_text(
            json.dumps({"schema_version": 1, "gateway": {"token": "t"}, "subagents": {}}),
            encoding="utf-8",
        )
        payload = self._run_script("generate_image.py", tmp_path, ["test"])
        assert payload["ok"] is False
        assert "media_generator" in str(payload.get("error", ""))


class TestSpecialistConcurrency:
    """``max_concurrent`` respected under parallel spawn calls."""

    @pytest.mark.asyncio
    async def test_parallel_spawns_hit_specialist_limit(
        self,
        media_workspace: tuple[Path, sqlite3.Connection],
    ) -> None:
        workspace, conn = media_workspace
        image_bytes = b"\xff\xd8\xff jpeg"

        async def slow_image(*_args: object, **_kwargs: object) -> bytes:
            await asyncio.sleep(0.05)
            return image_bytes

        registry = SubAgentRegistry()
        supervisor = SubAgentSupervisor(registry, config=_MEDIA_CFG)
        parent_id = await _register_parent(registry)
        ctx = _ctx(supervisor=supervisor, parent_id=parent_id, workspace=workspace)

        with (
            patch.dict(os.environ, {"MINIMAX_API_KEY": "sk-test-minimax"}),
            patch("sevn.lcm.script_cli.open_workspace_db", return_value=conn),
            patch(
                "sevn.agent.subagents.media_worker.generate_image_bytes",
                new=AsyncMock(side_effect=slow_image),
            ),
        ):
            first = json.loads(
                await spawn_subagent_tool(
                    ctx,
                    task="image:one",
                    specialist="media_generator",
                    wait=False,
                ),
            )
            second = json.loads(
                await spawn_subagent_tool(
                    ctx,
                    task="image:two",
                    specialist="media_generator",
                    wait=False,
                ),
            )
            third = json.loads(
                await spawn_subagent_tool(
                    ctx,
                    task="image:three",
                    specialist="media_generator",
                    wait=False,
                ),
            )

        assert first["ok"] is True
        assert second["ok"] is True
        assert third["ok"] is False
        assert "limit exceeded" in str(third.get("error", "")).lower()


class TestExtendedMediaKinds:
    """New media kinds with mocked MiniMax transport."""

    @pytest.mark.asyncio
    async def test_video_i2v_returns_trace(
        self,
        media_workspace: tuple[Path, sqlite3.Connection],
    ) -> None:
        workspace, conn = media_workspace
        video_bytes = b"\x00\x00\x00\x18ftypmp4"
        image_path = workspace / "frame.jpg"
        image_path.write_bytes(b"\xff\xd8\xff fake")

        with (
            patch.dict(os.environ, {"MINIMAX_API_KEY": "sk-test-minimax"}),
            patch(
                "sevn.agent.subagents.media_worker.generate_video_from_image_bytes",
                new=AsyncMock(return_value=video_bytes),
            ),
        ):
            result = await execute_media_generator_task(
                json.dumps(
                    {
                        "kind": "video_i2v",
                        "prompt": "gentle wind",
                        "first_frame_image": str(image_path),
                        "template": "subtle",
                    },
                ),
                session_id="sess-i2v",
                content_root=workspace,
                conn=conn,
                subagents_cfg=_MEDIA_CFG,
            )

        assert result["kind"] == "video_i2v"
        trace = result["trace"]
        assert isinstance(trace, dict)
        assert trace["template_key"] == "subtle"
        assert "gentle wind" in str(trace["augmented_prompt"])

    @pytest.mark.asyncio
    async def test_voice_speak_uses_literal_speech_text(
        self,
        media_workspace: tuple[Path, sqlite3.Connection],
    ) -> None:
        """TTS API receives literal speech_text; augmentation stays in trace."""
        workspace, conn = media_workspace
        audio_bytes = b"ID3fake"
        synthesize = AsyncMock(return_value=audio_bytes)

        with (
            patch.dict(os.environ, {"MINIMAX_API_KEY": "sk-test-minimax"}),
            patch(
                "sevn.agent.subagents.media_worker.synthesize_speech_bytes",
                new=synthesize,
            ),
        ):
            result = await execute_media_generator_task(
                json.dumps(
                    {
                        "kind": "voice",
                        "prompt": "calm narrator",
                        "template": "narration",
                        "voice_id": "English_expressive_narrator",
                        "speech_text": "Hello world",
                        "delivery": "warm",
                        "mood": "friendly",
                    },
                ),
                session_id="sess-voice",
                content_root=workspace,
                conn=conn,
                subagents_cfg=_MEDIA_CFG,
            )

        assert result["kind"] == "voice"
        assert result["voice_id"] == "English_expressive_narrator"
        assert synthesize.await_args is not None
        # Second positional arg is the spoken text — must be literal, not augmented.
        assert synthesize.await_args.args[1] == "Hello world"
        trace = result["trace"]
        assert isinstance(trace, dict)
        assert trace["spoken_text"] == "Hello world"
        assert "voice_character_notes" in trace
        assert "Hello world" not in str(trace["voice_character_notes"])

    @pytest.mark.asyncio
    async def test_unique_filenames_for_identical_prompts(
        self,
        media_workspace: tuple[Path, sqlite3.Connection],
    ) -> None:
        """Identical prompts produce distinct artifact paths and bytes."""
        workspace, conn = media_workspace
        image_a = b"\xff\xd8\xff aaa"
        image_b = b"\xff\xd8\xff bbb"
        gen = AsyncMock(side_effect=[image_a, image_b])

        with (
            patch.dict(os.environ, {"MINIMAX_API_KEY": "sk-test-minimax"}),
            patch(
                "sevn.agent.subagents.media_worker.generate_image_bytes",
                new=gen,
            ),
        ):
            first = await execute_media_generator_task(
                '{"kind":"image","prompt":"same prompt"}',
                session_id="sess-uniq",
                content_root=workspace,
                conn=conn,
                subagents_cfg=_MEDIA_CFG,
            )
            second = await execute_media_generator_task(
                '{"kind":"image","prompt":"same prompt"}',
                session_id="sess-uniq",
                content_root=workspace,
                conn=conn,
                subagents_cfg=_MEDIA_CFG,
            )

        assert first["artifact_path"] != second["artifact_path"]
        path_a = workspace / str(first["artifact_path"])
        path_b = workspace / str(second["artifact_path"])
        assert path_a.read_bytes() == image_a
        assert path_b.read_bytes() == image_b

    @pytest.mark.asyncio
    async def test_path_escape_rejected(
        self,
        media_workspace: tuple[Path, sqlite3.Connection],
    ) -> None:
        """Reference images outside content_root are rejected."""
        from sevn.agent.subagents.media_minimax import MiniMaxMediaError

        workspace, conn = media_workspace
        outside = workspace.parent / "escape.jpg"
        outside.write_bytes(b"\xff\xd8\xff x")

        with (
            patch.dict(os.environ, {"MINIMAX_API_KEY": "sk-test-minimax"}),
            pytest.raises(MiniMaxMediaError, match="escapes workspace"),
        ):
            await execute_media_generator_task(
                json.dumps(
                    {
                        "kind": "image_i2i",
                        "prompt": "oil paint",
                        "reference_image": str(outside),
                    },
                ),
                session_id="sess-escape",
                content_root=workspace,
                conn=conn,
                subagents_cfg=_MEDIA_CFG,
            )


@pytest.mark.skipif(
    os.environ.get("SEVN_MEDIA_LIVE") != "1",
    reason="live MiniMax smoke requires SEVN_MEDIA_LIVE=1",
)
class TestMediaLiveSmoke:
    """Optional live MiniMax smoke (operator-only)."""

    @pytest.mark.asyncio
    async def test_live_image_generation(
        self,
        media_workspace: tuple[Path, sqlite3.Connection],
    ) -> None:
        workspace, conn = media_workspace
        if not os.environ.get("MINIMAX_API_KEY"):
            pytest.skip("MINIMAX_API_KEY not set")
        result = await execute_media_generator_task(
            "image:a simple red circle on white",
            session_id="live-smoke",
            content_root=workspace,
            conn=conn,
            subagents_cfg=_MEDIA_CFG,
            video_poll_interval_s=2.0,
            video_max_polls=3,
        )
        path = workspace / str(result["artifact_path"])
        assert path.is_file()
        assert path.stat().st_size > 0
