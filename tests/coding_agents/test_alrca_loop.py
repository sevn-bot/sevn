"""ALRCA loop and LAP client tests (CA3-CA6)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from sevn.coding_agents.alrca.goal import GoalStatus, new_goal
from sevn.coding_agents.alrca.loop_worker import run_alrca_loop
from sevn.coding_agents.executors import StubExecutor
from sevn.integrations.litellm_lap.client import LitellmLapClient


def test_alrca_loop_completes_with_passing_verifier(tmp_path: Path) -> None:
    goal = new_goal(agent_id="agent-1", description="fix tests", max_turns=2)

    async def _run() -> None:
        result = await run_alrca_loop(
            goal,
            executor=StubExecutor(output="ok"),
            verifier_specs=["script:true"],
            workspace_path=tmp_path,
        )
        assert result.status == GoalStatus.complete

    asyncio.run(_run())


def test_lap_client_send_message_echo() -> None:
    client = LitellmLapClient(base_url="http://localhost:4000")
    out = asyncio.run(client.send_message(session_id="s1", message="ping"))
    assert out["session_id"] == "s1"
    assert "ping" in out["reply"]
