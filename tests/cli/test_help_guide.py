"""Tests for CLI help panels and ``sevn guide`` (`plan/cli-comprehensive-parity-doctor` W7)."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from sevn.cli.app import app
from sevn.cli.commands.guide_cmd import register as register_guide
from sevn.cli.help.guide import GUIDE_TOPICS, list_guide_topics, load_guide
from sevn.cli.help.panels import (
    PANEL_ORDER,
    ROOT_COMMAND_PANELS,
    apply_root_panels,
    iter_root_click_commands,
    panel_for,
)


def test_panel_order_matches_mission_control_groups() -> None:
    assert len(PANEL_ORDER) == 8
    assert PANEL_ORDER[0] == "Core"
    assert "Surfaces" in PANEL_ORDER


def test_root_command_panel_map_covers_guide() -> None:
    assert ROOT_COMMAND_PANELS["guide"] == "Ops"
    assert panel_for("doctor") == "Core"


def test_apply_root_panels_assigns_click_metadata() -> None:
    import typer

    mini = typer.Typer()
    register_guide(mini)

    @mini.command("doctor")
    def _doctor() -> None:
        """Probe."""

    apply_root_panels(mini)
    panels = dict(iter_root_click_commands(mini))
    assert panels["doctor"] == "Core"
    assert panels["guide"] == "Ops"


def test_list_guide_topics_includes_getting_started() -> None:
    topics = list_guide_topics()
    assert "getting-started" in topics
    for topic in GUIDE_TOPICS:
        assert topic in topics


def test_load_guide_getting_started_has_title() -> None:
    body = load_guide("getting-started")
    assert body.startswith("# Getting started")


def test_sevn_guide_lists_topics_plain() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["guide"], env={"NO_COLOR": "1"})
    assert result.exit_code == 0
    assert "getting-started" in result.stdout
    assert "doctor" in result.stdout


def test_sevn_guide_topic_renders_plain() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["guide", "doctor"], env={"NO_COLOR": "1"})
    assert result.exit_code == 0
    assert "sevn doctor" in result.stdout


def test_sevn_guide_json_list() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["guide", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert "topics" in payload
    assert "getting-started" in payload["topics"]


def test_sevn_guide_unknown_topic_exit_2() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["guide", "not-a-real-topic"])
    assert result.exit_code == 2


def test_sevn_help_groups_by_panel_on_tty() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for panel in ("Core", "Observability", "Ops"):
        assert panel in result.stdout


def test_cli_help_docs_check_script_main() -> None:
    from scripts.check_cli_help_docs import main

    assert main() == 0
