"""Scrubbed transcript fixtures and latency notes for the spike report."""

from __future__ import annotations

import inspect
import json
import re
import uuid
from collections.abc import Callable
from pathlib import Path

from spike_rt.events import RuntimeEvent, map_native_event

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
_EVIDENCE = (
    Path(__file__).resolve().parents[4] / ".ignorelocal" / "evidence" / "0003-spike-cli-runtimes"
)
_SCRUBBERS = (
    (re.compile(r"/Users/[^/\s\"]+"), "<HOME>"),
    (re.compile(r"/home/[^/\s\"]+"), "<HOME>"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "<EMAIL>"),
    (re.compile(r"sk-[A-Za-z0-9_-]{8,}"), "sk-x"),
    (re.compile(r"Bearer [A-Za-z0-9._~+/=-]{8,}"), "Bearer x"),
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"), "gh-x"),
)

GUIDE = (
    "sevn tools: when the user asks you to call sevn_echo, call that MCP tool exactly "
    "once and pass the text argument exactly as they wrote it. Do not simulate the call "
    "with a shell command. When tool permission is denied, request permission again and "
    "retry the same tool. When asked to create out.txt, create that file in the working "
    "directory with the contents ok and no other files. When told not to use tools, do "
    "not use tools."
)


def write_guide(workspace: Path) -> None:
    """Drop the shared tool instructions into the workspace."""

    path = workspace / "AGENTS.md"
    if not path.is_file():
        path.write_text(GUIDE + "\n", encoding="utf-8")


def scrub(
    text: str,
    *,
    secrets: tuple[str, ...] = (),
    paths: tuple[str, ...] = (),
) -> str:
    """Replace home paths, the workspace, and known secret shapes."""

    home = Path.home().as_posix()
    if home:
        text = text.replace(home, "<HOME>")
    for path in paths:
        if not path:
            continue
        text = text.replace(path, "<WS>")
        if path.startswith("/private"):
            text = text.replace(path.removeprefix("/private"), "<WS>")
    user = Path.home().name
    if user:
        text = text.replace(f"/{user}/", "/<USER>/")
        text = text.replace(f"pytest-of-{user}", "pytest-of-<USER>")
    for secret in secrets:
        if len(secret) >= 8:
            text = text.replace(secret, "<TOKEN>")
    for pattern, replacement in _SCRUBBERS:
        text = pattern.sub(replacement, text)
    return text


def write_turn_fixture(
    runtime: str,
    natives: list[dict[str, object]],
    *,
    secrets: tuple[str, ...] = (),
    paths: tuple[str, ...] = (),
) -> None:
    """Write one jsonl transcript when it binds a session and then finishes."""

    kept: list[dict[str, object]] = []
    kinds: list[str] = []
    for native in natives:
        event = map_native_event(runtime, native)
        if event.kind == "ignored" and event.native_type == "unknown":
            continue
        kept.append(native)
        if event.kind != "ignored":
            kinds.append(event.kind)
    if "session_bound" not in kinds or "turn_finished" not in kinds:
        return
    if kinds.index("session_bound") > kinds.index("turn_finished"):
        return
    directory = _FIXTURES / runtime
    directory.mkdir(parents=True, exist_ok=True)
    lines = [
        scrub(json.dumps(native, ensure_ascii=False, default=str), secrets=secrets, paths=paths)
        for native in kept
    ]
    (directory / f"{uuid.uuid4().hex}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def note_metric(payload: dict[str, object]) -> None:
    """Append one scrubbed metric line under the plan evidence directory."""

    try:
        _EVIDENCE.mkdir(parents=True, exist_ok=True)
        line = scrub(json.dumps(payload, ensure_ascii=False, default=str))
        with (_EVIDENCE / "w3-metrics.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        return


async def invoke(
    callback: Callable[[RuntimeEvent], object] | None,
    event: RuntimeEvent,
) -> object:
    """Call a sync or async session callback."""

    if callback is None:
        return None
    result = callback(event)
    if inspect.isawaitable(result):
        return await result
    return result
