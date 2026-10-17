"""Scripted ``ClaudeClient`` (connect, query, receive_response, interrupt).

Product types stay in the tests. ``receive_response`` yields spike-shaped native
dicts. A step ``{"kind": "permission", ...}`` awaits the ``can_use_tool`` callback
the runtime passed to ``connect`` and does not itself become a native event.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import AsyncIterator, Mapping
from typing import Any

from support.canary import note_claude_request


class FakeClaudeClient:
    """In-memory Claude SDK stand-in."""

    def __init__(self, script: list[Mapping[str, object]] | None = None) -> None:
        self.script = [dict(item) for item in script or []]
        self.connects: list[dict[str, object]] = []
        self.queries: list[str] = []
        self.interrupts = 0
        self.permission_results: list[object] = []
        self.permission_started = asyncio.Event()
        self._can_use_tool: Any = None

    async def connect(
        self,
        cwd: str | None = None,
        resume: str | None = None,
        can_use_tool: object = None,
        **options: object,
    ) -> None:
        recorded: dict[str, object] = {
            "cwd": cwd if cwd is not None else options.get("cwd"),
            "resume": resume if resume is not None else options.get("resume"),
        }
        recorded.update(options)
        self.connects.append(recorded)
        self._can_use_tool = (
            can_use_tool if can_use_tool is not None else options.get("can_use_tool")
        )
        note_claude_request(json.dumps({"connect": recorded}, default=str))

    async def query(self, prompt: str, **_options: object) -> None:
        self.queries.append(prompt)
        note_claude_request(prompt)

    async def receive_response(self) -> AsyncIterator[dict[str, object]]:
        for item in self.script:
            if item.get("kind") == "permission":
                await self._permission(item)
                continue
            yield dict(item)

    async def interrupt(self) -> None:
        self.interrupts += 1

    async def _permission(self, item: Mapping[str, object]) -> None:
        self.permission_started.set()
        callback = self._can_use_tool
        if callback is None:
            raise RuntimeError("claude runtime did not pass can_use_tool")
        tool = str(item.get("tool") or "")
        args = item.get("args") if isinstance(item.get("args"), dict) else {}
        request_id = item.get("request_id")
        outcome = callback(tool, args, request_id)
        if inspect.isawaitable(outcome):
            outcome = await outcome
        self.permission_results.append(outcome)
