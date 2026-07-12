"""Golden JSON contracts for CLI machine output (`specs/23-cli.md` §10.4)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner as ClickCliRunner
from typer.main import get_command

from sevn.cli.app import app
from sevn.cli.json_util import CLI_JSON_SCHEMA_VERSION

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "tests" / "fixtures" / "cli"


def _load_fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def runner() -> ClickCliRunner:
    return ClickCliRunner()


def test_doctor_success_envelope_fixture_shape() -> None:
    """Regression anchor: ``sevn doctor --json`` success envelope keys stay stable."""

    obj = _load_fixture("doctor_success_envelope.json")
    assert obj["ok"] is True
    assert obj["command"] == "sevn doctor"
    assert obj["schema_version"] == CLI_JSON_SCHEMA_VERSION
    data = obj["data"]
    assert isinstance(data["checks"], list)
    assert isinstance(data["warnings"], list)
    ids = {c["id"] for c in data["checks"]}
    assert "sevn_json" in ids
    assert "gateway_ready" in ids


def test_doctor_w0_golden_check_ids_fixture() -> None:
    """W0 baseline: canonical doctor check IDs and envelope keys for W2 back-compat."""

    golden = _load_fixture("doctor_w0_golden_check_ids.json")
    assert golden["command"] == "sevn doctor"
    assert golden["schema_version"] == CLI_JSON_SCHEMA_VERSION
    required = golden["required_check_ids"]
    assert isinstance(required, list)
    assert len(required) == len(set(required))
    assert "gateway_token_configured" in required
    assert "voice_backends" in required
    conditional = golden["conditional_check_ids"]
    assert isinstance(conditional, list)
    assert {row["id"] for row in conditional} >= {"llm_reachability", "extensions"}


@pytest.mark.parametrize(
    ("argv", "fixture_name"),
    [
        (["gui", "migrate", "--json"], "gui_migrate_failure_envelope.json"),
    ],
)
def test_json_failure_envelope_matches_fixture(
    runner: ClickCliRunner,
    argv: list[str],
    fixture_name: str,
) -> None:
    """``--json`` failure envelopes stay stable for dispatch stubs."""
    expected = _load_fixture(fixture_name)
    result = runner.invoke(get_command(app), argv)
    assert result.exit_code == int(expected["exit_code"])
    payload = json.loads(result.stdout.strip())
    assert payload["ok"] is expected["ok"]
    assert payload["command"] == expected["command"]
    assert payload["error_code"] == expected["error_code"]
    assert payload["exit_code"] == expected["exit_code"]
    assert expected["message"] in payload["message"]


def test_migrate_missing_workspace_exit4(runner: ClickCliRunner, tmp_path: Path) -> None:
    """``sevn migrate`` without bound ``sevn.json`` exits ``4``."""
    home = tmp_path / "home"
    (home / "workspace").mkdir(parents=True)
    result = runner.invoke(
        get_command(app),
        ["migrate"],
        env={"SEVN_HOME": str(home)},
    )
    assert result.exit_code == 4
