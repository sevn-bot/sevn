"""sevn serve, probe, and doctor (D9, D13)."""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

_BIND_MESSAGE = "refusing to bind 0.0.0.0: pass --allow-remote-bind"


def _stdout(result: object) -> str:
    return str(getattr(result, "stdout", "") or "")


def _combined(result: object) -> str:
    stderr = getattr(result, "stderr", "") or ""
    return f"{_stdout(result)}\n{stderr}"


def _parse_json(text: str) -> Any:
    stripped = text.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return [json.loads(line) for line in stripped.splitlines() if line.strip()]


def _contains_seq(payload: Any, seq: int) -> bool:
    if isinstance(payload, list):
        return any(_contains_seq(item, seq) for item in payload)
    if isinstance(payload, dict):
        if payload.get("seq") == seq or payload.get("s") == seq:
            return True
        return any(_contains_seq(value, seq) for value in payload.values())
    return False


def _contains_ping(payload: Any) -> bool:
    if isinstance(payload, list):
        return any(_contains_ping(item) for item in payload)
    if isinstance(payload, dict):
        if payload.get("k") == "system.ping" or payload.get("type") == "system.ping":
            return True
        return any(_contains_ping(value) for value in payload.values())
    return False


@pytest.fixture
def running_host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    import uvicorn

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    monkeypatch.setenv("SEVN_HOME", str(tmp_path))
    monkeypatch.setenv("SEVN_SECRETS__BACKEND", "age-file")
    monkeypatch.delenv("SEVN_DEV", raising=False)
    (tmp_path / "config.toml").write_text(
        f'[secrets]\nbackend = "age-file"\n\n[http]\nhost = "127.0.0.1"\nport = {port}\n',
        encoding="utf-8",
    )
    from sevn.config import Settings
    from sevn.http import create_app

    app = create_app(Settings(home=tmp_path))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    health = f"http://127.0.0.1:{port}/health"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(health, timeout=0.2) as response:
                if response.status == 200:
                    break
        except (OSError, urllib.error.URLError):
            time.sleep(0.05)
    else:
        server.should_exit = True
        thread.join(timeout=2)
        raise AssertionError("host did not become healthy")
    try:
        yield tmp_path
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_serve_help_lists_options() -> None:
    from sevn.cli import app
    from typer.testing import CliRunner

    result = CliRunner().invoke(app, ["serve", "--help"])
    assert result.exit_code == 0
    for option in ("--home", "--host", "--port", "--open", "--allow-remote-bind"):
        assert option in result.stdout


def test_serve_refuses_remote_bind(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sevn.cli import app
    from typer.testing import CliRunner

    monkeypatch.setenv("SEVN_HOME", str(tmp_path))
    result = CliRunner().invoke(
        app,
        ["serve", "--host", "0.0.0.0", "--home", str(tmp_path)],  # noqa: S104
    )
    assert result.exit_code == 2
    assert _BIND_MESSAGE in _combined(result)


def test_probe_call_info(running_host: Path) -> None:
    from sevn.cli import app
    from typer.testing import CliRunner

    result = CliRunner().invoke(app, ["probe", "call", "system.info", "{}"])
    assert result.exit_code == 0, _combined(result)
    payload = json.loads(_stdout(result))
    assert str(payload["host_id"]).startswith("host_")
    assert running_host.is_dir()


def test_probe_call_ping_then_events(running_host: Path) -> None:
    from sevn.cli import app
    from typer.testing import CliRunner

    runner = CliRunner()
    ping = runner.invoke(
        app,
        ["probe", "call", "system.ping", json.dumps({"op_id": "probe-op-1", "note": "hi"})],
    )
    assert ping.exit_code == 0, _combined(ping)
    body = json.loads(_stdout(ping))
    seq = body["seq"]
    assert isinstance(seq, int)
    events = runner.invoke(app, ["probe", "events", "--since", str(seq - 1)])
    assert events.exit_code == 0, _combined(events)
    printed = _parse_json(_stdout(events))
    assert _contains_seq(printed, seq)
    assert _contains_ping(printed)
    assert running_host.is_dir()


def test_doctor_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import sevn
    from sevn.cli import app
    from typer.testing import CliRunner

    monkeypatch.setenv("SEVN_HOME", str(tmp_path))
    (tmp_path / "config.toml").write_text('[secrets]\nbackend = "age-file"\n', encoding="utf-8")
    result = CliRunner().invoke(app, ["doctor", "--json"])
    assert result.exit_code == 0, _combined(result)
    body = json.loads(_stdout(result))
    assert Path(str(body["home"])).resolve() == tmp_path.resolve()
    assert str(body["db"]).endswith("sevn.db")
    assert body["secrets_backend"] == "age-file"
    assert isinstance(body["web_dist"], str)
    assert body["version"] == sevn.__version__
