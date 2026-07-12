"""Bundled ``cursor_cloud`` skill gates and script subprocess tests."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sevn.config.workspace_config import WorkspaceConfig
from sevn.data.bundled_skills import BUNDLED_SKILLS_ROOT
from sevn.integrations.cursor_cloud.jobs import CursorCloudJob, insert_job
from sevn.skills.cursor_cloud import CURSOR_CLOUD_SKILL_ID, gate_cursor_cloud_core_skill
from sevn.skills.manager import SkillsManager
from sevn.storage.migrate import apply_migrations

_SKILL_ROOT = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "sevn"
    / "data"
    / "bundled_skills"
    / "core"
    / "cursor_cloud"
)
_SCRIPTS = _SKILL_ROOT / "scripts"


def _enabled_config() -> WorkspaceConfig:
    return WorkspaceConfig(
        schema_version=1,
        skills={"cursor_cloud": {"enabled": True, "default_repo_url": "https://github.com/o/r"}},
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )


@pytest.fixture(autouse=True)
def _reset_skills_manager() -> None:
    SkillsManager.reset_singletons_for_tests()
    yield
    SkillsManager.reset_singletons_for_tests()


@pytest.fixture
def cursor_workspace(tmp_path: Path) -> Path:
    """Migrated workspace with sevn.json enabling cursor_cloud."""
    dot_sevn = tmp_path / ".sevn"
    dot_sevn.mkdir(parents=True)
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workspace_root": ".",
                "skills": {
                    "cursor_cloud": {
                        "enabled": True,
                        "default_repo_url": "https://github.com/o/r",
                        "default_ref": "main",
                    },
                },
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            },
        ),
        encoding="utf-8",
    )
    conn = sqlite3.connect(str(dot_sevn / "sevn.db"))
    apply_migrations(conn)
    conn.close()
    return tmp_path


def _run_script(
    script_name: str,
    workspace: Path,
    cli_args: list[str] | None = None,
) -> tuple[int, dict[str, object]]:
    script = _SCRIPTS / script_name
    env = os.environ.copy()
    env["SEVN_WORKSPACE"] = str(workspace)
    proc = subprocess.run(
        [sys.executable, str(script), *(cli_args or [])],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    payload = json.loads(proc.stdout.strip() or "{}")
    return proc.returncode, payload


def test_bundled_skill_manifest_exists() -> None:
    assert (_SKILL_ROOT / "SKILL.md").is_file()


def test_gate_skips_when_disabled() -> None:
    assert gate_cursor_cloud_core_skill(None) == "skip"


def test_gate_loads_when_enabled() -> None:
    assert gate_cursor_cloud_core_skill(_enabled_config()) == "load"


def test_manager_omits_skill_when_disabled(tmp_path: Path) -> None:
    mgr = SkillsManager.shared(tmp_path, (BUNDLED_SKILLS_ROOT,))
    assert CURSOR_CLOUD_SKILL_ID not in mgr._records


def test_manager_includes_skill_when_enabled(tmp_path: Path) -> None:
    mgr = SkillsManager.shared(
        tmp_path,
        (BUNDLED_SKILLS_ROOT,),
        config=_enabled_config(),
    )
    assert CURSOR_CLOUD_SKILL_ID in mgr._records


def test_launch_script_disabled_returns_error(cursor_workspace: Path) -> None:
    """Launch fails fast when cursor_cloud skill is not enabled in sevn.json."""
    sevn_json = cursor_workspace / "sevn.json"
    sevn_json.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workspace_root": ".",
                "skills": {"cursor_cloud": {"enabled": False}},
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            }
        ),
        encoding="utf-8",
    )
    code, payload = _run_script("launch.py", cursor_workspace, ["--prompt", "task"])
    assert code == 1
    assert payload.get("ok") is False


def test_launch_and_status_in_process(cursor_workspace: Path) -> None:
    """Exercise launch/status modules in-process with patched API client."""
    import importlib.util
    import sys

    def fake_create(conn: sqlite3.Connection, workspace: Path, **kwargs: Any) -> CursorCloudJob:
        return insert_job(
            conn,
            cursor_agent_id="bc-mock",
            session_key=kwargs.get("session_key", ""),
            prompt=str(kwargs.get("prompt", "add test")),
            repo_url=str(kwargs.get("repo_url", "https://github.com/o/r")),
            starting_ref=str(kwargs.get("starting_ref", "main")),
            status="ACTIVE",
            agent_url="https://cursor.com/agents/bc-mock",
            latest_run_id="run-1",
        )

    def fake_refresh(conn: sqlite3.Connection, job: CursorCloudJob) -> CursorCloudJob:
        return replace(
            job,
            status="FINISHED",
            pr_url="https://github.com/o/r/pull/9",
            artifact_count=1,
        )

    os.environ["SEVN_WORKSPACE"] = str(cursor_workspace)
    try:
        with patch(
            "sevn.integrations.cursor_cloud.client.create_cloud_agent",
            side_effect=fake_create,
        ):
            launch_spec = importlib.util.spec_from_file_location(
                "cursor_launch",
                _SCRIPTS / "launch.py",
            )
            assert launch_spec is not None
            assert launch_spec.loader is not None
            launch_mod = importlib.util.module_from_spec(launch_spec)
            sys.argv = ["launch.py", "--prompt", "add regression test"]
            launch_spec.loader.exec_module(launch_mod)
            assert launch_mod.main() == 0

        conn = sqlite3.connect(str(cursor_workspace / ".sevn" / "sevn.db"))
        conn.row_factory = sqlite3.Row
        try:
            with patch(
                "sevn.integrations.cursor_cloud.client.refresh_job_status",
                side_effect=fake_refresh,
            ):
                status_spec = importlib.util.spec_from_file_location(
                    "cursor_status",
                    _SCRIPTS / "status.py",
                )
                assert status_spec is not None
                assert status_spec.loader is not None
                status_mod = importlib.util.module_from_spec(status_spec)
                row = conn.execute(
                    "SELECT job_id FROM cursor_cloud_jobs WHERE cursor_agent_id = ?",
                    ("bc-mock",),
                ).fetchone()
                assert row is not None
                sys.argv = ["status.py", "--job-id", str(row["job_id"])]
                status_spec.loader.exec_module(status_mod)
                assert status_mod.main() == 0
        finally:
            conn.close()
    finally:
        os.environ.pop("SEVN_WORKSPACE", None)
