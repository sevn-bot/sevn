"""Agent Client Protocol (ACP) runtime bridge for sevn bots (#72, W31).

Module: sevn.acp
Depends: sevn.acp.runtime, sevn.acp.turn_bridge

Exports:
    AcpStopReason — prompt lifecycle stop reasons for ACP clients.
    run_acp_stdio_session — NDJSON JSON-RPC stdio session loop.
"""

from __future__ import annotations

from sevn.acp.runtime import AcpStopReason, run_acp_stdio_session

__all__ = ["AcpStopReason", "run_acp_stdio_session"]
