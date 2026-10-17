"""Crash recovery through ``sevn serve`` (WV F4).

``test_restart_requeues_started_jobs`` calls ``recover`` and then ``kick`` itself.
This test starts ``sevn serve`` and never sends another message, so deleting the
lifespan kick leaves the echo reply missing.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest
from support.chat import (
    connected,
    fetch_all,
    insert_job,
    insert_turn,
    load_modules,
    mint_id,
    ok,
    request,
)
from support.repo import repo_root

_CRASH_TEXT = "crash-resume-7k2"
_ECHO = f"echo: {_CRASH_TEXT}"


async def _plant_crashed_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[str, str, str]:
    from sevn.domain.agents import AgentService

    load_modules("sevn.api.bots")
    async with connected(tmp_path, monkeypatch) as (host, client):
        monkeypatch.setenv("SEVN_DEV", "1")
        monkeypatch.setenv("SEVN_TEST_MODEL", "echo")
        frame, _earlier = await request(
            client,
            "bots.create",
            {"name": "Nimbus", "model": "echo", "op_id": mint_id("op_")},
        )
        bot = ok(frame)
        assert bot["model"] == "echo"
        bot_id = str(bot["id"])
        agent = await AgentService().spawn(bot_id=bot_id)
        job_id = await insert_job(
            tmp_path,
            bot_id=bot_id,
            agent_id=agent.id,
            text=_CRASH_TEXT,
            status="started",
        )
        turn_id = await insert_turn(
            tmp_path,
            agent_id=agent.id,
            thread_id=agent.thread_id,
            job_id=job_id,
            status="running",
            model_messages=None,
        )
        await AgentService().set_status(agent.id, "running")
    await host.outbox.aclose()
    await host.hub.oplog.aclose()
    return bot_id, turn_id, job_id


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _child_env(home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["SEVN_HOME"] = str(home)
    env["SEVN_WORKSPACES"] = str(home / "workspaces")
    env["SEVN_SECRETS__BACKEND"] = "age-file"
    env["SEVN_DEV"] = "1"
    env["SEVN_TEST_MODEL"] = "echo"
    env["PYTHONUNBUFFERED"] = "1"
    return env


@contextlib.contextmanager
def _running_serve(home: Path, port: int, env: dict[str, str]) -> Iterator[subprocess.Popen[str]]:
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


def _wait_health(port: int, proc: subprocess.Popen[str], home: Path) -> None:
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
                    return
        except (OSError, urllib.error.URLError):
            time.sleep(0.05)
    log = log_path.read_text(encoding="utf-8") if log_path.is_file() else ""
    raise AssertionError(f"sevn serve did not become healthy on {url}\n{log}")


def _probe_messages(home: Path, env: dict[str, str], bot_id: str) -> dict[str, object]:
    completed = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-m",
            "sevn",
            "probe",
            "call",
            "messages.list",
            json.dumps({"bot_id": bot_id}),
            "--home",
            str(home),
        ],
        cwd=repo_root(),
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr or completed.stdout)
    loaded: object = json.loads(completed.stdout)
    assert isinstance(loaded, dict)
    body: dict[str, object] = {}
    for key, value in loaded.items():
        if isinstance(key, str):
            body[key] = value
    return body


def _assistant_texts(body: dict[str, object]) -> list[str]:
    messages = body.get("messages")
    assert isinstance(messages, list)
    found: list[str] = []
    for message in messages:
        assert isinstance(message, dict)
        if message.get("role") != "assistant":
            continue
        parts = message.get("parts")
        assert isinstance(parts, list)
        for part in parts:
            assert isinstance(part, dict)
            text = part.get("text")
            if isinstance(text, str):
                found.append(text)
    return found


def test_serve_fails_crashed_turn_and_echoes_without_resend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A crashed running turn fails on sevn serve and its job echoes with no messages.send."""
    bot_id, turn_id, job_id = asyncio.run(_plant_crashed_turn(tmp_path, monkeypatch))
    planted = fetch_all(tmp_path, "SELECT status FROM jobs WHERE id = ?", (job_id,))
    assert planted[0]["status"] == "started"
    running = fetch_all(tmp_path, "SELECT status FROM turns WHERE id = ?", (turn_id,))
    assert running[0]["status"] == "running"

    env = _child_env(tmp_path)
    port = _free_port()
    with _running_serve(tmp_path, port, env) as proc:
        _wait_health(port, proc, tmp_path)
        failed = fetch_all(tmp_path, "SELECT status FROM turns WHERE id = ?", (turn_id,))
        assert failed[0]["status"] == "failed"
        deadline = time.monotonic() + 10
        texts: list[str] = []
        last_error = ""
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                log_path = tmp_path / "serve-test.log"
                log = log_path.read_text(encoding="utf-8") if log_path.is_file() else ""
                raise AssertionError(f"sevn serve exited {proc.returncode}\n{log}")
            try:
                texts = _assistant_texts(_probe_messages(tmp_path, env, bot_id))
            except (AssertionError, json.JSONDecodeError, OSError) as exc:
                last_error = str(exc)
                time.sleep(0.05)
                continue
            if _ECHO in texts:
                break
            time.sleep(0.05)
        else:
            job = fetch_all(tmp_path, "SELECT status FROM jobs WHERE id = ?", (job_id,))
            raise AssertionError(
                f"messages.list never showed {_ECHO}; job {list(map(dict, job))}; {last_error}"
            )
        assert _ECHO in texts
        done = fetch_all(tmp_path, "SELECT status FROM jobs WHERE id = ?", (job_id,))
        assert done[0]["status"] == "done"
        sent = fetch_all(
            tmp_path,
            "SELECT method FROM op_log WHERE method = 'messages.send'",
        )
        assert sent == []
