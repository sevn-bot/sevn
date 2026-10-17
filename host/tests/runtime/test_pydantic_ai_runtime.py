"""Pydantic AI runtime, TurnRunner, and the model catalog (green after W3)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from fakes.models import function_model
from support.canary import canary, model_request_payloads, reset_model_requests
from support.chat import (
    connected,
    drain,
    error_body,
    fetch_all,
    handshake,
    insert_job,
    load_modules,
    mint_id,
    ok,
    request,
)

pytestmark = pytest.mark.xfail(reason="green after W3", strict=False)


async def _spawn(bot_id: str) -> Any:
    from sevn.domain.agents import AgentService

    return await AgentService().spawn(bot_id=bot_id)


def _agent_id(agent: object) -> str:
    value = getattr(agent, "id", None)
    assert isinstance(value, str)
    return value


@asynccontextmanager
async def _world(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    name: str = "Nimbus",
) -> AsyncIterator[tuple[Any, Any, dict[str, Any]]]:
    load_modules("sevn.api.bots")
    async with connected(tmp_path, monkeypatch) as (host, client):
        created = ok(
            (
                await request(
                    client,
                    "bots.create",
                    {"name": name, "op_id": mint_id("op_")},
                )
            )[0]
        )
        agent = await _spawn(str(created["id"]))
        created["agent_id"] = _agent_id(agent)
        created["thread_id"] = agent.thread_id
        yield host, client, created


async def _run_text(
    host: Any,
    home: Path,
    created: dict[str, Any],
    text: str,
    *,
    model: Any | None = None,
) -> str:
    from sevn.runtime.runtimes.pydantic_ai import PydanticAIRuntime
    from sevn.runtime.turn import TurnRunner

    job_id = await insert_job(
        home,
        bot_id=str(created["id"]),
        agent_id=str(created["agent_id"]),
        text=text,
    )
    runtime = PydanticAIRuntime() if model is None else PydanticAIRuntime(model=model)
    await TurnRunner(host.hub, runtime).run(job_id)
    return job_id


async def test_turn_streams_ticks_and_persists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pydantic_ai.messages import ModelMessagesTypeAdapter

    reset_model_requests()
    scripted = function_model([{"kind": "text", "text": "hello"}])
    async with _world(tmp_path, monkeypatch) as (host, client, created):
        await _run_text(host, tmp_path, created, "hello", model=scripted)
        frames = await drain(client, first=1)
        deltas = [
            str(frame.get("d", {}).get("text") or "")
            for frame in frames
            if frame.get("t") == "tick" and frame.get("k") == "turn.delta"
        ]
        assert "hello" in "".join(deltas)
        stored = await host.outbox.since(0)
        assert all(row.type != "turn.delta" for row in stored)
        created_events = [row for row in stored if row.type == "message.created"]
        assert created_events
        assert "hello" in json.dumps(created_events[-1].payload)
        turns = fetch_all(tmp_path, "SELECT model_messages FROM turns")
        assert len(turns) == 1
        raw = turns[0]["model_messages"]
        loaded = json.loads(raw) if isinstance(raw, str) else raw
        restored = ModelMessagesTypeAdapter.validate_python(loaded)
        again = json.loads(ModelMessagesTypeAdapter.dump_json(restored))
        assert again == loaded
        assert "hello" in json.dumps(loaded)


async def test_turn_persistence_is_one_transaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.store.models import Message
    from sqlalchemy import event

    def fail_after_insert(*_args: object) -> None:
        raise RuntimeError("injected failure after messages insert")

    event.listen(Message, "after_insert", fail_after_insert)
    try:
        scripted = function_model([{"kind": "text", "text": "hello"}])
        async with _world(tmp_path, monkeypatch) as (host, _client, created):
            job_id = await insert_job(
                tmp_path,
                bot_id=str(created["id"]),
                agent_id=str(created["agent_id"]),
                text="hello",
            )
            from sevn.runtime.runtimes.pydantic_ai import PydanticAIRuntime
            from sevn.runtime.turn import TurnRunner

            try:
                await TurnRunner(host.hub, PydanticAIRuntime(model=scripted)).run(job_id)
            except RuntimeError:
                pass
            turns = fetch_all(tmp_path, "SELECT id FROM turns")
            assert turns == []
            jobs = fetch_all(tmp_path, "SELECT status FROM jobs WHERE id = ?", (job_id,))
            assert jobs[0]["status"] == "started"
    finally:
        event.remove(Message, "after_insert", fail_after_insert)


async def test_agent_rebuilt_per_run_uses_current_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sevn.runtime.models as model_mod
    import sevn.runtime.runtimes.pydantic_ai as pai

    seen: list[str] = []

    def resolve(name: str) -> object:
        seen.append(name)
        return function_model([{"kind": "text", "text": "ok"}], model_name=name)

    monkeypatch.setattr(model_mod, "resolve_model", resolve)
    monkeypatch.setattr(pai, "resolve_model", resolve, raising=False)
    async with _world(tmp_path, monkeypatch) as (host, client, created):
        for model_name in ("anthropic:one", "openai:two"):
            updated, _earlier = await request(
                client,
                "bots.update",
                {"bot_id": created["id"], "model": model_name, "op_id": mint_id("op_")},
            )
            ok(updated)
            await _run_text(host, tmp_path, created, model_name)
    assert seen == ["anthropic:one", "openai:two"]


async def test_instructions_layout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reset_model_requests()
    scripted = function_model([{"kind": "text", "text": "ok"}])
    async with _world(tmp_path, monkeypatch) as (host, client, created):
        updated, _earlier = await request(
            client,
            "bots.update",
            {
                "bot_id": created["id"],
                "title": "Guide-Title",
                "instructions": "Be-brief-please",
                "op_id": mint_id("op_"),
            },
        )
        ok(updated)
        await _run_text(host, tmp_path, created, "hello", model=scripted)
        payloads = model_request_payloads()
        assert payloads
        instructions = payloads[-1]["instructions"]
        assert isinstance(instructions, str)
        workspace = str(created["workspace_path"])
        assert instructions.index("delegation") < instructions.index("Nimbus")
        assert instructions.index("untrusted") < instructions.index("Nimbus")
        assert (
            instructions.index("Nimbus")
            < instructions.index("Guide-Title")
            < instructions.index("Be-brief-please")
            < instructions.index(workspace)
        )
        folded = instructions.lower()
        assert "pinned memor" not in folded
        assert all(
            line.strip().lower() not in {"memory", "memories"} for line in instructions.splitlines()
        )


async def test_models_list_reflects_configured_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import httpx
    from sevn.config import Settings
    from sevn.paths import Paths
    from sevn.secrets.backends import open_backend

    class _Tags:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"models": [{"name": "llama3.2"}]}

    class _AsyncClient:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def __aenter__(self) -> _AsyncClient:
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

        async def get(self, url: str, *_args: object, **_kwargs: object) -> _Tags:
            assert "/api/tags" in url
            return _Tags()

    class _Client:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def __enter__(self) -> _Client:
            return self

        def __exit__(self, *_exc: object) -> None:
            return None

        def get(self, url: str, *_args: object, **_kwargs: object) -> _Tags:
            assert "/api/tags" in url
            return _Tags()

    def _get(url: str, *_args: object, **_kwargs: object) -> _Tags:
        assert "/api/tags" in url
        return _Tags()

    monkeypatch.setattr(httpx, "AsyncClient", _AsyncClient)
    monkeypatch.setattr(httpx, "Client", _Client)
    monkeypatch.setattr(httpx, "get", _get)
    load_modules("sevn.api.models", "sevn.api.bots")
    async with connected(tmp_path, monkeypatch) as (_host, client):
        open_backend(Settings.load(), Paths.from_env()).set("provider/anthropic", mint_id("key_"))
        listed, _earlier = await request(client, "models.list", {})
        models = ok(listed)["models"]
        assert isinstance(models, list) and models
        assert {item["provider"] for item in models} == {"anthropic"}
        assert all(str(item["id"]).startswith("anthropic:") for item in models)
        monkeypatch.setenv("SEVN_OLLAMA_URL", "http://ollama.test")
        listed, _earlier = await request(client, "models.list", {})
        models = ok(listed)["models"]
        assert any(item["provider"] == "anthropic" for item in models)
        assert any(
            item["provider"] == "ollama" and "llama3.2" in str(item["id"]) for item in models
        )


async def test_provider_key_absent_everywhere(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.config import Settings
    from sevn.paths import Paths
    from sevn.secrets.backends import open_backend

    reset_model_requests()
    scripted = function_model([{"kind": "text", "text": "ok"}])
    async with _world(tmp_path, monkeypatch) as (host, _client, created):
        second, _session = host.open()
        await handshake(second, host.token)
        with canary() as probe:
            probe.watch(second)
            open_backend(Settings.load(), Paths.from_env()).set("provider/anthropic", probe.value)
            await _run_text(host, tmp_path, created, "hello", model=scripted)
            await drain(second, first=0.5)
            turns = fetch_all(tmp_path, "SELECT id FROM turns")
            assert len(turns) == 1
            probe.assert_absent(probe.value)


async def test_echo_model_refused_without_sevn_dev(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.config import Settings
    from sevn.paths import Paths
    from sevn.secrets.backends import open_backend

    load_modules("sevn.api.models", "sevn.api.bots")
    async with connected(tmp_path, monkeypatch) as (_host, client):
        monkeypatch.setenv("SEVN_TEST_MODEL", "echo")
        open_backend(Settings.load(), Paths.from_env()).set("provider/anthropic", mint_id("key_"))
        listed, _earlier = await request(client, "models.list", {})
        models = ok(listed)["models"]
        assert isinstance(models, list) and models
        assert all("echo" not in str(item["id"]) for item in models)
        created = ok(
            (await request(client, "bots.create", {"name": "echo-bot", "op_id": mint_id("op_")}))[0]
        )
        frame, _earlier = await request(
            client,
            "bots.update",
            {"bot_id": created["id"], "model": "echo", "op_id": mint_id("op_")},
        )
        error = error_body(frame)
        assert error["code"] == "invalid_params"
        data = error["data"]
        assert isinstance(data, dict)
        errors = data["errors"]
        assert isinstance(errors, list)
        assert errors[0]["loc"] == ["model"]
