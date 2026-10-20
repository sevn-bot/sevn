"""One throwaway CLI turn with no tools. Subscription quota, so it can be disabled."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, cast

from sevn.config import Settings
from sevn.decisions.base import Attempt, attempt_from_model, model_prompt, parse_model_route
from sevn.decisions.thresholds import step_accepts
from sevn.domain.agents import AgentRecord
from sevn.domain.routing import RouterContext
from sevn.log import logger
from sevn.runtime.base import SessionRef, TurnContext
from sevn.runtime.events import RuntimeEvent
from sevn.store.db import utcnow

_CLI = frozenset({"claude", "codex", "opencode", "cursor"})
_runtime: object | None = None


class _Shot(Protocol):
    async def open(self, agent: AgentRecord) -> SessionRef: ...

    def run_turn(self, turn: TurnContext) -> AsyncIterator[RuntimeEvent]: ...

    async def close(self, agent_id: str) -> None: ...


def use_runtime(runtime: object | None) -> None:
    """Install the CLI runtime used for the one-shot. ``None`` clears it."""
    global _runtime
    _runtime = runtime


class CliOneShotDecider:
    """Open a session, ask once, and close it. The turn carries no tools."""

    async def attempt(self, context: RouterContext, state: str) -> Attempt | None:
        runtime = _runtime_for(context.runtime)
        if runtime is None:
            return None
        try:
            text = await _complete(cast("_Shot", runtime), _throwaway(context), model_prompt(state))
        except Exception:  # noqa: BLE001 — a failed CLI one-shot falls through
            logger.warning("cli decider failed")
            return None
        if text is None or text == "":
            return None
        parsed = parse_model_route(text)
        if parsed is None:
            return None
        return attempt_from_model(parsed, "cli", accepted=step_accepts(parsed.confidence))


def _runtime_for(name: str) -> object | None:
    if not Settings.load().decisions.allow_cli_fallback:
        return None
    if name not in _CLI:
        return None
    if _runtime is not None:
        return _runtime
    if name == "claude":
        from sevn.runtime.runtimes.claude import ClaudeRuntime, installed_client

        # The installed client belongs to live turns. A one-shot must not consume it.
        if installed_client() is not None:
            return None
        return ClaudeRuntime()
    return None


def _throwaway(context: RouterContext) -> AgentRecord:
    now = utcnow()
    runtime = "claude" if context.runtime == "claude" else "pydantic_ai"
    return AgentRecord(
        id="agent_throwaway",
        bot_id=context.bot_id,
        thread_id="thread_throwaway",
        title="",
        summary="",
        status="idle",
        runtime=runtime,
        runtime_session_ref=None,
        origin_job_id=None,
        isolation="shared",
        created_at=now,
        last_activity_at=now,
    )


async def _complete(runtime: _Shot, agent: AgentRecord, prompt: str) -> str | None:
    ref = await runtime.open(agent)
    try:
        turn = TurnContext(agent=agent, text=prompt, job_id="decision")
        deltas: list[str] = []
        finished = ""
        async for event in runtime.run_turn(turn):
            if event.kind == "text_delta" and event.text:
                deltas.append(event.text)
            elif event.kind == "turn_finished" and event.text:
                finished = event.text
        if deltas:
            return "".join(deltas)
        return finished
    finally:
        await runtime.close(ref.agent_id)
