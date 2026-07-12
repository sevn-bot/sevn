"""LiteLLM LAP client mocked tests (CA5)."""

from __future__ import annotations

import asyncio

import pytest

from sevn.integrations.litellm_lap.client import LitellmLapClient


@pytest.fixture
def offline_client() -> LitellmLapClient:
    return LitellmLapClient(base_url="http://localhost:4000", offline=True)


def test_health_returns_ok(offline_client: LitellmLapClient) -> None:
    result = asyncio.run(offline_client.health())
    assert result["status"] == "ok"
    assert result.get("stub") is True


def test_list_runtimes_returns_list(offline_client: LitellmLapClient) -> None:
    result = asyncio.run(offline_client.list_runtimes())
    assert "runtimes" in result
    assert len(result["runtimes"]) >= 1
    assert result["runtimes"][0]["id"] == "stub-runtime"


def test_create_run_returns_session_id(offline_client: LitellmLapClient) -> None:
    result = asyncio.run(
        offline_client.create_run(
            runtime_id="stub-runtime",
            agent_id="agent-uuid-1",
            message="implement feature X",
        ),
    )
    assert "session_id" in result
    assert "reply" in result
    assert "implement feature X" in result["reply"]


def test_send_message_echo(offline_client: LitellmLapClient) -> None:
    result = asyncio.run(offline_client.send_message(session_id="s1", message="ping"))
    assert result["session_id"] == "s1"
    assert "ping" in result["reply"]


def test_session_id_tracked_after_create_run(offline_client: LitellmLapClient) -> None:
    asyncio.run(
        offline_client.create_run(
            runtime_id="r",
            agent_id="agent-tracked",
            message="task",
            session_id="explicit-sid",
        ),
    )
    assert offline_client.get_session_id("agent-tracked") == "explicit-sid"


def test_get_session_id_unknown_returns_none(offline_client: LitellmLapClient) -> None:
    assert offline_client.get_session_id("no-such-agent") is None


def test_send_message_via_test_alrca_loop_file() -> None:
    """Mirror the assertion in tests/coding_agents/test_alrca_loop.py CA5 block."""
    client = LitellmLapClient(base_url="http://localhost:4000", offline=True)
    out = asyncio.run(client.send_message(session_id="s1", message="ping"))
    assert out["session_id"] == "s1"
    assert "ping" in out["reply"]
