"""``sevn migrate`` bound-workspace paths (`specs/22-onboarding.md` §2.3, §9)."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner as ClickCliRunner
from typer.main import get_command

from sevn.cli.app import app

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "onboarding" / "migrate"
_V1_SEVN_JSON = _FIXTURES / "v1_workspace" / "sevn.json"


@pytest.fixture
def runner() -> ClickCliRunner:
    return ClickCliRunner()


def _install_bound_workspace(tmp_path: Path, *, src: Path) -> Path:
    home = tmp_path / "home"
    ws = home / "workspace"
    ws.mkdir(parents=True)
    shutil.copy(src, ws / "sevn.json")
    return home


def test_migrate_dry_run_leaves_sevn_json_unchanged(
    runner: ClickCliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = _install_bound_workspace(tmp_path, src=_V1_SEVN_JSON)
    monkeypatch.setenv("SEVN_HOME", str(home))
    before = (home / "workspace" / "sevn.json").read_text(encoding="utf-8")
    result = runner.invoke(get_command(app), ["migrate", "--dry-run"])
    assert result.exit_code == 0
    assert (home / "workspace" / "sevn.json").read_text(encoding="utf-8") == before
    assert "dry-run only" in result.stdout


def _last_json_object(text: str) -> dict[str, object]:
    """Parse the last top-level JSON object (CLI may print a diff before summary JSON)."""
    decoder = json.JSONDecoder()
    last: dict[str, object] | None = None
    for match in re.finditer(r"\{", text):
        try:
            obj, _end = decoder.raw_decode(text, match.start())
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            last = obj
    if last is None:
        msg = "no JSON object found in output"
        raise ValueError(msg)
    return last


def test_migrate_yes_writes_v2_and_backup(
    runner: ClickCliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = _install_bound_workspace(tmp_path, src=_V1_SEVN_JSON)
    monkeypatch.setenv("SEVN_HOME", str(home))
    result = runner.invoke(get_command(app), ["migrate", "--yes"])
    assert result.exit_code == 0
    summary = _last_json_object(result.stdout)
    assert summary["changed"] is True
    assert summary["backup"] is not None
    ws = home / "workspace"
    upgraded = json.loads((ws / "sevn.json").read_text(encoding="utf-8"))
    assert upgraded["schema_version"] == 2
    backup = Path(summary["backup"])
    assert backup.is_file()
    assert backup.name.startswith("sevn.json.v1")


def test_migrate_missing_sevn_json_exit4(
    runner: ClickCliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    (home / "workspace").mkdir(parents=True)
    monkeypatch.setenv("SEVN_HOME", str(home))
    result = runner.invoke(get_command(app), ["migrate"])
    assert result.exit_code == 4
