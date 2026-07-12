"""Handoff spawn environment helpers."""

from __future__ import annotations

import tempfile
from pathlib import Path

from sevn.onboarding.spawn_env import handoff_child_env


def test_handoff_child_env_standard_layout() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        ws = home / "workspace"
        ws.mkdir()
        sj = ws / "sevn.json"
        sj.write_text(
            '{"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
            encoding="utf-8",
        )
        env = handoff_child_env(sevn_json_path=sj, service="gateway")
        assert env["SEVN_HOME"] == str(home.resolve())
        assert env["SEVN_SERVICE_LOG"] == "gateway"


def test_handoff_child_env_flat_workspace_dir() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        sj = ws / "sevn.json"
        sj.write_text(
            '{"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
            encoding="utf-8",
        )
        env = handoff_child_env(
            sevn_json_path=sj, service="proxy", extra={"SEVN_PROXY_URL": "http://127.0.0.1:8787"}
        )
        assert env["SEVN_HOME"] == str(ws.resolve())
        assert env["SEVN_PROXY_URL"] == "http://127.0.0.1:8787"
