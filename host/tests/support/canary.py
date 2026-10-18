"""K-CANARY kit (plan 0010).

``canary()`` mints a secret, stores it in the active secret backend, and registers
it with the redaction registry. ``assert_absent`` scans the captures this plan
hooks: loguru sinks, the events / op_log / messages / turns tables, FunctionModel
and FakeClaudeClient requests, and frames delivered to sessions.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
from collections.abc import Callable, Mapping
from pathlib import Path

CAPTURES: tuple[str, ...] = (
    "logs",
    "events",
    "op_log",
    "messages",
    "turns",
    "function_model",
    "fake_claude",
    "second_session",
)

_model_requests: list[dict[str, object]] = []
_claude_requests: list[str] = []


def note_model_request(payload: Mapping[str, object]) -> None:
    """Record one FunctionModel request for the open canary."""
    _model_requests.append(dict(payload))


def note_claude_request(payload: str) -> None:
    """Record one FakeClaudeClient prompt or connect payload."""
    _claude_requests.append(payload)


def model_request_payloads() -> list[dict[str, object]]:
    return [dict(item) for item in _model_requests]


def reset_model_requests() -> None:
    _model_requests.clear()


class Canary:
    """One generated secret plus the captures ``assert_absent`` reads."""

    def __init__(self, value: str, name: str) -> None:
        self.value = value
        self.name = name
        self.capture_names = CAPTURES
        self._planted: dict[str, list[str]] = {name: [] for name in CAPTURES}
        self._logs: list[str] = []
        self._frames: list[str] = []
        self._sink_id: int | None = None
        self._restore_fanout: Callable[[], None] | None = None
        self._model_start = 0
        self._claude_start = 0
        self._closed = False

    def __enter__(self) -> Canary:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def plant(self, capture: str, value: str) -> None:
        """Put ``value`` into one capture so ``assert_absent`` must fail."""
        self._planted[_known(capture)].append(value)

    def unplant(self, capture: str) -> None:
        self._planted[_known(capture)].clear()

    def watch(self, client: object) -> None:
        """Record frames this second session receives."""
        recv = getattr(client, "recv_text", None)
        if not callable(recv):
            raise TypeError("session client has no recv_text")

        async def wrapped() -> str:
            frame = await recv()
            text = frame if isinstance(frame, str) else str(frame)
            self.note_frame(text)
            return text

        client.recv_text = wrapped  # type: ignore[attr-defined]

    def note_frame(self, frame: str) -> None:
        if not self._closed:
            self._frames.append(frame)

    def assert_absent(self, value: str) -> None:
        """Fail when ``value`` appears in any capture."""
        for name, text in self._snapshot():
            if value and value in text:
                raise AssertionError(f"canary leaked in {name}")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        global _active
        if _active is self:
            _active = None
        if self._sink_id is not None:
            from sevn.log import logger

            logger.remove(self._sink_id)
            self._sink_id = None
        if self._restore_fanout is not None:
            self._restore_fanout()
            self._restore_fanout = None

    def open(self) -> None:
        global _active
        if _active is not None:
            raise RuntimeError("a canary is already open")
        _active = self
        self._model_start = len(_model_requests)
        self._claude_start = len(_claude_requests)
        self._install_log_sink()
        self._install_fanout_hook()

    def _install_log_sink(self) -> None:
        from sevn.log import logger, redact

        logger.configure(patcher=redact)

        def _record(message: object) -> None:
            self._logs.append(str(message))

        self._sink_id = logger.add(_record)

    def _install_fanout_hook(self) -> None:
        from sevn.protocol.hub import Hub

        original = Hub._fanout

        async def wrapped(hub: Hub, frame: str) -> None:
            self.note_frame(frame)
            await original(hub, frame)

        Hub._fanout = wrapped  # type: ignore[method-assign]

        def restore() -> None:
            Hub._fanout = original  # type: ignore[method-assign]

        self._restore_fanout = restore

    def _snapshot(self) -> list[tuple[str, str]]:
        from sevn.log import logger
        from sevn.paths import Paths

        logger.complete()
        db = Paths.from_env().db
        tables = {
            "events": _table_text(
                db, "events", "SELECT seq, type, entity, payload, created_at FROM events"
            ),
            "op_log": _table_text(
                db, "op_log", "SELECT op_id, method, result, created_at FROM op_log"
            ),
            "messages": _table_text(db, "messages", "SELECT * FROM messages"),
            "turns": _table_text(db, "turns", "SELECT * FROM turns"),
        }
        model_blob = json.dumps(_model_requests[self._model_start :], default=str)
        claude_blob = "\n".join(_claude_requests[self._claude_start :])
        frames = "\n".join(self._frames)
        logs = "\n".join(self._logs)
        bodies = {
            "logs": logs,
            "events": tables["events"],
            "op_log": tables["op_log"],
            "messages": tables["messages"],
            "turns": tables["turns"],
            "function_model": model_blob,
            "fake_claude": claude_blob,
            "second_session": frames,
        }
        found: list[tuple[str, str]] = []
        for name in CAPTURES:
            planted = "\n".join(self._planted[name])
            found.append((name, planted + "\n" + bodies[name]))
        return found


_active: Canary | None = None


def canary() -> Canary:
    """Mint a secret, store it, and start the captures.

    Call ``close`` or use the return value as a context manager. ``SEVN_HOME``
    and the age-file backend must already point at a disposable home.
    """
    from sevn.config import Settings
    from sevn.paths import Paths
    from sevn.secrets.backends import open_backend

    value = secrets.token_urlsafe(32)
    name = "canary/" + secrets.token_hex(8)
    backend = open_backend(Settings.load(), Paths.from_env())
    backend.set(name, value)
    probe = Canary(value, name)
    probe.open()
    return probe


def _known(capture: str) -> str:
    if capture not in CAPTURES:
        known = ", ".join(CAPTURES)
        raise KeyError(f"unknown canary capture {capture!r}; expected one of {known}")
    return capture


def _table_text(db: Path, table: str, sql: str) -> str:
    if not db.is_file():
        return ""
    with sqlite3.connect(db) as connection:
        present = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        if present is None:
            return ""
        rows = connection.execute(sql).fetchall()
    return repr(rows)
