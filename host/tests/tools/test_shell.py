"""Seatbelt, bubblewrap, and per-bot network."""

from __future__ import annotations

import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from support.botcore import arm_configured, upgrade_home

_HOSTS_MARKER = "seatbelt-marker"


async def _pair(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[object, object]:
    from sevn.domain.agents import AgentService
    from sevn.domain.bots import BotService

    arm_configured(monkeypatch, tmp_path)
    await upgrade_home(tmp_path)
    bot = await BotService().create("Nimbus")
    agent = await AgentService().spawn(bot.id)
    return bot, agent


def _note(workspace: object) -> str | None:
    matches = list(Path(str(workspace)).rglob("note.txt"))
    if not matches:
        return None
    return matches[0].read_text(encoding="utf-8")


def _network(home: Path, bot_id: str, value: str) -> None:
    import sqlite3

    with sqlite3.connect(home / "sevn.db") as connection:
        connection.execute("UPDATE bots SET network = ? WHERE id = ?", (value, bot_id))
        connection.commit()


class _MarkerHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = b"network-marker"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


@pytest.mark.skipif(sys.platform != "darwin", reason="Seatbelt is macOS-only")
async def test_shell_seatbelt_denies_home_ssh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.tools.shell import execute

    home = tmp_path / "home"
    (home / ".ssh").mkdir(parents=True)
    (home / ".ssh" / "known_hosts").write_text(_HOSTS_MARKER + "\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    bot, agent = await _pair(tmp_path, monkeypatch)
    wrote = await execute(bot.id, agent.id, "printf hi > note.txt")
    assert wrote.executed is True
    assert wrote.returncode == 0
    assert _note(bot.workspace_path) == "hi"
    shown = await execute(bot.id, agent.id, 'printf %s "$HOME"')
    assert shown.stdout.strip() == str(home)
    denied = await execute(bot.id, agent.id, 'cat "$HOME/.ssh/known_hosts"')
    assert denied.executed is True
    assert denied.returncode != 0
    assert _HOSTS_MARKER not in denied.stdout
    assert _HOSTS_MARKER not in denied.stderr


@pytest.mark.skipif(sys.platform != "linux", reason="bubblewrap is Linux-only")
async def test_shell_bwrap_denies_outside_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.tools.shell import execute

    bot, agent = await _pair(tmp_path, monkeypatch)
    outside = tmp_path / "outside" / "nope.txt"
    outside.parent.mkdir()
    wrote = await execute(bot.id, agent.id, "printf hi > note.txt")
    assert wrote.executed is True
    assert wrote.returncode == 0
    assert _note(bot.workspace_path) == "hi"
    denied = await execute(bot.id, agent.id, f"printf x > {outside}")
    assert denied.executed is True
    assert denied.returncode != 0
    assert not outside.exists()


@pytest.mark.skipif(
    sys.platform not in {"darwin", "linux"},
    reason="sandbox home masking is macOS or Linux",
)
async def test_shell_denies_sevn_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sevn.tools.shell import execute

    bot, agent = await _pair(tmp_path, monkeypatch)
    keys = tmp_path / "keys"
    keys.mkdir(exist_ok=True)
    (keys / "marker").write_text(_HOSTS_MARKER + "\n", encoding="utf-8")
    run = tmp_path / "run"
    run.mkdir(exist_ok=True)
    (run / "marker").write_text(_HOSTS_MARKER + "\n", encoding="utf-8")
    for path in (keys / "marker", run / "marker"):
        shown = await execute(bot.id, agent.id, f'cat "{path}"')
        assert shown.executed is True
        assert _HOSTS_MARKER not in shown.stdout
        assert _HOSTS_MARKER not in shown.stderr


@pytest.mark.skipif(
    sys.platform not in {"darwin", "linux"},
    reason="sandbox network is macOS or Linux",
)
async def test_network_off_blocks_curl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sevn.tools.shell import execute

    bot, agent = await _pair(tmp_path, monkeypatch)
    _network(tmp_path, str(bot.id), "off")
    server = ThreadingHTTPServer(("127.0.0.1", 0), _MarkerHandler)
    port = int(server.server_address[1])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        wrote = await execute(bot.id, agent.id, "printf hi > note.txt")
        assert wrote.returncode == 0
        probed = await execute(
            bot.id,
            agent.id,
            f"curl --max-time 2 --fail-with-body http://127.0.0.1:{port}/",
        )
        assert probed.executed is True
        assert probed.returncode != 0
        assert "network-marker" not in probed.stdout
    finally:
        server.shutdown()
        thread.join(timeout=2)


async def test_shell_is_deferred(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import sevn.tools.shell
    from sevn.tools.registry import toolsets_for

    bot, _agent = await _pair(tmp_path, monkeypatch)
    assert sevn.tools.shell.__name__ == "sevn.tools.shell"
    eager: set[str] = set()
    deferred: set[str] = set()
    for item in toolsets_for(bot):
        eager.update(item.eager)
        deferred.update(item.deferred)
    assert "shell" in deferred
    assert "shell" not in eager
