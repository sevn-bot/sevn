"""Batch F W27 RED: ``sevn acp`` stdio handshake (#72) → W31."""

from __future__ import annotations

import json
from typing import Any

from typer.testing import CliRunner

from sevn.cli.app import app


def test_sevn_acp_subcommand_is_registered() -> None:
    """``sevn acp --help`` exposes the ACP runtime entrypoint."""
    runner = CliRunner()
    result = runner.invoke(app, ["acp", "--help"], env={"NO_COLOR": "1"})
    assert result.exit_code == 0
    assert "acp" in result.stdout.lower()


def test_acp_stdio_prompt_returns_end_turn_stop_reason() -> None:
    """ACP runtime speaks JSON-RPC over stdio and returns ``end_turn`` for a prompt."""
    from sevn.acp.runtime import AcpStopReason, run_acp_stdio_session

    frames: list[dict[str, Any]] = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "1.0"}},
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "session/prompt",
            "params": {"sessionId": "s1", "prompt": "ping"},
        },
    ]
    inbound = "\n".join(json.dumps(f) for f in frames) + "\n"
    outbound = run_acp_stdio_session(stdin_text=inbound, workspace_config={})
    lines = [ln for ln in outbound.strip().splitlines() if ln.strip()]
    assert lines, "ACP runtime must write at least one JSON line"
    last = json.loads(lines[-1])
    assert last.get("result", {}).get("stopReason") in {
        AcpStopReason.END_TURN.value,
        "end_turn",
    }


def test_acp_stdio_cancelled_stop_reason() -> None:
    """ACP runtime maps operator cancel to ``cancelled`` stop reason."""
    from sevn.acp.runtime import AcpStopReason, run_acp_stdio_session

    frames = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "session/cancel", "params": {"sessionId": "s1"}},
    ]
    inbound = "\n".join(json.dumps(f) for f in frames) + "\n"
    outbound = run_acp_stdio_session(stdin_text=inbound, workspace_config={})
    parsed = [json.loads(ln) for ln in outbound.strip().splitlines() if ln.strip()]
    stop_reasons = [
        msg.get("result", {}).get("stopReason")
        for msg in parsed
        if isinstance(msg.get("result"), dict)
    ]
    assert AcpStopReason.CANCELLED.value in stop_reasons or "cancelled" in stop_reasons
