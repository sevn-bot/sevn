"""Shared fixtures for open-issues sweep Batch G (W35 — voice activation / #102)."""

from __future__ import annotations

import importlib
import json
import sqlite3
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol
from unittest.mock import AsyncMock

import pytest
from starlette.testclient import TestClient

from sevn.config.workspace_config import VoiceConfig, WorkspaceConfig
from sevn.gateway.http_server import create_app
from sevn.storage.migrate import apply_migrations
from sevn.workspace.layout import WorkspaceLayout

if TYPE_CHECKING:
    from sevn.agent.tracing.sink import TraceEvent

_GATEWAY_TOKEN = "batch-g-gw-token"

# W36 contract: activation keys live under ``voice.activation.*`` — never reuse trigger keywords.
ACTIVATION_CONFIG_PREFIX = "voice.activation"
FORBIDDEN_ACTIVATION_KEY_FRAGMENTS = frozenset(
    {
        "voice_trigger_keywords",
        "trigger_keywords",
    },
)


class AudioFrameSource(Protocol):
    """Injectable mic stand-in — tests must never open real hardware."""

    async def read_frames(self) -> AsyncIterator[bytes]:
        """Yield PCM-ish frames until exhausted."""
        ...


@dataclass(frozen=True)
class FakeAudioScenario:
    """One synthetic audio timeline for privacy / hand-off tests."""

    label: str
    frames: tuple[bytes, ...]
    activation_at_frame: int | None = None


class _RecordingTraceSink:
    """Collect :class:`TraceEvent` rows without I/O (mirrors ``test_voice_duplex_w1``)."""

    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    async def emit(self, event: TraceEvent) -> None:
        self.events.append(event)

    async def flush(self) -> None:
        return

    async def close(self) -> None:
        return


class _StaticFrameSource:
    """Deterministic frame source for listener injection tests."""

    def __init__(self, frames: tuple[bytes, ...]) -> None:
        self._frames = frames
        self.opened = False

    async def read_frames(self) -> AsyncIterator[bytes]:
        self.opened = True
        for frame in self._frames:
            yield frame


def import_voice_activation_module() -> Any:
    """Lazy import of the W36 activation module — fails the test when absent."""
    try:
        return importlib.import_module("sevn.voice.activation")
    except ImportError as exc:
        pytest.fail(f"sevn.voice.activation not implemented: {exc}")


def baseline_voice_workspace(*, voice: VoiceConfig | None = None) -> WorkspaceConfig:
    """Minimal workspace with voice enabled but activation absent (today's default)."""
    return WorkspaceConfig.minimal(
        gateway={"token": _GATEWAY_TOKEN},
        voice=voice or VoiceConfig(enabled=True),
    )


def activation_enabled_workspace_doc(*, enabled: bool = True) -> dict[str, object]:
    """Raw ``sevn.json`` fragment with activation toggled on (W36 surface)."""
    return {
        "schema_version": 2,
        "workspace_root": ".",
        "gateway": {"token": _GATEWAY_TOKEN},
        "voice": {
            "enabled": True,
            "activation": {
                "enabled": enabled,
            },
        },
    }


@contextmanager
def gateway_test_client(
    tmp_path: Path,
    *,
    sevn_doc: dict[str, object] | None = None,
) -> Iterator[TestClient]:
    """Gateway ``TestClient`` with migrated SQLite — no real microphone."""
    sevn_json = tmp_path / "sevn.json"
    payload = sevn_doc or {
        "schema_version": 2,
        "workspace_root": ".",
        "gateway": {"token": _GATEWAY_TOKEN},
    }
    sevn_json.write_text(json.dumps(payload), encoding="utf-8")
    from sevn.config.workspace_config import parse_workspace_config

    cfg = parse_workspace_config(payload)
    layout = WorkspaceLayout.from_config(sevn_json, cfg)
    conn_holder: dict[str, sqlite3.Connection] = {}

    def factory() -> sqlite3.Connection:
        if "conn" not in conn_holder:
            conn = sqlite3.connect(":memory:", check_same_thread=False)
            conn.execute("PRAGMA foreign_keys=ON")
            apply_migrations(conn)
            conn_holder["conn"] = conn
        return conn_holder["conn"]

    app = create_app(workspace=cfg, layout=layout, sqlite_connection_factory=factory)
    with TestClient(app, raise_server_exceptions=False) as client:
        client.get("/health")
        yield client


@pytest.fixture
def recording_trace_sink() -> _RecordingTraceSink:
    return _RecordingTraceSink()


@pytest.fixture
def fake_audio_scenarios() -> tuple[FakeAudioScenario, ...]:
    """Ambient-only and activation timelines for privacy / hand-off tests."""
    ambient = b"\x00\x01" * 512
    utterance = b"\xff\xfe" * 256
    return (
        FakeAudioScenario("ambient_only", (ambient, ambient, ambient), activation_at_frame=None),
        FakeAudioScenario(
            "activation_then_utterance",
            (ambient, ambient, utterance, utterance),
            activation_at_frame=2,
        ),
    )


@pytest.fixture
def make_gateway_client() -> Callable[..., Iterator[TestClient]]:
    @contextmanager
    def _factory(
        tmp_path: Path,
        *,
        sevn_doc: dict[str, object] | None = None,
    ) -> Iterator[TestClient]:
        with gateway_test_client(tmp_path, sevn_doc=sevn_doc) as client:
            yield client

    return _factory


@pytest.fixture
def mock_stt_pipeline() -> AsyncMock:
    """Spy STT chain the listener must reuse post-activation (W35.7)."""
    pipe = AsyncMock()
    pipe.transcribe_or_placeholder = AsyncMock(
        return_value=("activated utterance", {"stt_provider": "whisper_cpp"}),
    )
    return pipe
