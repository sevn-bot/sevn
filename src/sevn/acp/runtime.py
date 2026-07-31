"""ACP stdio JSON-RPC session loop (#72, W31.2).

Module: sevn.acp.runtime
Depends: json, enum, sevn.acp.turn_bridge

Exports:
    AcpStopReason — ``end_turn`` / ``cancelled`` stop reasons.
    run_acp_stdio_session — process NDJSON frames and return outbound text.
"""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Any, TextIO


class AcpStopReason(StrEnum):
    """ACP prompt lifecycle stop reasons returned to Buzz / ACP clients."""

    END_TURN = "end_turn"
    CANCELLED = "cancelled"


def _write_line(stream: TextIO, payload: dict[str, Any]) -> None:
    """Write one NDJSON line to ``stream``.

    Args:
        stream (TextIO): Outbound stdio stream.
        payload (dict[str, Any]): JSON-RPC object.

    Returns:
        None

    Examples:
        >>> import io
        >>> buf = io.StringIO()
        >>> _write_line(buf, {"jsonrpc": "2.0", "id": 1, "result": {}})
        >>> buf.getvalue().startswith("{")
        True
    """
    stream.write(json.dumps(payload, separators=(",", ":")) + "\n")
    stream.flush()


def _session_update(session_id: str, *, text: str) -> dict[str, Any]:
    """Build one ``session/update`` notification payload.

    Args:
        session_id (str): Active ACP session id.
        text (str): Assistant text chunk.

    Returns:
        dict[str, Any]: JSON-RPC notification object.

    Examples:
        >>> _session_update("s1", text="hi")["method"]
        'session/update'
    """
    return {
        "jsonrpc": "2.0",
        "method": "session/update",
        "params": {
            "sessionId": session_id,
            "update": {
                "kind": "message",
                "content": {"type": "text", "text": text},
            },
        },
    }


def _prompt_text(params: dict[str, Any]) -> str:
    """Extract user prompt text from ACP ``session/prompt`` params.

    Args:
        params (dict[str, Any]): JSON-RPC params object.

    Returns:
        str: Normalised prompt text (possibly empty).

    Examples:
        >>> _prompt_text({"prompt": " ping "})
        'ping'
    """
    raw_prompt = params.get("prompt")
    if isinstance(raw_prompt, str) and raw_prompt.strip():
        return raw_prompt.strip()
    content = params.get("content")
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text" and isinstance(block.get("text"), str):
                parts.append(block["text"])
        joined = "\n".join(p for p in parts if p.strip())
        if joined.strip():
            return joined.strip()
    return ""


def run_acp_stdio_session(
    *,
    stdin_text: str | None = None,
    workspace_config: dict[str, Any] | None = None,
    stdout: TextIO | None = None,
) -> str:
    """Run one ACP stdio session over newline-delimited JSON-RPC.

    Args:
        stdin_text (str | None): Inbound NDJSON (defaults to ``sys.stdin`` when ``None`` and TTY).
        workspace_config (dict[str, Any] | None): Optional workspace snapshot for turn bridging.
        stdout (TextIO | None): Outbound stream (defaults to ``sys.stdout``).

    Returns:
        str: Concatenated outbound NDJSON lines written during the session.

    Examples:
        >>> out = run_acp_stdio_session(
        ...     stdin_text='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}\\n',
        ...     workspace_config={},
        ... )
        >>> "protocolVersion" in out
        True
    """
    import sys

    from sevn.acp.turn_bridge import run_acp_prompt_turn

    out_stream = stdout or sys.stdout
    inbound = stdin_text if stdin_text is not None else sys.stdin.read()
    ws_cfg = workspace_config if workspace_config is not None else {}
    lines_out: list[str] = []

    def emit(payload: dict[str, Any]) -> None:
        line = json.dumps(payload, separators=(",", ":"))
        lines_out.append(line)
        _write_line(out_stream, payload)

    for raw_line in inbound.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        try:
            frame = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(frame, dict):
            continue
        method = frame.get("method")
        req_id = frame.get("id")
        params_raw = frame.get("params")
        params: dict[str, Any] = params_raw if isinstance(params_raw, dict) else {}

        if method == "initialize":
            emit(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "protocolVersion": str(params.get("protocolVersion") or "1.0"),
                        "agentInfo": {"name": "sevn", "title": "sevn.bot ACP runtime"},
                    },
                }
            )
            continue

        if method == "session/prompt":
            session_id = str(params.get("sessionId") or "default")
            prompt = _prompt_text(params)
            reply = run_acp_prompt_turn(session_id, prompt, ws_cfg)
            if reply:
                emit(_session_update(session_id, text=reply))
            emit(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"stopReason": AcpStopReason.END_TURN.value, "sessionId": session_id},
                }
            )
            continue

        if method == "session/cancel":
            session_id = str(params.get("sessionId") or "default")
            emit(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "stopReason": AcpStopReason.CANCELLED.value,
                        "sessionId": session_id,
                    },
                }
            )
            continue

        if req_id is not None:
            emit(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"method not found: {method}"},
                }
            )

    return "\n".join(lines_out) + ("\n" if lines_out else "")


__all__ = ["AcpStopReason", "run_acp_stdio_session"]
