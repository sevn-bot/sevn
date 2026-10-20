"""Decider framework, fallback chain, decision log, and K-REG."""

from __future__ import annotations

import ast
import json
import sqlite3
import subprocess
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fakes.fake_jev import FakeJev, dump_requests
from fakes.fake_ollama import FakeOllama
from fakes.models import function_model
from support.botcore import (
    arm_configured,
    decision_rows,
    decision_text,
    secrets_toml,
    set_provider_key,
    upgrade_home,
)
from support.canary import canary
from support.repo import repo_root

_FEATURE_PREFIXES = (
    "sevn.memory",
    "sevn.sandbox",
    "sevn.browser",
    "sevn.computer",
    "sevn.voice",
    "sevn.routines",
    "sevn.skills",
    "sevn.mcp_bridge",
    "sevn.evals",
    "sevn.tools.files",
    "sevn.tools.shell",
    "sevn.tools.user",
    "sevn.tools.agents",
    "sevn.tools.history",
)


def _now() -> datetime:
    return datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


def _message(**overrides: object) -> object:
    from sevn.domain.routing import RoutedMessage

    body: dict[str, object] = {
        "text": "hello",
        "author": "user",
        "created_at": _now(),
        "source": "user",
        "new_agent": False,
        "reply_to": None,
        "reply_to_agent_id": None,
        "agent_id": None,
    }
    body.update(overrides)
    return RoutedMessage(**body)


def _agent(agent_id: str, title: str, summary: str, status: str) -> object:
    from sevn.domain.routing import OpenAgent

    return OpenAgent(id=agent_id, title=title, summary=summary, status=status)


def _context(
    agents: list[object],
    *,
    pending: list[object] | None = None,
    recent: dict[str, list[str]] | None = None,
    runtime: str = "pydantic_ai",
) -> object:
    from sevn.domain.routing import RouterContext

    return RouterContext(
        bot_id="bot_core",
        open_agents=agents,
        pending_questions=[] if pending is None else pending,
        recent_user_messages={} if recent is None else recent,
        runtime=runtime,
    )


def _pending(agent_id: str, asked_at: datetime) -> object:
    from sevn.domain.routing import PendingQuestion

    return PendingQuestion(agent_id=agent_id, asked_at=asked_at)


async def _rules(message: object, context: object) -> object | None:
    from sevn.decisions.rules import RuleDecider

    return await RuleDecider().decide(message, context)


def _criteria(question: object) -> dict[str, object]:
    assert isinstance(question, dict)
    raw = question.get("criteria")
    assert isinstance(raw, dict)
    return raw


class RecordingRuntime:
    """Throwaway CLI runtime. Records open/close and any tools it was given."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.opened: list[str] = []
        self.closed: list[str] = []
        self.session_refs: list[str] = []
        self.prompts: list[str] = []
        self.tools: list[object] = []

    async def open(self, agent: object | None = None) -> object:
        from sevn.runtime.base import SessionRef

        agent_id = str(getattr(agent, "id", "agent_throwaway"))
        self.opened.append(agent_id)
        self.session_refs.append("throwaway-session")
        tools = getattr(agent, "tools", None)
        if tools:
            self.tools.append(tools)
        return SessionRef(agent_id=agent_id, session_ref="throwaway-session")

    def run_turn(self, turn: object) -> Any:
        from sevn.runtime.events import RuntimeEvent

        tools = getattr(turn, "tools", None)
        if tools:
            self.tools.append(tools)
        self.prompts.append(str(getattr(turn, "text", "")))
        text = self.text

        async def generate() -> Any:
            yield RuntimeEvent(kind="text_delta", text=text)
            yield RuntimeEvent(kind="turn_finished", text=text, model_messages=[])

        return generate()

    async def close(self, agent_id: str) -> None:
        self.closed.append(agent_id)

    async def interrupt(self, agent_id: str) -> None:
        _ = agent_id

    async def answer(self, pending_id: str, answer: object) -> None:
        _ = (pending_id, answer)


def _imported(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = "." * node.level
                found.append(base if node.module is None else f"{base}{node.module}")
            elif node.module is not None:
                found.append(node.module)
    return found


def _forbidden(name: str) -> bool:
    return any(name == prefix or name.startswith(prefix + ".") for prefix in _FEATURE_PREFIXES)


_RULES: tuple[dict[str, Any], ...] = (
    {
        "name": "reply_to",
        "text": "/new side quest",
        "reply_to_agent_id": "agent_reply",
        "agent_id": "agent_explicit",
        "new_agent": False,
        "agents": (
            ("agent_reply", "Reply lane", "earlier work", "idle"),
            ("agent_explicit", "Other", "other", "running"),
        ),
        "intent": "follow_up",
        "target": "agent_reply",
    },
    {
        "name": "explicit_agent",
        "text": "/new side quest",
        "agent_id": "agent_explicit",
        "new_agent": True,
        "agents": (("agent_explicit", "Other", "other", "idle"),),
        "intent": "follow_up",
        "target": "agent_explicit",
    },
    {
        "name": "new_agent_flag",
        "text": "hello",
        "new_agent": True,
        "agents": (("agent_open", "Open", "work", "idle"),),
        "intent": "new_request",
        "target": None,
    },
    {
        "name": "slash_new",
        "text": "/new plan a trip",
        "agents": (("agent_open", "Open", "work", "running"),),
        "intent": "new_request",
        "target": None,
    },
    {
        "name": "continue",
        "text": "/continue Invoice",
        "agents": (
            ("agent_invoice", "Invoice fix", "taxes", "idle"),
            ("agent_trip", "Trip plan", "lisbon", "running"),
        ),
        "intent": "follow_up",
        "target": "agent_invoice",
    },
    {
        "name": "no_open_agents",
        "text": "hello",
        "agents": (),
        "intent": "new_request",
        "target": None,
    },
    {
        "name": "pending_answer",
        "text": "Tuesday",
        "agents": (("agent_q", "Question", "waiting on a day", "waiting"),),
        "pending": True,
        "intent": "answer",
        "target": "agent_q",
    },
)


@pytest.mark.parametrize("case", _RULES, ids=[item["name"] for item in _RULES])
async def test_rule_decider_first_match_wins(case: Mapping[str, Any]) -> None:
    agents = [_agent(*spec) for spec in case["agents"]]
    pending = None
    if case.get("pending") is True:
        pending = [_pending("agent_q", _now() - timedelta(minutes=1))]
    message = _message(
        text=case["text"],
        reply_to_agent_id=case.get("reply_to_agent_id"),
        agent_id=case.get("agent_id"),
        new_agent=bool(case.get("new_agent")),
    )
    decision = await _rules(message, _context(agents, pending=pending))
    assert decision is not None
    assert decision.intent == case["intent"]
    assert decision.target_agent_id == case["target"]
    assert decision.path == "rule"
    assert decision.confidence == 1.0


async def test_slash_new_must_start_the_text() -> None:
    agents = [_agent("agent_open", "Open", "work", "idle")]
    decision = await _rules(_message(text="please /new"), _context(agents))
    assert decision is None


async def test_continue_requires_a_unique_open_agent() -> None:
    agents = [
        _agent("agent_a", "Invoice fix", "taxes", "idle"),
        _agent("agent_b", "Invoice history", "older", "idle"),
    ]
    ambiguous = await _rules(_message(text="/continue Invoice"), _context(agents))
    assert ambiguous is None
    wrong_case = [
        _agent("agent_a", "Invoice fix", "taxes", "idle"),
        _agent("agent_b", "Trip plan", "lisbon", "idle"),
    ]
    missed = await _rules(_message(text="/continue invoice"), _context(wrong_case))
    assert missed is None


async def test_stale_or_ambiguous_pending_is_not_an_answer() -> None:
    agents = [_agent("agent_q", "Question", "day", "waiting")]
    stale = await _rules(
        _message(text="Tuesday"),
        _context(agents, pending=[_pending("agent_q", _now() - timedelta(minutes=10, seconds=1))]),
    )
    assert stale is None
    both = [
        _agent("agent_q", "Question", "day", "waiting"),
        _agent("agent_r", "Other", "also waiting", "waiting"),
    ]
    ambiguous = await _rules(
        _message(text="Tuesday"),
        _context(
            both,
            pending=[
                _pending("agent_q", _now() - timedelta(minutes=1)),
                _pending("agent_r", _now() - timedelta(minutes=1)),
            ],
        ),
    )
    assert ambiguous is None
    fresh = await _rules(
        _message(text="Tuesday"),
        _context(agents, pending=[_pending("agent_q", _now() - timedelta(minutes=10))]),
    )
    assert fresh is not None
    assert fresh.intent == "answer"
    assert fresh.target_agent_id == "agent_q"


async def test_jev_request_has_all_router_questions_in_one_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.decisions.jev import use_client
    from sevn.decisions.registry import decide

    arm_configured(monkeypatch, tmp_path)
    await upgrade_home(tmp_path)
    agent = _agent("agent_trip", "Trip plan", "lisbon dates", "running")
    long_history = "H" * 2500
    recent = {
        "agent_trip": ["oldest-dropped", "keep-one", "keep-two", long_history],
    }
    fake = FakeJev(
        answers={
            "message.intent": ("follow_up", 0.95),
            "message.target_agent": ("agent_trip", 0.91),
            "busy.policy": ("steer", 0.9),
        }
    )
    use_client(fake)
    try:
        decision = await decide(
            _message(text="make it four days"),
            _context([agent], recent=recent),
        )
    finally:
        use_client(None)
    assert decision.intent == "follow_up"
    assert decision.path == "jev"
    assert len(fake.requests) == 1
    request = fake.requests[0]
    assert request.model == "jev-1.13.0"
    assert set(request.questions) == {"message.intent", "message.target_agent", "busy.policy"}
    intent = _criteria(request.questions["message.intent"])
    assert set(intent) == {
        "new_request",
        "follow_up",
        "steer",
        "answer",
        "cancel",
        "chit_chat",
    }
    target = _criteria(request.questions["message.target_agent"])
    assert set(target) == {"agent_trip", "none"}
    assert target["agent_trip"] == "Trip plan — lisbon dates"
    busy = _criteria(request.questions["busy.policy"])
    assert set(busy) == {"queue", "steer", "interrupt"}
    state = request.text()
    assert "make it four days" in state
    assert "keep-one" in state
    assert "keep-two" in state
    assert "oldest-dropped" not in state
    assert state.count("H") <= 2000


async def test_busy_policy_omitted_when_no_agent_is_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.decisions.jev import use_client
    from sevn.decisions.registry import decide

    arm_configured(monkeypatch, tmp_path)
    await upgrade_home(tmp_path)
    fake = FakeJev(
        answers={
            "message.intent": ("follow_up", 0.95),
            "message.target_agent": ("agent_idle", 0.9),
        }
    )
    use_client(fake)
    try:
        await decide(
            _message(text="and the hotel"),
            _context([_agent("agent_idle", "Hotel", "booked", "idle")]),
        )
    finally:
        use_client(None)
    assert len(fake.requests) == 1
    assert set(fake.requests[0].questions) == {"message.intent", "message.target_agent"}


async def test_state_is_redacted_before_jev(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.decisions.jev import use_client
    from sevn.decisions.registry import decide

    arm_configured(monkeypatch, tmp_path)
    await upgrade_home(tmp_path)
    fake = FakeJev(answers={"message.intent": ("new_request", 0.99)})
    use_client(fake)
    try:
        with canary() as probe:
            await decide(_message(text=f"plan the trip {probe.value}"), _context([]))
            assert fake.requests
            blob = dump_requests(fake)
            assert "plan the trip" in blob
            probe.assert_absent(probe.value)
            assert probe.value not in blob
    finally:
        use_client(None)


@pytest.mark.parametrize("path", ["llm", "ollama", "cli"])
async def test_state_is_redacted_before_every_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    from sevn.decisions.cli_oneshot import use_runtime
    from sevn.decisions.jev import use_client
    from sevn.decisions.registry import decide
    from sevn.runtime.models import use_model
    from support.canary import model_request_payloads, reset_model_requests

    arm_configured(monkeypatch, tmp_path)
    await upgrade_home(tmp_path)
    reset_model_requests()
    runtime = RecordingRuntime(decision_text("new_request", None, 0.95))
    ollama = FakeOllama(decision_text("new_request", None, 0.95))
    use_client(None)
    use_runtime(None)
    use_model(None)
    try:
        with canary() as probe, ollama:
            text = f"plan the trip {probe.value}"
            if path == "llm":
                set_provider_key()
                use_model(
                    function_model(
                        [{"kind": "text", "text": decision_text("new_request", None, 0.95)}]
                    )
                )
            elif path == "ollama":
                monkeypatch.setenv("SEVN_OLLAMA_URL", ollama.url)
            else:
                use_runtime(runtime)
            await decide(_message(text=text), _context([], runtime="claude"))
            if path == "llm":
                blob = json.dumps(model_request_payloads(), default=str)
            elif path == "ollama":
                blob = ollama.text()
            else:
                blob = "\n".join(runtime.prompts)
            assert "plan the trip" in blob
            assert probe.value not in blob
            probe.assert_absent(probe.value)
    finally:
        use_client(None)
        use_runtime(None)
        use_model(None)


async def test_decision_log_state_redacted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sevn.decisions.jev import use_client
    from sevn.decisions.registry import decide

    arm_configured(monkeypatch, tmp_path)
    await upgrade_home(tmp_path)
    fake = FakeJev(answers={"message.intent": ("new_request", 0.99)})
    use_client(fake)
    try:
        with canary() as probe:
            await decide(_message(text=f"plan the trip {probe.value}"), _context([]))
            rows = decision_rows(tmp_path)
            assert rows
            stored = "\n".join(str(row["state_redacted"]) for row in rows)
            assert "plan the trip" in stored
            assert probe.value not in stored
            assert all(str(row["input_hash"]) for row in rows)
            probe.assert_absent(probe.value)
    finally:
        use_client(None)


async def test_decision_log_state_truncated_to_4000(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.decisions.jev import use_client
    from sevn.decisions.registry import decide

    arm_configured(monkeypatch, tmp_path)
    await upgrade_home(tmp_path)
    fake = FakeJev(answers={"message.intent": ("new_request", 0.99)})
    use_client(fake)
    try:
        await decide(_message(text="A" * 5000 + "TAILMARKER"), _context([]))
    finally:
        use_client(None)
    rows = decision_rows(tmp_path)
    assert rows
    for row in rows:
        assert len(str(row["state_redacted"])) <= 4000


_CHAIN = (
    "jev_low_to_llm",
    "no_key_to_ollama",
    "no_ollama_to_cli",
    "cli_disabled_to_default",
    "ambiguous_asks_user",
    "llm_low_to_ollama",
)


@pytest.mark.parametrize("case", _CHAIN)
async def test_fallback_chain_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    from sevn.decisions.cli_oneshot import use_runtime
    from sevn.decisions.jev import use_client
    from sevn.decisions.registry import decide
    from sevn.runtime.models import use_model

    extra = ""
    if case == "cli_disabled_to_default":
        extra = "[decisions]\nallow_cli_fallback = false\n"
    arm_configured(monkeypatch, tmp_path, secrets_toml(extra))
    await upgrade_home(tmp_path)
    invoice = _agent("agent_invoice", "Invoice fix", "taxes", "idle")
    trip = _agent("agent_trip", "Trip plan", "lisbon", "idle")
    agents = [invoice, trip] if case == "ambiguous_asks_user" else [invoice]
    runtime_name = "claude" if case == "no_ollama_to_cli" else "pydantic_ai"
    target = None if case == "ambiguous_asks_user" else "agent_invoice"
    jev = FakeJev(
        answers={
            "message.intent": ("follow_up", 0.1),
            "message.target_agent": ("agent_invoice", 0.1),
        }
    )
    llm_confidence = 0.5 if case == "llm_low_to_ollama" else 0.95
    ollama_body = decision_text("follow_up", "agent_invoice", 0.95)
    cli_body = decision_text("follow_up", "agent_invoice", 0.95)
    runtime = RecordingRuntime(cli_body)
    use_client(None)
    use_runtime(None)
    use_model(None)
    try:
        with FakeOllama(ollama_body) as ollama:
            if case == "jev_low_to_llm":
                use_client(jev)
                set_provider_key()
                use_model(
                    function_model(
                        [
                            {
                                "kind": "text",
                                "text": decision_text("follow_up", "agent_invoice", 0.95),
                            }
                        ]
                    )
                )
            elif case == "no_key_to_ollama":
                monkeypatch.setenv("SEVN_OLLAMA_URL", ollama.url)
            elif case == "no_ollama_to_cli":
                use_runtime(runtime)
            elif case == "llm_low_to_ollama":
                set_provider_key()
                use_model(
                    function_model(
                        [
                            {
                                "kind": "text",
                                "text": decision_text("follow_up", "agent_invoice", llm_confidence),
                            }
                        ]
                    )
                )
                monkeypatch.setenv("SEVN_OLLAMA_URL", ollama.url)
            elif case == "cli_disabled_to_default":
                use_runtime(runtime)
            decision = await decide(
                _message(text="follow up on the invoice"),
                _context(agents, runtime=runtime_name),
            )
            paths = [str(row["path"]) for row in decision_rows(tmp_path)]
            if case == "jev_low_to_llm":
                assert decision.path == "llm"
                assert decision.intent == "follow_up"
                assert decision.target_agent_id == target
                assert paths == ["jev", "llm"]
                assert ollama.requests == []
                assert runtime.opened == []
            elif case == "no_key_to_ollama":
                assert decision.path == "ollama"
                assert paths == ["ollama"]
                assert jev.requests == []
            elif case == "no_ollama_to_cli":
                assert decision.path == "cli"
                assert paths == ["cli"]
                assert runtime.opened
                assert runtime.closed == runtime.opened
            elif case == "cli_disabled_to_default":
                assert decision.path == "default"
                assert decision.intent == "follow_up"
                assert decision.target_agent_id == "agent_invoice"
                assert paths == ["default"]
                assert runtime.opened == []
            elif case == "llm_low_to_ollama":
                assert decision.path == "ollama"
                assert paths == ["llm", "ollama"]
            else:
                assert decision.path == "user"
                assert decision.ask_user is True
                assert paths == ["user"]
                assert "New task" in decision.choices
                assert "Continue: Invoice fix" in decision.choices
                assert "Continue: Trip plan" in decision.choices
                assert len(decision.choices) == 3
    finally:
        use_client(None)
        use_runtime(None)
        use_model(None)


async def test_cli_fallback_uses_throwaway_session_without_tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.decisions.cli_oneshot import use_runtime
    from sevn.decisions.registry import decide

    arm_configured(monkeypatch, tmp_path)
    await upgrade_home(tmp_path)
    runtime = RecordingRuntime(decision_text("new_request", None, 0.95))
    use_runtime(runtime)
    try:
        decision = await decide(_message(text="plan a trip"), _context([], runtime="claude"))
    finally:
        use_runtime(None)
    assert decision.path == "cli"
    assert runtime.opened
    assert runtime.closed == runtime.opened
    assert runtime.session_refs == ["throwaway-session"] * len(runtime.opened)
    assert runtime.tools == []


async def test_default_decider_single_open_agent_follow_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sevn.decisions.registry import decide

    arm_configured(
        monkeypatch,
        tmp_path,
        secrets_toml("[decisions]\nallow_cli_fallback = false\n"),
    )
    await upgrade_home(tmp_path)
    decision = await decide(
        _message(text="add a line"),
        _context([_agent("agent_only", "Invoice fix", "taxes", "idle")], runtime="claude"),
    )
    assert decision.path == "default"
    assert decision.intent == "follow_up"
    assert decision.target_agent_id == "agent_only"
    assert decision.ask_user is False
    assert [str(row["path"]) for row in decision_rows(tmp_path)] == ["default"]


async def test_provider_rules_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sevn.decisions.cli_oneshot import use_runtime
    from sevn.decisions.jev import use_client
    from sevn.decisions.registry import decide
    from sevn.runtime.models import use_model
    from support.canary import model_request_payloads, reset_model_requests

    arm_configured(monkeypatch, tmp_path, secrets_toml('[decisions]\nprovider = "rules"\n'))
    await upgrade_home(tmp_path)
    reset_model_requests()
    fake = FakeJev(answers={"message.intent": ("new_request", 0.99)})
    runtime = RecordingRuntime(decision_text("new_request", None, 0.99))
    use_client(fake)
    use_runtime(runtime)
    use_model(function_model([{"kind": "text", "text": decision_text("new_request", None, 0.99)}]))
    try:
        with FakeOllama(decision_text("new_request", None, 0.99)) as ollama:
            monkeypatch.setenv("SEVN_OLLAMA_URL", ollama.url)
            set_provider_key()
            agents = [
                _agent("agent_a", "Invoice fix", "taxes", "idle"),
                _agent("agent_b", "Trip plan", "lisbon", "idle"),
            ]
            await decide(_message(text="hello there"), _context(agents, runtime="claude"))
            assert fake.requests == []
            assert ollama.requests == []
            assert runtime.opened == []
            assert model_request_payloads() == []
    finally:
        use_client(None)
        use_runtime(None)
        use_model(None)


def test_thresholds_from_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sevn.config import Settings

    arm_configured(monkeypatch, tmp_path)
    defaults = Settings.load().decisions
    assert defaults.thresholds.intent == 0.70
    assert defaults.thresholds.target == 0.65
    assert defaults.thresholds.busy == 0.60
    assert defaults.jev_model == "jev-1.13.0"
    assert defaults.ollama_model == "llama3.2:3b"
    assert defaults.allow_cli_fallback is True
    assert defaults.provider == "jev"
    assert defaults.evals_on is False
    (tmp_path / "config.toml").write_text(
        secrets_toml(
            "\n".join(
                (
                    "",
                    "[decisions]",
                    'provider = "rules"',
                    'jev_model = "jev-1.13.0"',
                    'llm_model = "anthropic:claude-haiku-4-5"',
                    'ollama_model = "llama3.2:3b"',
                    "allow_cli_fallback = false",
                    "evals_on = true",
                    "",
                    "[decisions.thresholds]",
                    "intent = 0.91",
                    "target = 0.55",
                    "busy = 0.42",
                    "",
                )
            )
        ),
        encoding="utf-8",
    )
    loaded = Settings.load().decisions
    assert loaded.thresholds.intent == 0.91
    assert loaded.thresholds.target == 0.55
    assert loaded.thresholds.busy == 0.42
    assert loaded.provider == "rules"
    assert loaded.llm_model == "anthropic:claude-haiku-4-5"
    assert loaded.allow_cli_fallback is False
    assert loaded.evals_on is True


async def test_register_source_rule_ordering() -> None:
    from sevn.decisions.base import RouteDecision
    from sevn.domain.routing import clear_source_rules, register_source_rule

    calls: list[str] = []

    def earlier(message: object, context: object) -> RouteDecision | None:
        _ = (message, context)
        calls.append("earlier")
        return RouteDecision(
            intent="cancel",
            target_agent_id="agent_a",
            confidence=1.0,
            path="rule",
        )

    def later(message: object, context: object) -> RouteDecision | None:
        _ = (message, context)
        calls.append("later")
        return RouteDecision(
            intent="chit_chat",
            target_agent_id=None,
            confidence=1.0,
            path="rule",
        )

    def skip(message: object, context: object) -> None:
        _ = (message, context)
        calls.append("skip")
        return None

    clear_source_rules()
    try:
        register_source_rule("user", later, order=20)
        register_source_rule("user", earlier, order=5)
        agents = [
            _agent("agent_a", "Invoice fix", "taxes", "idle"),
            _agent("agent_b", "Trip plan", "lisbon", "idle"),
        ]
        decision = await _rules(_message(text="hello there"), _context(agents))
        assert decision is not None
        assert decision.intent == "cancel"
        assert "later" not in calls
        calls.clear()
        clear_source_rules()
        register_source_rule("user", skip, order=1)
        register_source_rule("user", later, order=2)
        fallen = await _rules(_message(text="hello there"), _context(agents))
        assert fallen is not None
        assert fallen.intent == "chit_chat"
        assert calls == ["skip", "later"]
    finally:
        clear_source_rules()


async def test_register_source_rule_is_source_scoped() -> None:
    from sevn.decisions.base import RouteDecision
    from sevn.domain.routing import clear_source_rules, register_source_rule

    def webhook_rule(message: object, context: object) -> RouteDecision:
        _ = (message, context)
        return RouteDecision(
            intent="new_request",
            target_agent_id=None,
            confidence=1.0,
            path="rule",
        )

    clear_source_rules()
    try:
        register_source_rule("webhook", webhook_rule, order=0)
        agents = [
            _agent("agent_a", "Invoice fix", "taxes", "idle"),
            _agent("agent_b", "Trip plan", "lisbon", "idle"),
        ]
        user_decision = await _rules(_message(text="hello there", source="user"), _context(agents))
        assert user_decision is None
        hooked = await _rules(_message(text="hello there", source="webhook"), _context(agents))
        assert hooked is not None
        assert hooked.intent == "new_request"
        assert hooked.path == "rule"
    finally:
        clear_source_rules()


async def test_register_toolset_condition(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sevn.domain.bots import BotService
    from sevn.tools.registry import register_toolset, toolsets_for, unregister_toolset

    arm_configured(monkeypatch, tmp_path)
    await upgrade_home(tmp_path)

    def factory(_deps: object) -> dict[str, object]:
        return {"tools": ["shell"]}

    def only_full(bot: object) -> bool:
        return getattr(bot, "access", "") == "full"

    register_toolset("gated", factory, eager={"shell"}, condition=only_full)
    register_toolset("always", factory, eager=set())
    try:
        workspace = await BotService().create("Workspace", access="workspace")
        full = await BotService().create("Full", access="full")
        workspace_names = {item.name for item in toolsets_for(workspace)}
        full_names = {item.name for item in toolsets_for(full)}
        assert "gated" not in workspace_names
        assert "always" in workspace_names
        assert "gated" in full_names
        gated = next(item for item in toolsets_for(full) if item.name == "gated")
        assert gated.eager == {"shell"}
    finally:
        unregister_toolset("gated")
        unregister_toolset("always")


def test_core_modules_import_no_feature_modules() -> None:
    root = repo_root()
    routing = root / "host/src/sevn/domain/routing.py"
    core = root / "host/src/sevn/tools/core.py"
    assert routing.is_file()
    assert core.is_file(), "tools/core.py is missing"
    for path in (routing, core):
        offenders = [name for name in _imported(path) if _forbidden(name)]
        assert offenders == [], f"{path.name} imports feature modules: {offenders}"


def test_migrations_single_head() -> None:
    completed = subprocess.run(
        ["make", "db-heads"],  # noqa: S607
        cwd=repo_root(),
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert "0003_router_memory" in completed.stdout


def test_upgrade_from_previous_head(tmp_path: Path) -> None:
    from alembic import command
    from alembic.config import Config

    database = tmp_path / "sevn.db"
    cfg = Config(str(repo_root() / "host" / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{database}")
    command.upgrade(cfg, "0002_bots_agents")
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
                'workspace', 'ask', '/tmp/ws', NULL, 0, 1, 'user', ?, ?
            )
            """,
            (now, now),
        )
        connection.execute(
            """
            INSERT INTO agents (
                id, bot_id, thread_id, title, summary, status, runtime,
                runtime_session_ref, origin_job_id, isolation, created_at, last_activity_at
            ) VALUES (
                'agent_fixture', 'bot_fixture', 'thread_fixture', 'Invoice fix', 'taxes',
                'idle', 'pydantic_ai', NULL, NULL, 'shared', ?, ?
            )
            """,
            (now, now),
        )
        connection.commit()
    command.upgrade(cfg, "head")
    with sqlite3.connect(database) as connection:
        bot = connection.execute("SELECT name FROM bots WHERE id = 'bot_fixture'").fetchone()
        agent = connection.execute(
            "SELECT title, thread_id FROM agents WHERE id = 'agent_fixture'"
        ).fetchone()
        names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
            )
        }
        decision_cols = {row[1] for row in connection.execute("PRAGMA table_info(decision_log)")}
        route_cols = {row[1] for row in connection.execute("PRAGMA table_info(route_decisions)")}
        lock_cols = {row[1] for row in connection.execute("PRAGMA table_info(agent_locks)")}
        agent_cols = {row[1] for row in connection.execute("PRAGMA table_info(agents)")}
        bot_cols = {row[1] for row in connection.execute("PRAGMA table_info(bots)")}
    assert bot == ("Nimbus",)
    assert agent == ("Invoice fix", "thread_fixture")
    assert {
        "decision_log",
        "route_decisions",
        "memories",
        "memories_fts",
        "messages_fts",
        "agent_locks",
    } <= names
    assert {
        "id",
        "point",
        "input_hash",
        "state_redacted",
        "answers",
        "confidences",
        "path",
        "outcome",
        "corrected_to",
        "created_at",
    } <= decision_cols
    assert "message_id" in route_cols
    assert {"path", "agent_id", "acquired_at", "expires_at"} <= lock_cols
    assert {"idle_since", "archived_at", "isolation"} <= agent_cols
    assert "network" in bot_cols


def test_doctor_reports_decision_routing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from sevn.cli import app
    from sevn.config import Settings
    from sevn.paths import Paths
    from sevn.secrets.backends import open_backend
    from typer.testing import CliRunner

    arm_configured(monkeypatch, tmp_path)
    runner = CliRunner()
    first = runner.invoke(app, ["doctor", "--json"])
    assert first.exit_code == 0, first.output
    body = json.loads(first.stdout)
    assert body["jev_key"] == "no"
    assert body["ollama"] == "no"
    assert body["allow_cli_fallback"] is True
    assert body["decisions_provider"] == "jev"
    (tmp_path / "config.toml").write_text(
        secrets_toml('[decisions]\nprovider = "rules"\nallow_cli_fallback = false\n'),
        encoding="utf-8",
    )
    open_backend(Settings.load(), Paths.from_env()).set("provider/typesafe", "test-typesafe-key")
    with FakeOllama('{"intent":"new_request","target_agent_id":null,"confidence":0.9}') as ollama:
        monkeypatch.setenv("SEVN_OLLAMA_URL", ollama.url)
        second = runner.invoke(app, ["doctor", "--json"])
    assert second.exit_code == 0, second.output
    updated = json.loads(second.stdout)
    assert updated["jev_key"] == "yes"
    assert updated["ollama"] == "yes"
    assert updated["allow_cli_fallback"] is False
    assert updated["decisions_provider"] == "rules"
