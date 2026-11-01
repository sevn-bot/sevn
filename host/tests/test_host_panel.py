"""Phase 6: the host panel. Ollama status, loaded models and queue depth."""

from __future__ import annotations

import json
import socket
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from support.chat import connected, load_modules, mint_id, ok, request


@contextmanager
def _ollama() -> Iterator[str]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/api/tags":
                body: dict[str, Any] = {"models": [{"name": "llama3.2:3b"}, {"name": "qwen3:8b"}]}
            elif self.path == "/api/ps":
                body = {"models": [{"name": "llama3.2:3b", "size_vram": 2_400_000_000}]}
            else:
                self.send_response(404)
                self.end_headers()
                return
            data = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def _closed_port() -> str:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    return f"http://127.0.0.1:{port}"


@pytest.fixture(autouse=True)
def _fresh_cache() -> Iterator[None]:
    from sevn.domain.host_status import reset_cache

    reset_cache()
    yield
    reset_cache()


async def _panel(client: Any) -> dict[str, Any]:
    frame, _earlier = await request(client, "fleet.overview", {})
    host = ok(frame)["host"]
    assert isinstance(host, dict)
    return host


async def test_without_ollama_configured(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    load_modules("sevn.api.fleet")
    async with connected(tmp_path, monkeypatch) as (_host, client):
        host = await _panel(client)
    assert host["ollama"]["configured"] is False
    assert host["ollama"]["reachable"] is None
    assert host["ollama"]["models"] == []
    assert host["queued_jobs"] == 0
    assert host["running_turns"] == 0
    assert host["max_running_turns"] == 3
    assert isinstance(host["version"], str) and host["version"] != ""
    assert datetime.fromisoformat(host["as_of"]) <= datetime.now(UTC)


async def test_reachable_ollama_lists_models_and_loaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    load_modules("sevn.api.fleet")
    with _ollama() as url:
        async with connected(tmp_path, monkeypatch) as (_host, client):
            monkeypatch.setenv("SEVN_OLLAMA_URL", url)
            host = await _panel(client)
    ollama = host["ollama"]
    assert ollama["configured"] is True
    assert ollama["reachable"] is True
    assert ollama["error"] is None
    assert ollama["models"] == ["llama3.2:3b", "qwen3:8b"]
    assert ollama["loaded"] == [{"name": "llama3.2:3b", "vram_bytes": 2_400_000_000}]


async def test_unreachable_ollama_says_so(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    load_modules("sevn.api.fleet")
    async with connected(tmp_path, monkeypatch) as (_host, client):
        monkeypatch.setenv("SEVN_OLLAMA_URL", _closed_port())
        host = await _panel(client)
    ollama = host["ollama"]
    assert ollama["configured"] is True
    assert ollama["reachable"] is False
    assert ollama["error"] == "unreachable"
    assert ollama["models"] == []


async def test_queue_depth_counts_queued_jobs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.domain.agents import AgentService
    from sevn.domain.jobs import JobService

    load_modules("sevn.api.bots", "sevn.api.fleet")
    async with connected(tmp_path, monkeypatch) as (_host, client):
        frame, _earlier = await request(
            client, "bots.create", {"name": "Nimbus", "op_id": mint_id("op_")}
        )
        bot_id = ok(frame)["id"]
        agent = await AgentService().spawn(bot_id)
        for _ in range(3):
            await JobService().enqueue(mint_id("job_"), bot_id, agent.id, "hi")
        await JobService().enqueue(mint_id("job_"), bot_id, agent.id, "done", status="done")
        host = await _panel(client)
    assert host["queued_jobs"] == 3
