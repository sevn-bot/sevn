"""Native transcript mapping (D4).

``map_native_event(runtime, native) -> RuntimeEvent`` where ``kind`` is a D4 kind
or ``"ignored"``. Ignored events set ``native_type``, and that value is a member of
``IGNORED_NATIVE[runtime]``. Each ``fixtures/<runtime>/*.jsonl`` line is one native
object. Claude, Codex, and OpenCode transcripts are unmarked after W3.R.
"""

from __future__ import annotations

import json
from collections.abc import Collection, Mapping
from pathlib import Path

import pytest

SPIKE_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = SPIKE_ROOT / "fixtures"

EVENT_KINDS = frozenset(
    {
        "text_delta",
        "thinking_delta",
        "tool_call_started",
        "tool_call_finished",
        "permission_request",
        "turn_finished",
        "error",
        "session_bound",
    }
)


def _transcripts() -> list[object]:
    params: list[object] = []
    for runtime in ("claude", "codex", "opencode"):
        root = FIXTURES / runtime
        found = sorted(root.glob("*.jsonl")) if root.is_dir() else []
        # Stand-in so the test still runs, and fails, before that wave records transcripts.
        paths = found or [root / "_pending.jsonl"]
        for path in paths:
            params.append(pytest.param(runtime, path, id=f"{runtime}:{path.name}"))
    return params


def _load_mapping() -> tuple[object, object, type[object]]:
    try:
        from spike_rt.events import (  # type: ignore[reportMissingImports]
            IGNORED_NATIVE,
            RuntimeEvent,
            map_native_event,
        )
    except ImportError as exc:
        pytest.fail(f"missing spike_rt.events mapping API ({exc})")
    assert isinstance(RuntimeEvent, type)
    return IGNORED_NATIVE, map_native_event, RuntimeEvent


def _events(path: Path) -> list[object]:
    relative = path.relative_to(SPIKE_ROOT).as_posix()
    assert path.is_file(), f"missing fixture transcript {relative}"
    natives: list[object] = []
    for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            native = json.loads(line)
        except json.JSONDecodeError as exc:
            pytest.fail(f"{relative}:{index} is not JSON ({exc})")
        assert isinstance(native, dict), f"{relative}:{index} is not an object"
        natives.append(native)
    assert natives, f"{relative} has no events"
    return natives


def _map_all(runtime: str, natives: list[object]) -> list[object]:
    ignored_native, map_native_event, runtime_event = _load_mapping()
    mapped_events: list[object] = []
    for native in natives:
        try:
            mapped = map_native_event(runtime, native)  # type: ignore[operator]
        except KeyError as exc:
            pytest.fail(f"map_native_event raised KeyError: {exc}")
        assert isinstance(mapped, runtime_event)
        _assert_mapped(runtime, mapped, ignored_native)
        mapped_events.append(mapped)
    return mapped_events


def _assert_mapped(runtime: str, event: object, ignored_native: object) -> None:
    kind = event.kind  # type: ignore[attr-defined]
    assert kind == "ignored" or kind in EVENT_KINDS
    if kind == "ignored":
        native_type = event.native_type  # type: ignore[attr-defined]
        assert isinstance(native_type, str) and native_type
        documented = _ignored_for(ignored_native, runtime)
        assert native_type in documented, f"{native_type!r} is not a documented ignored event"
        return
    if kind in {"text_delta", "thinking_delta"}:
        assert isinstance(event.text, str)  # type: ignore[attr-defined]
    elif kind == "tool_call_started":
        assert isinstance(event.name, str) and event.name  # type: ignore[attr-defined]
        assert isinstance(event.args, dict)  # type: ignore[attr-defined]
    elif kind == "tool_call_finished":
        assert isinstance(event.name, str) and event.name  # type: ignore[attr-defined]
        assert isinstance(event.ok, bool)  # type: ignore[attr-defined]
    elif kind == "permission_request":
        assert isinstance(event.tool, str) and event.tool  # type: ignore[attr-defined]
        assert isinstance(event.args, dict)  # type: ignore[attr-defined]
        request_id = event.request_id  # type: ignore[attr-defined]
        assert isinstance(request_id, str) and request_id
    elif kind == "turn_finished":
        usage = event.usage  # type: ignore[attr-defined]
        assert usage is None or isinstance(usage, dict)
    elif kind == "error":
        assert isinstance(event.code, str) and event.code  # type: ignore[attr-defined]
        assert isinstance(event.message, str)  # type: ignore[attr-defined]
    elif kind == "session_bound":
        session_ref = event.session_ref  # type: ignore[attr-defined]
        assert isinstance(session_ref, str) and session_ref


def _ignored_for(ignored_native: object, runtime: str) -> Collection[object]:
    assert isinstance(ignored_native, Mapping), "IGNORED_NATIVE must be a mapping"
    documented = ignored_native.get(runtime)
    assert isinstance(documented, Collection) and not isinstance(documented, (str, bytes)), (
        f"no documented ignored list for {runtime}"
    )
    return documented


@pytest.mark.parametrize(("runtime", "transcript"), _transcripts())
def test_every_native_event_maps(runtime: str, transcript: Path) -> None:
    _load_mapping()
    _map_all(runtime, _events(transcript))


@pytest.mark.parametrize(("runtime", "transcript"), _transcripts())
def test_turn_has_session_bound_then_finished(runtime: str, transcript: Path) -> None:
    _load_mapping()
    kinds = [
        event.kind  # type: ignore[attr-defined]
        for event in _map_all(runtime, _events(transcript))
        if event.kind != "ignored"  # type: ignore[attr-defined]
    ]
    assert "session_bound" in kinds
    assert "turn_finished" in kinds
    assert kinds.index("session_bound") < kinds.index("turn_finished")
