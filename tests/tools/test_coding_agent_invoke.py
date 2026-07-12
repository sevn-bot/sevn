"""coding_agent_invoke tool tests."""

from __future__ import annotations

import asyncio

from sevn.config.workspace_config import WorkspaceConfig
from sevn.tools.coding_agent_invoke import coding_agent_invoke


def test_invoke_unknown_agent_returns_error() -> None:
    out = asyncio.run(
        coding_agent_invoke(
            agent_id="no-such-agent",
            message="hi",
            workspace=WorkspaceConfig.minimal(),
        )
    )
    assert out["ok"] is False
