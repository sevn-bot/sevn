"""Doctor safe ``--fix`` whitelist tests (W3 — `specs/23-cli.md` §3)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from sevn.cli.app import app
from sevn.cli.doctor.checks import CheckResult, DoctorCheck
from sevn.cli.doctor.fix import FixContext, _fix_llmignore, _fix_operator_lock
from sevn.cli.doctor.sections import section_for, title_for
from sevn.cli.operator_lock import operator_lock_path


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_fix_operator_lock_clears_stale_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("SEVN_HOME", str(home))
    lock_path = operator_lock_path(home)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text("999999\n", encoding="utf-8")
    os.utime(lock_path, (time.time() - 7200, time.time() - 7200))
    (home / "workspace").mkdir()

    class _Bw:
        layout = type("L", (), {"content_root": home / "workspace"})()
        config = None

    outcome = _fix_operator_lock(FixContext(bw=_Bw(), yes=True, interactive=False))
    assert outcome is not None
    assert outcome.status == "fixed"
    assert not lock_path.exists()


def test_fix_llmignore_creates_layout(tmp_path: Path) -> None:
    ws = tmp_path / "workspace"
    ws.mkdir()

    class _Bw:
        layout = type("L", (), {"content_root": ws})()
        config = None

    outcome = _fix_llmignore(FixContext(bw=_Bw(), yes=True, interactive=False))
    assert outcome is not None
    assert outcome.status == "fixed"
    assert (ws / ".llmignore" / "blocked").is_dir()


def test_doctor_fix_yes_non_interactive_json_shape(
    runner: CliRunner,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    ws = home / "workspace"
    ws.mkdir(parents=True)
    (ws / "sevn.json").write_text('{"schema_version":1}', encoding="utf-8")
    monkeypatch.setenv("SEVN_HOME", str(home))

    def _fake_probes(_bw: object, result: CheckResult, *, options: object) -> None:
        _ = _bw, options
        result.add(
            DoctorCheck(
                "llmignore",
                section_for("llmignore"),
                title_for("llmignore"),
                False,
                severity="warn",
                detail="missing",
            ),
        )

    import sevn.cli.commands.doctor as doctor_cmd

    monkeypatch.setattr(doctor_cmd, "run_doctor_probes", _fake_probes)
    monkeypatch.setattr(
        doctor_cmd,
        "load_doctor_workspace",
        lambda: type("BW", (), {"layout": type("L", (), {"content_root": ws})(), "config": None})(),
    )

    payload = json.loads(runner.invoke(app, ["doctor", "--fix", "--yes", "--json"]).stdout)
    data = payload["data"] if payload["ok"] else payload["details"]
    assert "fixed" in data
    assert "manual" in data
