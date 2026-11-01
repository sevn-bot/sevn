"""Decision evals stay off unless evals_on is set."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import pytest
from fakes.fake_jev import FakeJev
from support.botcore import arm_configured, secrets_toml
from support.repo import repo_root

_REPORT_DAY = "2026-10-18"
_INTENTS = ("new_request", "follow_up", "steer", "answer", "chit_chat")
_FORBIDDEN = (
    re.compile(r"/Users/[^/\s]+"),
    re.compile(r"/home/[^/\s]+"),
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    re.compile(r"sk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"Bearer [A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
)


def _report_path() -> Path:
    return repo_root() / ".ignorelocal" / "evals" / f"{_REPORT_DAY}.json"


def _clear_report() -> None:
    path = _report_path()
    if path.is_file():
        path.unlink()


def test_evals_off_by_default_runs_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sevn.cli import app
    from typer.testing import CliRunner

    arm_configured(monkeypatch, tmp_path)
    _clear_report()
    result = CliRunner().invoke(app, ["evals", "run", "decisions"])
    assert result.exit_code == 0, result.output
    assert "evals disabled" in result.stdout
    assert not _report_path().exists()


def test_evals_on_writes_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from freezegun import freeze_time
    from sevn.cli import app
    from sevn.decisions.jev import use_client
    from typer.testing import CliRunner

    arm_configured(
        monkeypatch,
        tmp_path,
        secrets_toml("[decisions]\nevals_on = true\n"),
    )
    _clear_report()
    use_client(
        FakeJev(
            answers={
                "message.intent": ("new_request", 0.9),
                "message.target_agent": ("none", 0.9),
            }
        )
    )
    try:
        with freeze_time(f"{_REPORT_DAY}T12:00:00+00:00"):
            result = CliRunner().invoke(app, ["evals", "run", "decisions"])
        assert result.exit_code == 0, result.output
        body = json.loads(_report_path().read_text(encoding="utf-8"))
    finally:
        use_client(None)
        _clear_report()
    accuracy = body["accuracy"]
    assert isinstance(accuracy, dict)
    assert "message.intent" in accuracy
    assert "message.target_agent" in accuracy
    for value in accuracy.values():
        assert isinstance(value, int | float)
        assert 0 <= float(value) <= 1


def test_datasets_are_synthetic() -> None:
    folder = repo_root() / "host" / "evals" / "decisions"
    files = sorted(folder.glob("*.jsonl"))
    assert files
    counts: Counter[str] = Counter()
    for path in files:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip() == "":
                continue
            for pattern in _FORBIDDEN:
                assert pattern.search(line) is None, path.name
            record = json.loads(line)
            assert isinstance(record, dict)
            intent = record["intent"]
            assert isinstance(intent, str)
            counts[intent] += 1
    for intent in _INTENTS:
        assert counts[intent] >= 20
