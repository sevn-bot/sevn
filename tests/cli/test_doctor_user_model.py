"""``sevn doctor --user-model`` (`specs/32-memory-honcho.md` §7)."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from sevn.cli.app import app


def test_doctor_user_model_json(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "sevnhome"
    ws = home / "workspace"
    ws.mkdir(parents=True)
    (ws / ".sevn").mkdir()
    (ws / "sevn.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "memory": {"user_model": {"enabled": False}},
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("SEVN_HOME", str(home))
    runner = CliRunner()
    result = runner.invoke(app, ["doctor", "--user-model", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["data"]["prompt_rev"] == 1
