"""Manual LLM Guard scan tool (`plan/tools-skills-full-inventory-wave-plan.md` Wave 7).

Wraps :class:`~sevn.security.llm_guard_scanner.LLMGuardScanner` for agent-initiated
prompt-injection checks. Blocked payloads are never echoed back to the model.

Module: sevn.tools.llm_guard_tool
Depends: sevn.config.workspace_config, sevn.security.llm_guard_scanner, sevn.tools.base,
    sevn.tools.context, sevn.tools.decorator

Exports:
    llm_guard_scan_tool — manual scan wrapper around ``LLMGuardScanner``.
    register_llm_guard_tool — register when the scanner subsystem is enabled.
    scanner_tool_enabled — config gate helper.
    scan_result_to_tool_payload — redaction-safe JSON payload builder.

Examples:
    >>> from sevn.config.workspace_config import WorkspaceConfig
    >>> scanner_tool_enabled(WorkspaceConfig.minimal())
    True
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from sevn.security.llm_guard_scanner import LLMGuardScanner, ScanResult, ScanVerdict
from sevn.tools.base import enveloped_failure, enveloped_success
from sevn.tools.codes import ToolResultCode
from sevn.tools.context import ToolContext
from sevn.tools.decorator import sevn_tool, tool_from_decorated

if TYPE_CHECKING:
    from sevn.config.workspace_config import WorkspaceConfig
    from sevn.tools.base import ToolExecutor

SourceHint = Literal["tool_result", "manual"]
_REGISTERED_WORKSPACE_CONFIG: WorkspaceConfig | None = None


def scanner_tool_enabled(workspace_config: WorkspaceConfig | None) -> bool:
    """Return whether ``llm_guard_scan`` should register for ``workspace_config``.

    Args:
        workspace_config (WorkspaceConfig | None): Parsed workspace config.

    Returns:
        bool: ``True`` when ``security.llmignore.enabled`` is unset or true.

    Examples:
        >>> from sevn.config.workspace_config import (
        ...     SecurityLlmignoreSubConfig,
        ...     SecurityWorkspaceConfig,
        ...     WorkspaceConfig,
        ... )
        >>> cfg = WorkspaceConfig.minimal(
        ...     security=SecurityWorkspaceConfig(
        ...         llmignore=SecurityLlmignoreSubConfig(enabled=False),
        ...     ),
        ... )
        >>> scanner_tool_enabled(cfg)
        False
    """
    if workspace_config is None:
        return True
    security = workspace_config.security
    if security is None:
        return True
    llmignore = security.llmignore
    if llmignore is None:
        return True
    return bool(llmignore.enabled)


def scan_result_to_tool_payload(result: ScanResult) -> dict[str, Any]:
    """Build a redaction-safe tool payload from ``result``.

    Blocked scans omit the inspected text per ``specs/09-security-scanner.md`` §2.3.

    Args:
        result (ScanResult): Scanner outcome.

    Returns:
        dict[str, Any]: JSON-serialisable verdict payload.

    Examples:
        >>> from sevn.security.llm_guard_scanner import BlockReason, ScanResult, ScanVerdict
        >>> payload = scan_result_to_tool_payload(
        ...     ScanResult(
        ...         verdict=ScanVerdict.block,
        ...         reasons=(BlockReason.prompt_injection,),
        ...         scores={"injection": 0.9},
        ...         provider_used="heuristic",
        ...         details={"matched": "ignore previous instructions"},
        ...     ),
        ... )
        >>> payload["verdict"]
        'block'
        >>> "matched" not in payload.get("details", {})
        True
    """
    payload: dict[str, Any] = {
        "verdict": result.verdict.value,
        "reasons": [reason.value for reason in result.reasons],
        "scores": dict(result.scores),
        "provider_used": result.provider_used,
    }
    if result.verdict == ScanVerdict.allow:
        payload["details"] = dict(result.details)
    else:
        payload["details"] = {
            key: value
            for key, value in result.details.items()
            if key not in {"matched", "text", "raw_text", "payload"}
        }
    return payload


@sevn_tool(
    name="llm_guard_scan",
    category="security",
    description="Manually scan suspect text for prompt injection and policy violations.",
    parameters={
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Suspect fragment to scan."},
            "source_hint": {
                "type": "string",
                "enum": ["tool_result", "manual"],
                "description": "Use tool_result to apply external-source scan path.",
            },
        },
        "required": ["text"],
    },
    abortable=True,
    see_also=("integration_call", "web_fetch"),
)
async def llm_guard_scan_tool(
    ctx: ToolContext,
    text: str,
    source_hint: SourceHint = "manual",
) -> str:
    """Run ``LLMGuardScanner`` on ``text`` and return a redacted verdict envelope.

    Args:
        ctx (ToolContext): Invocation context with ``workspace_path``.
        text (str): Suspect UTF-8 fragment.
        source_hint (SourceHint): ``tool_result`` selects ``scan_tool_result`` path.

    Returns:
        str: §3.1 JSON envelope string without blocked raw text.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(llm_guard_scan_tool)
        True
    """
    body = text.strip()
    if not body:
        return enveloped_failure("text must be non-empty", code=ToolResultCode.VALIDATION_ERROR)
    if source_hint not in ("tool_result", "manual"):
        return enveloped_failure(
            f"unsupported source_hint {source_hint!r}",
            code=ToolResultCode.VALIDATION_ERROR,
        )
    from sevn.config.workspace_config import WorkspaceConfig

    cfg = _REGISTERED_WORKSPACE_CONFIG or WorkspaceConfig.minimal()
    scanner = LLMGuardScanner(ctx.workspace_path, cfg)
    if source_hint == "tool_result":
        result = await scanner.scan_tool_result(
            tool_name="manual_llm_guard_scan",
            payload=body,
            run_ctx=ctx,
        )
    else:
        result = await scanner.scan_inbound(
            text=body,
            channel="manual_tool",
            user_id=ctx.session_id,
            actor_is_owner=True,
            source="manual_tool",
        )
    return enveloped_success(scan_result_to_tool_payload(result))


def register_llm_guard_tool(
    executor: ToolExecutor,
    workspace_config: WorkspaceConfig | None = None,
) -> None:
    """Register ``llm_guard_scan`` when the scanner subsystem is enabled.

    Args:
        executor (ToolExecutor): Registry under construction.
        workspace_config (WorkspaceConfig | None): Parsed workspace config gate.

    Returns:
        None

    Examples:
        >>> from sevn.config.workspace_config import (
        ...     SecurityLlmignoreSubConfig,
        ...     SecurityWorkspaceConfig,
        ...     WorkspaceConfig,
        ... )
        >>> from sevn.tools.base import ToolExecutor
        >>> from sevn.tools.llm_guard_tool import register_llm_guard_tool
        >>> exe = ToolExecutor()
        >>> register_llm_guard_tool(exe, WorkspaceConfig.minimal())
        >>> "llm_guard_scan" in {d.name for d in exe.definitions()}
        True
    """
    global _REGISTERED_WORKSPACE_CONFIG
    if not scanner_tool_enabled(workspace_config):
        return
    _REGISTERED_WORKSPACE_CONFIG = workspace_config
    executor.register(tool_from_decorated(llm_guard_scan_tool))


__all__ = [
    "llm_guard_scan_tool",
    "register_llm_guard_tool",
    "scan_result_to_tool_payload",
    "scanner_tool_enabled",
]
