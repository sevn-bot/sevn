"""``sevn subagents`` CLI tests (W7.4)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.main import get_command

from sevn.agent.subagents.registry import SubAgentRegistry
from sevn.agent.subagents.supervisor import SubAgentSpec, SubAgentSupervisor
from sevn.cli.app import app
from sevn.config.sections.subagents import SubAgentsWorkspaceConfig
from sevn.storage.migrate import apply_migrations


@pytest.fixture
def runner():
    from click.testing import CliRunner

    return CliRunner()


@pytest.fixture
def bound_home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    ws = home / "workspace"
    ws.mkdir(parents=True)
    (ws / "sevn.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workspace_root": ".",
                "gateway": {"token": "literal-gateway-token-at-least-32-chars-long"},
                "subagents": {
                    "enabled": True,
                    "agents": {"tier_b": {"max_level1": 2, "max_level2": 1}},
                },
            },
        ),
        encoding="utf-8",
    )
    (ws / ".sevn").mkdir()
    conn = __import__("sqlite3").connect(str(ws / ".sevn" / "sevn.db"))
    apply_migrations(conn)
    conn.close()
    return home


def test_subagents_list_running_via_mission_api(runner, bound_home: Path, monkeypatch) -> None:
    monkeypatch.setenv("SEVN_HOME", str(bound_home))
    payload = {
        "running": [
            {
                "id": "a1",
                "level": 1,
                "role": "tier_b",
                "status": "running",
                "age_s": 1.2,
                "task_summary": "demo",
            },
        ],
        "counts": {"level1_total": 1, "level2_total": 0},
        "limits": {},
    }
    with patch("sevn.cli.dashboard_api_client.dashboard_api_get", return_value=payload):
        result = runner.invoke(
            get_command(app),
            ["subagents", "list"],
            env={"SEVN_HOME": str(bound_home)},
        )
    assert result.exit_code == 0
    assert "a1" in result.output


def test_subagents_limits_show_resolves_precedence(runner, bound_home: Path, monkeypatch) -> None:
    monkeypatch.setenv("SEVN_HOME", str(bound_home))
    result = runner.invoke(
        get_command(app),
        ["subagents", "limits"],
        env={"SEVN_HOME": str(bound_home)},
    )
    assert result.exit_code == 0
    assert "tier_b: L1=2 L2=1" in result.output


def test_subagents_limits_write_role_caps(runner, bound_home: Path, monkeypatch) -> None:
    monkeypatch.setenv("SEVN_HOME", str(bound_home))
    result = runner.invoke(
        get_command(app),
        ["subagents", "limits", "--role", "tier_c", "--max-l1", "3", "--max-l2", "2"],
        env={"SEVN_HOME": str(bound_home)},
    )
    assert result.exit_code == 0
    doc = json.loads((bound_home / "workspace" / "sevn.json").read_text(encoding="utf-8"))
    assert doc["subagents"]["agents"]["tier_c"]["max_level1"] == 3
    assert doc["subagents"]["agents"]["tier_c"]["max_level2"] == 2


def test_config_subagents_command(runner, bound_home: Path, monkeypatch) -> None:
    monkeypatch.setenv("SEVN_HOME", str(bound_home))
    result = runner.invoke(
        get_command(app),
        ["config", "subagents"],
        env={"SEVN_HOME": str(bound_home)},
    )
    assert result.exit_code == 0
    assert "Sub-agents" in result.output
    assert "orphaned_runs" in result.output


def test_subagents_kill_uses_post_transport(runner, bound_home: Path, monkeypatch) -> None:
    monkeypatch.setenv("SEVN_HOME", str(bound_home))
    with patch(
        "sevn.cli.dashboard_api_client.dashboard_api_post",
        return_value={"id": "a1", "killed": True, "status": "killed"},
    ):
        result = runner.invoke(
            get_command(app),
            ["subagents", "kill", "a1"],
            env={"SEVN_HOME": str(bound_home)},
        )
    assert result.exit_code == 0
    assert "Killed" in result.output or "a1" in result.output


def test_supervisor_fake_kill_round_trip() -> None:
    import asyncio

    supervisor = SubAgentSupervisor(registry=SubAgentRegistry(), config=SubAgentsWorkspaceConfig())

    async def _work() -> None:
        await asyncio.sleep(60)

    async def _demo() -> bool:
        handle = await supervisor.spawn(
            SubAgentSpec(
                level=1,
                role="tier_b",
                body=_work,
                session_id="s",
                channel="telegram",
                task_summary="cli fake",
            ),
        )
        killed = await supervisor.kill(handle.id, cascade=True)
        row = await supervisor.registry.get(handle.id)
        return killed and row is not None and row.status.value == "killed"

    assert asyncio.run(_demo())
