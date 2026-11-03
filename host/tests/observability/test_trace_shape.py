"""Trace shape: job -> route.decide -> turn -> tools (plan 0015 D5).

These tests run against the in-memory span exporter (``span_exporter``): the SDK
provider is global, so sevn's spans and Pydantic AI's spans land in one place.
"""

from __future__ import annotations

import contextvars
import importlib
import json
import re
import secrets
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

import pytest
from fakes.fake_claude import FakeClaudeClient
from fakes.fake_jev import FakeJev
from fakes.models import function_model
from support.botcore import (
    arm_configured,
    decision_text,
    secrets_toml,
    set_provider_key,
    upgrade_home,
)
from support.chat import (
    connected,
    fetch_all,
    insert_job,
    insert_turn,
    load_modules,
    mint_id,
    ok,
    poll_rows,
    request,
)
from support.repo import repo_root
from support.spans import (
    attribute_text,
    descends_from,
    finished,
    named,
    one,
    parent_hex,
    span_hex,
    trace_hex,
    traceparent_of,
    wait_spans,
)

pytestmark = pytest.mark.usefixtures("otel_clean")

_PREVIOUS_HEAD = "0005_metrics_shares"
_HEAD = "0010_trace_context"
_SEVN_SPANS = {"job", "route.decide", "turn"}
_ID_SHAPE = re.compile(r"[a-z]+_[0-9A-HJKMNP-TV-Z]{26}")
_WRITE_NOTE = [
    [{"kind": "tool", "name": "write_file", "args": {"path": "note.txt", "content": "traced"}}],
    [{"kind": "text", "text": "done"}],
]
_CLAUDE_TOOLS = [
    {"type": "system", "subtype": "init", "session_id": "sess_trace"},
    {
        "type": "assistant",
        "block": {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}},
    },
    {"type": "user", "block": {"type": "tool_result", "name": "Bash", "is_error": False}},
    {
        "type": "assistant",
        "block": {"type": "tool_use", "name": "Read", "input": {"file_path": "missing.txt"}},
    },
    {"type": "user", "block": {"type": "tool_result", "name": "Read", "is_error": True}},
    {
        "type": "stream_event",
        "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "ok"}},
    },
    {"type": "result", "usage": {"input_tokens": 3, "output_tokens": 2}, "result": "ok"},
]


def _spans_module() -> Any:
    """The module under test. Importing it first makes these tests fail fast before W3."""
    return importlib.import_module("sevn.observability.spans")


def _attrs(span: Any) -> dict[str, Any]:
    return dict(span.attributes or {})


async def _create_bot(client: Any, **extra: object) -> dict[str, Any]:
    frame, _earlier = await request(
        client, "bots.create", {"name": "Nimbus", "op_id": mint_id("op_"), **extra}
    )
    return ok(frame)


async def _send(client: Any, bot_id: object, text: str) -> dict[str, Any]:
    frame, _earlier = await request(
        client, "messages.send", {"bot_id": bot_id, "text": text, "op_id": mint_id("op_")}
    )
    return ok(frame)


async def _network_on(client: Any, bot_id: str) -> None:
    frame, _earlier = await request(
        client, "bots.update", {"bot_id": bot_id, "network": "on", "op_id": mint_id("op_")}
    )
    ok(frame)


async def _job_finished(home: Path, job_id: str, *, status: str = "done") -> None:
    await poll_rows(
        home,
        "SELECT status FROM jobs WHERE id = ?",
        (job_id,),
        lambda rows: bool(rows) and rows[0]["status"] == status,
    )


def _execute(home: Path, sql: str, args: tuple[object, ...]) -> None:
    with sqlite3.connect(home / "sevn.db") as connection:
        connection.execute(sql, args)
        connection.commit()


def _kick_fresh(hub: Any, agent_id: str) -> None:
    """Bind the worker and start ``agent_id`` from an empty context.

    The pump task copies this empty context, so a turn can only find its parent
    through ``jobs.trace_parent``, never through a span left active by the request.
    """
    from sevn.runtime.worker import bind

    def start() -> None:
        bind(hub).kick(agent_id)

    contextvars.Context().run(start)


def _turn_row(home: Path, agent_id: str) -> dict[str, Any]:
    rows = fetch_all(home, "SELECT id, model, usage FROM turns WHERE agent_id = ?", (agent_id,))
    assert len(rows) == 1, [dict(row) for row in rows]
    row = dict(rows[0])
    usage = row["usage"]
    row["usage"] = json.loads(usage) if isinstance(usage, str) else usage
    return row


async def _pydantic_message(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    exporter: Any,
    text: str,
    script: list[Any],
) -> tuple[dict[str, Any], dict[str, Any], list[Any]]:
    """Send one message to a Pydantic AI bot; return ``(bot, sent, spans)``."""
    from sevn.runtime.models import use_model
    from sevn.runtime.worker import bind

    load_modules("sevn.api.bots", "sevn.api.messages")
    use_model(function_model(script))
    try:
        async with connected(tmp_path, monkeypatch) as (host, client):
            bind(host.hub)
            bot = await _create_bot(client)
            sent = await _send(client, bot["id"], text)
            await _job_finished(tmp_path, str(sent["job_id"]))
            spans = await wait_spans(
                exporter, lambda found: bool(named(found, "job")) and bool(named(found, "turn"))
            )
    finally:
        use_model(None)
    return bot, sent, spans


# --- one message, one trace ---------------------------------------------------------


async def test_one_message_is_one_trace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, span_exporter: Any
) -> None:
    _spans_module()
    text = "write the note " + secrets.token_hex(4)
    bot, sent, spans = await _pydantic_message(
        tmp_path, monkeypatch, span_exporter, text, _WRITE_NOTE
    )
    job = one(spans, "job")
    turn = one(spans, "turn")
    routes = named(spans, "route.decide")
    tools = [span for span in spans if _attrs(span).get("gen_ai.tool.name") == "write_file"]
    chats = [span for span in spans if _attrs(span).get("gen_ai.operation.name") == "chat"]

    assert job.parent is None
    assert routes, [span.name for span in spans]
    assert tools, [span.name for span in spans]
    assert chats, [span.name for span in spans]
    assert {trace_hex(span) for span in spans} == {trace_hex(job)}
    assert all(parent_hex(route) == span_hex(job) for route in routes)
    assert parent_hex(turn) == span_hex(job)
    assert all(descends_from(tool, turn, spans) for tool in tools)
    assert all(descends_from(chat, turn, spans) for chat in chats)

    job_attrs = _attrs(job)
    assert job_attrs["sevn.job_id"] == sent["job_id"]
    assert job_attrs["sevn.bot_id"] == bot["id"]
    assert job_attrs["sevn.source"] == "user"
    assert job_attrs["sevn.content.size"] == len(text.encode("utf-8"))
    assert "sevn.content.text" not in job_attrs

    turn_attrs = _attrs(turn)
    row = _turn_row(tmp_path, str(sent["agent_id"]))
    assert turn_attrs["sevn.turn_id"] == row["id"]
    assert turn_attrs["sevn.job_id"] == sent["job_id"]
    assert turn_attrs["sevn.agent_id"] == sent["agent_id"]
    assert turn_attrs["sevn.bot_id"] == bot["id"]
    assert turn_attrs["sevn.runtime"] == "pydantic_ai"
    # Content capture is off by default: the message text is in no span.
    assert all(text not in attribute_text(span) for span in spans)


async def test_route_decide_span_per_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, span_exporter: Any
) -> None:
    """A jev miss then an LLM accept: two route.decide spans, in order, with paths."""
    from sevn.decisions.jev import use_client
    from sevn.decisions.registry import decide
    from sevn.domain.routing import OpenAgent, RoutedMessage, RouterContext
    from sevn.runtime.models import use_model
    from sevn.store.db import utcnow

    _spans_module()
    arm_configured(monkeypatch, tmp_path, secrets_toml())
    await upgrade_home(tmp_path)
    use_client(
        FakeJev(
            answers={
                "message.intent": ("follow_up", 0.1),
                "message.target_agent": ("agent_invoice", 0.1),
            }
        )
    )
    set_provider_key()
    use_model(
        function_model(
            [{"kind": "text", "text": decision_text("follow_up", "agent_invoice", 0.95)}]
        )
    )
    try:
        decision = await decide(
            RoutedMessage(
                text="follow up on the invoice",
                author="user",
                created_at=utcnow(),
                source="user",
                new_agent=False,
                reply_to=None,
                reply_to_agent_id=None,
                agent_id=None,
            ),
            RouterContext(
                bot_id="bot_core",
                open_agents=[
                    OpenAgent(
                        id="agent_invoice", title="Invoice fix", summary="taxes", status="idle"
                    )
                ],
                pending_questions=[],
                recent_user_messages={},
                runtime="pydantic_ai",
            ),
        )
    finally:
        use_client(None)
        use_model(None)
    assert decision.path == "llm"
    routes = sorted(
        named(finished(span_exporter), "route.decide"), key=lambda span: span.start_time
    )
    assert [_attrs(span)["sevn.decision_path"] for span in routes] == ["jev", "llm"]
    assert [_attrs(span)["sevn.accepted"] for span in routes] == [False, True]
    assert all(_attrs(span)["sevn.decision_point"] == "route" for span in routes)
    assert _attrs(routes[1])["sevn.confidence"] == pytest.approx(0.95)
    assert all(isinstance(_attrs(span)["sevn.confidence"], float) for span in routes)


# --- trace context travels on the job row ----------------------------------------------


async def test_turn_parented_from_job_row_across_tasks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, span_exporter: Any
) -> None:
    from sevn.runtime.models import use_model

    _spans_module()
    load_modules("sevn.api.bots", "sevn.api.messages")
    use_model(function_model([{"kind": "text", "text": "ok"}]))
    try:
        async with connected(tmp_path, monkeypatch) as (host, client):
            # No worker yet: the job waits in the queue after messages.send returns.
            bot = await _create_bot(client)
            sent = await _send(client, bot["id"], "hello")
            job = one(finished(span_exporter), "job")
            rows = fetch_all(
                tmp_path, "SELECT trace_parent FROM jobs WHERE id = ?", (sent["job_id"],)
            )
            assert rows[0]["trace_parent"] == traceparent_of(job)
            _kick_fresh(host.hub, str(sent["agent_id"]))
            await _job_finished(tmp_path, str(sent["job_id"]))
            spans = await wait_spans(span_exporter, lambda found: bool(named(found, "turn")))
    finally:
        use_model(None)
    turn = one(spans, "turn")
    assert trace_hex(turn) == trace_hex(job)
    assert parent_hex(turn) == span_hex(job)


async def test_resumed_turn_after_restart_stays_in_trace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, span_exporter: Any
) -> None:
    from sevn.domain.agents import AgentService
    from sevn.runtime.models import use_model
    from sevn.runtime.recovery import recover

    _spans_module()
    trace_id = secrets.token_hex(16)
    span_id = secrets.token_hex(8)
    load_modules("sevn.api.bots")
    try:
        async with connected(tmp_path, monkeypatch) as (host, client):
            bot = await _create_bot(client)
            agent = await AgentService().spawn(bot_id=str(bot["id"]))
            job_id = await insert_job(
                tmp_path, bot_id=str(bot["id"]), agent_id=agent.id, text="crashed", status="started"
            )
            await insert_turn(
                tmp_path,
                agent_id=agent.id,
                thread_id=agent.thread_id,
                job_id=job_id,
                status="running",
                model_messages=None,
            )
            _execute(
                tmp_path,
                "UPDATE jobs SET trace_parent = ? WHERE id = ?",
                (f"00-{trace_id}-{span_id}-01", job_id),
            )
            await recover()
            use_model(function_model([{"kind": "text", "text": "done"}]))
            _kick_fresh(host.hub, agent.id)
            await _job_finished(tmp_path, job_id)
            spans = await wait_spans(span_exporter, lambda found: bool(named(found, "turn")))
    finally:
        use_model(None)
    turn = one(spans, "turn")
    assert trace_hex(turn) == trace_id
    assert parent_hex(turn) == span_id


@pytest.mark.parametrize(
    "stored",
    [
        "zz-not-a-traceparent",
        "00-" + "0" * 32 + "-" + "0" * 16 + "-01",
        "00-" + "a" * 31 + "-" + "b" * 16 + "-01",
    ],
)
async def test_invalid_trace_parent_starts_new_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, span_exporter: Any, stored: str
) -> None:
    from sevn.domain.agents import AgentService
    from sevn.runtime.models import use_model

    _spans_module()
    load_modules("sevn.api.bots")
    use_model(function_model([{"kind": "text", "text": "ok"}]))
    try:
        async with connected(tmp_path, monkeypatch) as (host, client):
            bot = await _create_bot(client)
            agent = await AgentService().spawn(bot_id=str(bot["id"]))
            job_id = await insert_job(
                tmp_path, bot_id=str(bot["id"]), agent_id=agent.id, text="hello"
            )
            _execute(tmp_path, "UPDATE jobs SET trace_parent = ? WHERE id = ?", (stored, job_id))
            _kick_fresh(host.hub, agent.id)
            await _job_finished(tmp_path, job_id)
            spans = await wait_spans(span_exporter, lambda found: bool(named(found, "turn")))
    finally:
        use_model(None)
    turn = one(spans, "turn")
    assert turn.parent is None
    assert turn.context.trace_id != 0
    assert tuple(turn.links) == ()


# --- turn attributes --------------------------------------------------------------------


async def test_turn_span_carries_usage_cost_and_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, span_exporter: Any
) -> None:
    _spans_module()
    _bot, sent, spans = await _pydantic_message(
        tmp_path, monkeypatch, span_exporter, "count the tokens", _WRITE_NOTE
    )
    turn = _attrs(one(spans, "turn"))
    row = _turn_row(tmp_path, str(sent["agent_id"]))
    usage = row["usage"]
    assert turn["sevn.stop"] == "end"
    assert turn["sevn.runtime"] == "pydantic_ai"
    assert turn["gen_ai.request.model"] == row["model"]
    assert turn["gen_ai.usage.input_tokens"] == usage["input_tokens"]
    assert turn["gen_ai.usage.output_tokens"] == usage["output_tokens"]
    assert turn["sevn.cost_source"] == usage["cost_source"]
    if usage["cost_usd"] is None:
        assert "sevn.cost_usd" not in turn
    else:
        assert turn["sevn.cost_usd"] == pytest.approx(usage["cost_usd"])


async def test_failed_turn_span_stop_is_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, span_exporter: Any
) -> None:
    from opentelemetry.trace import StatusCode
    from pydantic_ai.models.function import FunctionModel
    from sevn.runtime.models import use_model
    from sevn.runtime.worker import bind

    _spans_module()

    def boom(_messages: Any, _info: Any) -> Any:
        raise RuntimeError("model down")

    async def boom_stream(_messages: Any, _info: Any) -> Any:
        raise RuntimeError("model down")
        yield ""  # pragma: no cover - makes this an async generator

    load_modules("sevn.api.bots", "sevn.api.messages")
    use_model(FunctionModel(boom, stream_function=boom_stream))
    try:
        async with connected(tmp_path, monkeypatch) as (host, client):
            bind(host.hub)
            bot = await _create_bot(client)
            sent = await _send(client, bot["id"], "this will fail")
            await _job_finished(tmp_path, str(sent["job_id"]), status="failed")
            spans = await wait_spans(span_exporter, lambda found: bool(named(found, "turn")))
    finally:
        use_model(None)
    turn = one(spans, "turn")
    assert _attrs(turn)["sevn.stop"] == "error"
    assert turn.status.status_code == StatusCode.ERROR


async def test_cli_tool_events_become_tool_spans(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, span_exporter: Any
) -> None:
    """Claude runtime: mapped tool start/end events open and close ``tool.<name>`` spans."""
    from opentelemetry.trace import StatusCode
    from sevn.runtime.runtimes.claude import use_client
    from sevn.runtime.worker import bind

    _spans_module()
    use_client(FakeClaudeClient(script=_CLAUDE_TOOLS))
    load_modules("sevn.api.bots", "sevn.api.messages")
    try:
        async with connected(tmp_path, monkeypatch) as (host, client):
            bind(host.hub)
            bot = await _create_bot(client, runtime="claude", access="full")
            await _network_on(client, str(bot["id"]))
            sent = await _send(client, bot["id"], "list the files")
            await _job_finished(tmp_path, str(sent["job_id"]))
            spans = await wait_spans(
                span_exporter,
                lambda found: bool(named(found, "turn")) and bool(named(found, "job")),
            )
    finally:
        use_client(None)
    turn = one(spans, "turn")
    bash = one(spans, "tool.Bash")
    read = one(spans, "tool.Read")
    row = _turn_row(tmp_path, str(sent["agent_id"]))
    assert _attrs(turn)["sevn.runtime"] == "claude"
    assert _attrs(turn)["sevn.cost_source"] == "subscription"
    for tool, name in ((bash, "Bash"), (read, "Read")):
        attrs = _attrs(tool)
        assert parent_hex(tool) == span_hex(turn)
        assert trace_hex(tool) == trace_hex(turn)
        assert attrs["gen_ai.tool.name"] == name
        assert attrs["sevn.turn_id"] == row["id"]
        assert attrs["sevn.agent_id"] == sent["agent_id"]
        assert "sevn.content.size" in attrs
    assert bash.status.status_code != StatusCode.ERROR
    assert read.status.status_code == StatusCode.ERROR
    # Tool arguments are content: with capture off they are size and hash only.
    assert "missing.txt" not in attribute_text(read)
    assert bash.start_time <= read.start_time


async def test_span_names_contain_no_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, span_exporter: Any
) -> None:
    _spans_module()
    bot, sent, spans = await _pydantic_message(
        tmp_path, monkeypatch, span_exporter, "name check", _WRITE_NOTE
    )
    row = _turn_row(tmp_path, str(sent["agent_id"]))
    ids = {str(bot["id"]), str(sent["job_id"]), str(sent["agent_id"]), str(row["id"])}
    for span in spans:
        assert not any(value in span.name for value in ids), span.name
        assert _ID_SHAPE.search(span.name) is None, span.name
    sevn_names = {span.name for span in spans if span.instrumentation_scope.name.startswith("sevn")}
    assert sevn_names, [span.name for span in spans]
    assert all(name in _SEVN_SPANS or name.startswith("tool.") for name in sevn_names)


async def test_tracing_off_writes_null_trace_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.runtime.models import use_model
    from sevn.runtime.worker import bind

    _spans_module()
    load_modules("sevn.api.bots", "sevn.api.messages")
    use_model(function_model([{"kind": "text", "text": "ok"}]))
    try:
        async with connected(tmp_path, monkeypatch) as (host, client):
            bind(host.hub)
            bot = await _create_bot(client)
            sent = await _send(client, bot["id"], "untraced")
            await _job_finished(tmp_path, str(sent["job_id"]))
    finally:
        use_model(None)
    rows = fetch_all(tmp_path, "SELECT trace_parent FROM jobs WHERE id = ?", (sent["job_id"],))
    assert rows[0]["trace_parent"] is None


def test_job_span_is_a_new_root_inside_an_active_span(span_exporter: Any) -> None:
    from opentelemetry import trace
    from sevn.observability.spans import job_span

    tracer = trace.get_tracer("sevn.tests")
    with (
        tracer.start_as_current_span("websocket"),
        job_span("user", job_id="job_test", bot_id="bot_test") as span,
    ):
        assert span.is_recording()
    spans = finished(span_exporter)
    job = one(spans, "job")
    outer = one(spans, "websocket")
    assert job.parent is None
    assert trace_hex(job) != trace_hex(outer)
    assert _attrs(job)["sevn.source"] == "user"
    assert _attrs(job)["sevn.job_id"] == "job_test"
    assert _attrs(job)["sevn.bot_id"] == "bot_test"


# --- K-MIG -------------------------------------------------------------------------------


def test_migrations_single_head() -> None:
    completed = subprocess.run(
        ["make", "--no-print-directory", "db-heads"],  # noqa: S607 — the repo Makefile target
        cwd=repo_root(),
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    assert lines == [f"{_HEAD} (head)"], completed.stdout


def test_migration_file_chains_from_the_previous_head() -> None:
    import importlib.util

    path = repo_root() / "host/src/sevn/store/migrations/versions/0010_trace_context.py"
    assert path.is_file()
    spec = importlib.util.spec_from_file_location("sevn_0010_trace_context", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == _HEAD
    assert module.down_revision == _PREVIOUS_HEAD
    text = path.read_text(encoding="utf-8")
    assert "sevn.store.models" not in text


def test_upgrade_from_previous_head(tmp_path: Path) -> None:
    from alembic import command
    from alembic.config import Config

    database = tmp_path / "sevn.db"
    cfg = Config(str(repo_root() / "host" / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{database}")
    command.upgrade(cfg, _PREVIOUS_HEAD)
    now = "2026-01-01T00:00:00+00:00"
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """
            INSERT INTO bots (
                id, name, title, scope, instructions, avatar, runtime, model, effort,
                access, approval_policy, workspace_path, folder_id, paused,
                can_create_bots, created_by, created_at, updated_at
            ) VALUES (
                'bot_fixture', 'Nimbus', '', '', '', '', 'pydantic_ai', 'echo', NULL,
                'workspace', 'ask', 'workspace/nimbus', NULL, 0, 1, 'user', ?, ?
            )
            """,
            (now, now),
        )
        connection.execute(
            """
            INSERT INTO jobs (
                id, to_bot_id, agent_id, route_decision_id, origin, text, attachments,
                reply_to, expects_reply, hop, status, created_at, started_at, finished_at
            ) VALUES (
                'job_fixture', 'bot_fixture', NULL, NULL, 'user', 'kept text', '[]',
                NULL, 0, 0, 'done', ?, NULL, NULL
            )
            """,
            (now,),
        )
        connection.commit()
    command.upgrade(cfg, "head")
    with sqlite3.connect(database) as connection:
        job = connection.execute(
            "SELECT text, status, trace_parent FROM jobs WHERE id = 'job_fixture'"
        ).fetchone()
        bot = connection.execute("SELECT name FROM bots WHERE id = 'bot_fixture'").fetchone()
        columns = {row[1]: row for row in connection.execute("PRAGMA table_info(jobs)")}
        version = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    assert bot == ("Nimbus",)
    assert job == ("kept text", "done", None)
    assert "trace_parent" in columns
    assert columns["trace_parent"][2].upper() == "TEXT"
    assert columns["trace_parent"][3] == 0
    assert version == (_HEAD,)
