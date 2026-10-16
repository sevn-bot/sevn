"""sevn serve, probe, and doctor (D9, D13)."""

from __future__ import annotations

import contextlib
import json
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from support.repo import repo_root

_BIND_MESSAGE = "refusing to bind 0.0.0.0: pass --allow-remote-bind"
_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_SERVE_OPTIONS = ("--home", "--host", "--port", "--open", "--allow-remote-bind")


def _visible(text: str) -> str:
    """Help text with ANSI styles removed.

    Rich's option highlighter styles each hyphen, so a colored render stores
    ``--home`` as ``-`` + SGR + ``-home``. The visible glyphs are unchanged.
    """
    return _ANSI.sub("", text)


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


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _child_env(home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["SEVN_HOME"] = str(home)
    env["PYTHONUNBUFFERED"] = "1"
    return env


@contextlib.contextmanager
def _running_cli_serve(
    home: Path, port: int, env: dict[str, str]
) -> Iterator[subprocess.Popen[str]]:
    log_path = home / "serve-test.log"
    log_file = log_path.open("w", encoding="utf-8")
    proc = subprocess.Popen(  # noqa: S603
        [
            sys.executable,
            "-m",
            "sevn",
            "serve",
            "--home",
            str(home),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=repo_root(),
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        text=True,
    )
    try:
        yield proc
    finally:
        if proc.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=5)
        log_file.close()


def _wait_health(port: int, proc: subprocess.Popen[str], home: Path) -> dict[str, Any]:
    url = f"http://127.0.0.1:{port}/health"
    log_path = home / "serve-test.log"
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            log = log_path.read_text(encoding="utf-8") if log_path.is_file() else ""
            raise AssertionError(f"sevn serve exited {proc.returncode} before /health\n{log}")
        try:
            with urllib.request.urlopen(url, timeout=0.2) as response:
                if response.status == 200:
                    body: object = json.loads(response.read().decode())
                    if isinstance(body, dict):
                        return body
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            time.sleep(0.05)
    log = log_path.read_text(encoding="utf-8") if log_path.is_file() else ""
    raise AssertionError(f"sevn serve did not become healthy on {url}\n{log}")


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
    visible = _visible(result.stdout)
    for option in _SERVE_OPTIONS:
        assert option in visible, f"{option} missing from help:\n{visible}"


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


def _distinct_port(taken: int) -> int:
    port = _free_port()
    while port == taken:
        port = _free_port()
    return port


def test_probe_reaches_serve_port_not_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Probe follows the address `sevn serve --port` bound, not config `[http].port`."""
    config_port = _free_port()
    serve_port = _distinct_port(config_port)
    (tmp_path / "config.toml").write_text(
        f'[secrets]\nbackend = "age-file"\n\n[http]\nhost = "127.0.0.1"\nport = {config_port}\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("SEVN_HOME", str(tmp_path))
    monkeypatch.setenv("SEVN_SECRETS__BACKEND", "age-file")
    monkeypatch.delenv("SEVN_HTTP__PORT", raising=False)
    monkeypatch.delenv("SEVN_HTTP__HOST", raising=False)
    from sevn.config import Settings

    assert Settings.load().http.port == config_port
    assert Settings.load().http.port != serve_port
    env = _child_env(tmp_path)
    env["SEVN_SECRETS__BACKEND"] = "age-file"
    env.pop("SEVN_HTTP__PORT", None)
    env.pop("SEVN_HTTP__HOST", None)
    with _running_cli_serve(tmp_path, serve_port, env) as proc:
        health = _wait_health(serve_port, proc, tmp_path)
        from sevn.cli import app
        from typer.testing import CliRunner

        result = CliRunner().invoke(
            app,
            ["probe", "call", "--home", str(tmp_path), "system.info", "{}"],
        )
        assert result.exit_code == 0, _combined(result)
        payload = json.loads(_stdout(result))
        assert payload["host_id"] == health["host_id"]
        assert str(payload["host_id"]).startswith("host_")


def test_serve_starts_with_env_secret_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`secrets.backend = "env"` must boot without writing host/identity."""
    port = _free_port()
    (tmp_path / "config.toml").write_text(
        f'[secrets]\nbackend = "env"\n\n[http]\nhost = "127.0.0.1"\nport = {port}\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("SEVN_HOME", str(tmp_path))
    monkeypatch.delenv("SEVN_SECRETS__BACKEND", raising=False)
    monkeypatch.delenv("SEVN_HTTP__PORT", raising=False)
    monkeypatch.delenv("SEVN_HTTP__HOST", raising=False)
    for key in list(os.environ):
        if key.startswith("SEVN_SECRET_"):
            monkeypatch.delenv(key, raising=False)
    env = _child_env(tmp_path)
    env.pop("SEVN_SECRETS__BACKEND", None)
    for key in [name for name in env if name.startswith("SEVN_SECRET_")]:
        del env[key]
    from sevn.config import Settings
    from sevn.paths import Paths
    from sevn.secrets.backends import EnvBackend, open_backend

    assert isinstance(open_backend(Settings.load(), Paths.from_env()), EnvBackend)
    with _running_cli_serve(tmp_path, port, env) as proc:
        health = _wait_health(port, proc, tmp_path)
        assert health["status"] == "ok"
        assert str(health["host_id"]).startswith("host_")
        assert proc.poll() is None
