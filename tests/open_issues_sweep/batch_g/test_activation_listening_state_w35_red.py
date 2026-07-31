"""W35.5 — listening state observable (#102 → W38, D24)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.gateway.test_config_menu_actions import _build_router
from tests.open_issues_sweep.batch_g.conftest import (
    activation_enabled_workspace_doc,
    import_voice_activation_module,
)
from typer.testing import CliRunner

from sevn.cli.app import app
from sevn.gateway.channel_router import IncomingMessage


@pytest.mark.xfail(reason="green after W38: sevn voice activation status CLI", strict=False)
def test_cli_activation_status_reports_listening_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import_voice_activation_module()
    home = tmp_path / "home"
    ws_dir = home / "workspace"
    ws_dir.mkdir(parents=True)
    (ws_dir / "sevn.json").write_text(
        json.dumps(activation_enabled_workspace_doc(enabled=True)),
        encoding="utf-8",
    )
    (ws_dir / ".llmignore").mkdir()
    monkeypatch.setenv("SEVN_HOME", str(home))
    monkeypatch.setenv("SEVN_GATEWAY_TOKEN", "batch-g-gw-token")

    runner = CliRunner()
    result = runner.invoke(app, ["voice", "activation", "status", "--json"], env={"NO_COLOR": "1"})
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    assert data.get("listening_state") in {
        "disabled",
        "enabled_listening",
        "enabled_unavailable",
    }


@pytest.mark.xfail(reason="green after W38: enable/disable flips listening state", strict=False)
def test_cli_activation_enable_disable_flips_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import_voice_activation_module()
    home = tmp_path / "home"
    ws_dir = home / "workspace"
    ws_dir.mkdir(parents=True)
    (ws_dir / "sevn.json").write_text(
        json.dumps(activation_enabled_workspace_doc(enabled=False)),
        encoding="utf-8",
    )
    (ws_dir / ".llmignore").mkdir()
    monkeypatch.setenv("SEVN_HOME", str(home))
    monkeypatch.setenv("SEVN_GATEWAY_TOKEN", "batch-g-gw-token")
    runner = CliRunner()

    off = runner.invoke(app, ["voice", "activation", "status", "--json"], env={"NO_COLOR": "1"})
    assert off.exit_code == 0
    off_state = json.loads(off.stdout).get("data", {}).get("listening_state")
    assert off_state == "disabled"

    enable = runner.invoke(app, ["voice", "activation", "enable"], env={"NO_COLOR": "1"})
    assert enable.exit_code == 0
    on = runner.invoke(app, ["voice", "activation", "status", "--json"], env={"NO_COLOR": "1"})
    on_state = json.loads(on.stdout).get("data", {}).get("listening_state")
    assert on_state in {"enabled_listening", "enabled_unavailable"}

    disable = runner.invoke(app, ["voice", "activation", "disable"], env={"NO_COLOR": "1"})
    assert disable.exit_code == 0
    back = runner.invoke(app, ["voice", "activation", "status", "--json"], env={"NO_COLOR": "1"})
    assert json.loads(back.stdout).get("data", {}).get("listening_state") == "disabled"


@pytest.mark.asyncio
@pytest.mark.xfail(reason="green after W38: Telegram activation status action", strict=False)
async def test_telegram_activation_status_action_reports_listening_state(tmp_path: Path) -> None:
    import_voice_activation_module()
    router, cap, _ws = _build_router(tmp_path)
    msg = IncomingMessage(
        channel="telegram",
        chat_id="1",
        user_id="1",
        text="",
        metadata={"callback_query_id": "cq-activation-status"},
    )
    handler = getattr(router, "_menu_actions", None)
    assert handler is not None
    handle = getattr(handler, "_handle_voice_activation_status", None)
    assert handle is not None, "act:voice:activation:status handler missing"
    await handle(msg, "act:voice:activation:status")
    joined = "\n".join(str(t) for _cq, t in cap.answered)
    assert any(token in joined.lower() for token in ("listening", "unavailable", "disabled"))
