"""Live subscription-CLI scenarios (D3, D5, D6).

``await spike_rt.run.open_session(runtime, workspace, session_ref=None)`` returns a
session whose ``turn(prompt, *, on_permission, on_event)`` streams ``RuntimeEvent``
values. Callbacks may be coroutines and are awaited. ``on_permission`` returns
``"deny"`` or ``"approve"``. ``await session.interrupt()`` from ``on_event`` must
return without waiting for ``turn`` to finish. ``await session.aclose()`` releases
the process. ``session.bearer`` is the raw MCP token; ``session.mcp_calls`` records
each ``sevn_echo`` call (``name``, ``arguments``, ``bearer``). ``session.session_ref``
is the CLI resume id from ``session_bound``.

Claude, Codex, and OpenCode markers were removed in W2.R and W3.R.
Cursor stays bonus D6. Its session/new auth failure is a no-go, not a skip.
A missing login skips with ``skipped: no live gate``.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import json
import subprocess
from pathlib import Path

import pytest

_TURN_TIMEOUT_S = 300.0
_INTERRUPT_DEADLINE_S = 10.0

_RUNTIMES = [
    "claude",
    "codex",
    "opencode",
    pytest.param("cursor", marks=pytest.mark.xfail(strict=False, reason="bonus D6")),
]


def _require_login(runtime: str) -> None:
    if not _logged_in(runtime):
        pytest.skip("skipped: no live gate")


@functools.cache
def _logged_in(runtime: str) -> bool:
    try:
        if runtime == "claude":
            completed = _status(["claude", "auth", "status", "--json"])
            if completed.returncode != 0:
                return False
            payload = json.loads(completed.stdout)
            return isinstance(payload, dict) and payload.get("loggedIn") is True
        if runtime == "codex":
            completed = _status(["codex", "login", "status"])
            if completed.returncode != 0:
                return False
            text = f"{completed.stdout}\n{completed.stderr}".lower()
            return "logged in" in text and "not logged" not in text
        if runtime == "opencode":
            completed = _status(["opencode", "auth", "list", "--format", "json"])
            if completed.returncode != 0:
                return False
            payload = json.loads(completed.stdout)
            if not isinstance(payload, list):
                return False
            return any(
                isinstance(item, dict)
                and isinstance(item.get("connections"), list)
                and len(item["connections"]) > 0
                for item in payload
            )
        if runtime == "cursor":
            completed = _status(["cursor-agent", "status", "--format", "json"])
            if completed.returncode != 0:
                return False
            payload = json.loads(completed.stdout)
            return isinstance(payload, dict) and payload.get("isAuthenticated") is True
    except (OSError, json.JSONDecodeError):
        return False
    pytest.fail(f"unknown runtime {runtime}")


def _status(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, capture_output=True, text=True, timeout=30, check=False)


async def _drain(*tasks: asyncio.Task[object]) -> None:
    for item in tasks:
        if not item.done():
            item.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await item


async def _open(runtime: str, workspace: Path, session_ref: str | None = None) -> object:
    try:
        from spike_rt.run import open_session  # type: ignore[reportMissingImports]
    except ImportError as exc:
        pytest.fail(f"missing spike_rt.run.open_session ({exc})")
    session = await open_session(runtime, workspace, session_ref=session_ref)
    try:
        assert (workspace / "README.md").is_file()
    except AssertionError:
        await session.aclose()
        raise
    return session


def _blob(events: object, calls: object = ()) -> str:
    parts: list[str] = []
    for event in events:  # type: ignore[attr-defined]
        for name in ("text", "message"):
            value = getattr(event, name, None)
            if isinstance(value, str):
                parts.append(value)
        args = getattr(event, "args", None)
        if isinstance(args, dict):
            parts.append(json.dumps(args, default=str))
    for call in calls:  # type: ignore[attr-defined]
        arguments = getattr(call, "arguments", None)
        if isinstance(arguments, dict):
            parts.append(json.dumps(arguments, default=str))
    return "\n".join(parts)


def _is_terminal(event: object) -> bool:
    kind = getattr(event, "kind", None)
    if kind == "turn_finished":
        return True
    return kind == "error" and getattr(event, "code", None) == "interrupted"


async def _approve_echo(event: object) -> str:
    tool = getattr(event, "tool", "")
    if tool == "sevn_echo" or (isinstance(tool, str) and tool.endswith("sevn_echo")):
        return "approve"
    return "deny"


@pytest.mark.live
@pytest.mark.parametrize("runtime", _RUNTIMES)
def test_turn_calls_sevn_echo(runtime: str, tmp_path: Path) -> None:
    _require_login(runtime)
    asyncio.run(_turn_calls_sevn_echo(runtime, tmp_path))


async def _turn_calls_sevn_echo(runtime: str, workspace: Path) -> None:
    session = await _open(runtime, workspace)
    try:
        events = await asyncio.wait_for(
            session.turn(  # type: ignore[attr-defined]
                'Call the sevn_echo tool exactly once with the text "ping".',
                on_permission=_approve_echo,
            ),
            timeout=_TURN_TIMEOUT_S,
        )
        calls = session.mcp_calls  # type: ignore[attr-defined]
        assert len(calls) == 1
        call = calls[0]
        assert call.name == "sevn_echo"
        assert call.arguments["text"] == "ping"
        bearer = session.bearer  # type: ignore[attr-defined]
        assert bearer
        assert call.bearer == bearer
        assert "ping" in _blob(events, calls).lower()
        assert any(getattr(event, "kind", None) == "session_bound" for event in events)
        assert isinstance(session.session_ref, str) and session.session_ref  # type: ignore[attr-defined]
    finally:
        await session.aclose()  # type: ignore[attr-defined]


@pytest.mark.live
@pytest.mark.parametrize("runtime", _RUNTIMES)
def test_permission_deny_then_approve(runtime: str, tmp_path: Path) -> None:
    _require_login(runtime)
    asyncio.run(_permission_deny_then_approve(runtime, tmp_path))


async def _permission_deny_then_approve(runtime: str, workspace: Path) -> None:
    out_file = workspace / "out.txt"
    seen: list[str] = []

    async def on_permission(event: object) -> str:
        assert getattr(event, "kind", None) == "permission_request"
        tool = getattr(event, "tool", None)
        args = getattr(event, "args", None)
        request_id = getattr(event, "request_id", None)
        assert isinstance(tool, str) and tool
        assert isinstance(args, dict)
        assert isinstance(request_id, str) and request_id
        seen.append(request_id)
        if len(seen) <= 2:
            assert not out_file.exists()
        if len(seen) == 1:
            return "deny"
        return "approve"

    session = await _open(runtime, workspace)
    try:
        await asyncio.wait_for(
            session.turn(  # type: ignore[attr-defined]
                "Create a file named out.txt in the working directory with the contents ok. "
                "If permission is denied, request permission again and create the file. "
                "Do not create any other file.",
                on_permission=on_permission,
            ),
            timeout=_TURN_TIMEOUT_S,
        )
        assert len(seen) >= 2
        assert out_file.is_file()
        assert "ok" in out_file.read_text(encoding="utf-8").lower()
    finally:
        await session.aclose()  # type: ignore[attr-defined]


@pytest.mark.live
@pytest.mark.parametrize("runtime", _RUNTIMES)
def test_resume_by_session_ref(runtime: str, tmp_path: Path) -> None:
    _require_login(runtime)
    asyncio.run(_resume_by_session_ref(runtime, tmp_path))


async def _resume_by_session_ref(runtime: str, workspace: Path) -> None:
    first = await _open(runtime, workspace)
    try:
        await asyncio.wait_for(
            first.turn(  # type: ignore[attr-defined]
                'Call the sevn_echo tool exactly once with the text "ping".',
                on_permission=_approve_echo,
            ),
            timeout=_TURN_TIMEOUT_S,
        )
        ref = first.session_ref  # type: ignore[attr-defined]
        assert isinstance(ref, str) and ref
    finally:
        await first.aclose()  # type: ignore[attr-defined]

    second = await _open(runtime, workspace, session_ref=ref)
    try:
        events = await asyncio.wait_for(
            second.turn("what did I ask before?"),  # type: ignore[attr-defined]
            timeout=_TURN_TIMEOUT_S,
        )
        assert second.session_ref == ref  # type: ignore[attr-defined]
        assert "ping" in _blob(events).lower()
    finally:
        await second.aclose()  # type: ignore[attr-defined]


@pytest.mark.live
@pytest.mark.parametrize("runtime", _RUNTIMES)
def test_interrupt_mid_turn(runtime: str, tmp_path: Path) -> None:
    _require_login(runtime)
    asyncio.run(_interrupt_mid_turn(runtime, tmp_path))


async def _interrupt_mid_turn(runtime: str, workspace: Path) -> None:
    session = await _open(runtime, workspace)
    try:
        saw_text = asyncio.Event()

        async def on_event(event: object) -> None:
            if getattr(event, "kind", None) == "text_delta" and not saw_text.is_set():
                await session.interrupt()  # type: ignore[attr-defined]
                saw_text.set()

        async def on_permission(_event: object) -> str:
            return "deny"

        task = asyncio.create_task(
            session.turn(  # type: ignore[attr-defined]
                "Write a detailed essay about rivers. Start the first sentence immediately "
                "and keep writing for at least 400 words. Do not call tools.",
                on_permission=on_permission,
                on_event=on_event,
            )
        )
        text_wait = asyncio.create_task(saw_text.wait())
        done, _pending = await asyncio.wait(
            {text_wait, task},
            timeout=_TURN_TIMEOUT_S,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if task in done and not saw_text.is_set():
            await _drain(text_wait)
            exc = task.exception()
            if exc is not None:
                raise exc
            pytest.fail("turn finished before a text_delta")
        if not saw_text.is_set():
            await _drain(task, text_wait)
            pytest.fail("no text_delta arrived to interrupt")
        await _drain(text_wait)
        try:
            events = await asyncio.wait_for(task, timeout=_INTERRUPT_DEADLINE_S)
        except TimeoutError:
            await _drain(task)
            pytest.fail('turn_finished or error code "interrupted" did not arrive within 10s')
        assert any(_is_terminal(event) for event in events)
        ref = session.session_ref  # type: ignore[attr-defined]
        assert isinstance(ref, str) and ref
        follow = await asyncio.wait_for(
            session.turn(  # type: ignore[attr-defined]
                "Reply with exactly the word pong. Do not use tools.",
                on_permission=on_permission,
            ),
            timeout=_TURN_TIMEOUT_S,
        )
        assert any(getattr(event, "kind", None) == "turn_finished" for event in follow)
        assert session.session_ref == ref  # type: ignore[attr-defined]
        assert "pong" in _blob(follow).lower()
    finally:
        await session.aclose()  # type: ignore[attr-defined]
