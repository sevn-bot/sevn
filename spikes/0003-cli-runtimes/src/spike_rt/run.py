"""Run one spike scenario: ``python -m spike_rt.run <rt> <scenario>``."""

from __future__ import annotations

import argparse
import asyncio
import sys
import tempfile
from pathlib import Path

import anyio

from spike_rt.claude_rt import ClaudeSession, _scrub
from spike_rt.events import RuntimeEvent


async def open_session(
    runtime: str,
    workspace: Path,
    session_ref: str | None = None,
) -> ClaudeSession:
    """Create ``README.md``, set the runtime cwd, and open a session.

    ``session_ref`` resumes that CLI session. Codex and OpenCode arrive in W3.
    """

    await _prepare_workspace(workspace)
    if runtime == "claude":
        from spike_rt.claude_rt import open_claude_session

        return await open_claude_session(workspace, session_ref)
    raise RuntimeError(f"runtime {runtime!r} is not available")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m spike_rt.run")
    parser.add_argument("rt", choices=["claude", "codex", "opencode", "cursor"])
    parser.add_argument("scenario", choices=["echo", "permission", "resume", "interrupt"])
    args = parser.parse_args(argv)
    try:
        asyncio.run(_run(args.rt, args.scenario))
    except Exception as exc:  # noqa: BLE001
        print(_scrub(f"{args.rt} {args.scenario}: failed: {exc}"), file=sys.stderr)
        return 1
    print(f"{args.rt} {args.scenario}: ok")
    return 0


async def _run(runtime: str, scenario: str) -> None:
    with tempfile.TemporaryDirectory(prefix="spike-rt-") as raw:
        workspace = Path(raw)
        if scenario == "echo":
            await _echo(runtime, workspace)
        elif scenario == "permission":
            await _permission(runtime, workspace)
        elif scenario == "resume":
            await _resume(runtime, workspace)
        elif scenario == "interrupt":
            await _interrupt(runtime, workspace)
        else:
            raise RuntimeError(f"unknown scenario {scenario!r}")


async def _echo(runtime: str, workspace: Path) -> None:
    session = await open_session(runtime, workspace)
    try:
        events = await session.turn(
            'Call the sevn_echo tool exactly once with the text "ping".',
            on_permission=_approve_echo,
        )
        calls = session.mcp_calls
        if len(calls) != 1 or calls[0].arguments.get("text") != "ping":
            raise RuntimeError("sevn_echo was not called once with ping")
        if calls[0].bearer != session.bearer:
            raise RuntimeError("sevn_echo bearer did not match the session")
        if not any(event.kind == "session_bound" for event in events):
            raise RuntimeError("turn did not bind a session")
    finally:
        await session.aclose()


async def _permission(runtime: str, workspace: Path) -> None:
    seen: list[str] = []
    out_file = workspace / "out.txt"

    async def on_permission(event: RuntimeEvent) -> str:
        if event.request_id is None:
            raise RuntimeError("permission request has no id")
        seen.append(event.request_id)
        if len(seen) == 1:
            return "deny"
        return "approve"

    session = await open_session(runtime, workspace)
    try:
        await session.turn(
            "Create a file named out.txt in the working directory with the contents ok. "
            "If permission is denied, request permission again and create the file. "
            "Do not create any other file.",
            on_permission=on_permission,
        )
    finally:
        await session.aclose()
    if len(seen) < 2:
        raise RuntimeError("permission was not denied and then retried")
    text = await anyio.Path(out_file).read_text(encoding="utf-8")
    if "ok" not in text.lower():
        raise RuntimeError("out.txt was not created with ok")


async def _resume(runtime: str, workspace: Path) -> None:
    first = await open_session(runtime, workspace)
    try:
        await first.turn(
            'Call the sevn_echo tool exactly once with the text "ping".',
            on_permission=_approve_echo,
        )
        ref = first.session_ref
        if not isinstance(ref, str) or not ref:
            raise RuntimeError("first turn did not bind a session")
    finally:
        await first.aclose()
    second = await open_session(runtime, workspace, session_ref=ref)
    try:
        events = await second.turn("what did I ask before?")
        if second.session_ref != ref:
            raise RuntimeError("resumed session ref changed")
        if "ping" not in _blob(events).lower():
            raise RuntimeError("resumed turn did not mention ping")
    finally:
        await second.aclose()


async def _interrupt(runtime: str, workspace: Path) -> None:
    session = await open_session(runtime, workspace)
    try:
        saw_text = asyncio.Event()

        async def on_event(event: RuntimeEvent) -> None:
            if event.kind == "text_delta" and not saw_text.is_set():
                await session.interrupt()
                saw_text.set()

        async def on_permission(_event: RuntimeEvent) -> str:
            return "deny"

        task = asyncio.create_task(
            session.turn(
                "Write a detailed essay about rivers. Start the first sentence immediately "
                "and keep writing for at least 400 words. Do not call tools.",
                on_permission=on_permission,
                on_event=on_event,
            )
        )
        await asyncio.wait_for(saw_text.wait(), timeout=300)
        events = await asyncio.wait_for(task, timeout=10)
        if not any(_terminal(event) for event in events):
            raise RuntimeError("interrupted turn did not finish")
        ref = session.session_ref
        follow = await session.turn(
            "Reply with exactly the word pong. Do not use tools.",
            on_permission=on_permission,
        )
        if session.session_ref != ref or "pong" not in _blob(follow).lower():
            raise RuntimeError("session was not reusable after interrupt")
    finally:
        await session.aclose()


async def _approve_echo(event: RuntimeEvent) -> str:
    tool = event.tool or ""
    if tool == "sevn_echo" or tool.endswith("sevn_echo"):
        return "approve"
    return "deny"


def _terminal(event: RuntimeEvent) -> bool:
    return event.kind == "turn_finished" or (event.kind == "error" and event.code == "interrupted")


async def _prepare_workspace(workspace: Path) -> None:
    path = anyio.Path(workspace)
    await path.mkdir(parents=True, exist_ok=True)
    readme = path / "README.md"
    if not await readme.is_file():
        await readme.write_text("Spike workspace.\n", encoding="utf-8")


def _blob(events: list[RuntimeEvent]) -> str:
    parts: list[str] = []
    for event in events:
        if event.text:
            parts.append(event.text)
        if event.message:
            parts.append(event.message)
    return "\n".join(parts)


if __name__ == "__main__":
    raise SystemExit(main())
