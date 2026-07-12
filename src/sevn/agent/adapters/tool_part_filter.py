"""Shared helper for filtering XML-recovered ``ToolCallPart`` entries at LLM boundaries.

Used by both the triager (structured-output guard) and tier-B (turn-allowlist guard)
to prevent unknown-to-this-turn tool names from reaching the provider as ``tool_use``
blocks, which the Anthropic wire rejects with HTTP 400.

Module: sevn.agent.adapters.tool_part_filter
Depends: dataclasses, loguru, pydantic_ai.messages

Exports:
    MutableToolAllowlist — per-turn allowlist with diagnostic widening and ``grant_load_tool``.
    filter_tool_call_parts — drop ``ToolCallPart`` entries not in the allowlist.

Examples:
    >>> from pydantic_ai.messages import TextPart, ToolCallPart
    >>> parts = [TextPart(content="hi"), ToolCallPart(tool_name="load_skill", args="{}", tool_call_id="1")]
    >>> kept = filter_tool_call_parts(parts, allowed_tool_names=frozenset({"read"}), log_prefix="test")
    >>> [type(p).__name__ for p in kept]
    ['TextPart']
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Callable

from loguru import logger
from pydantic_ai.messages import ModelResponsePart, ToolCallPart

DIAGNOSTIC_RECOVERY_TOOLS: Final[frozenset[str]] = frozenset({"process", "read", "list_dir"})
FILE_PIPELINE_TOOL_IDS: Final[tuple[str, ...]] = (
    "glob",
    "search_in_file",
    "find_file",
    "file_info",
    "get_page_content",
    "terminal_run",
    "sandbox_exec",
)
RECOVERY_WIDEN_FAILURE_THRESHOLD: Final[int] = 2


@dataclass
class MutableToolAllowlist:
    """Per-turn tool allowlist that can widen after repeated scoped-tool failures."""

    base: frozenset[str]
    registry_names: frozenset[str] = field(default_factory=frozenset)
    extra: set[str] = field(default_factory=set)
    load_granted: set[str] = field(default_factory=set)
    codemode_blocks_web_autogrants: bool = False

    @property
    def effective(self) -> frozenset[str]:
        """Return the union of the base triager allowlist and widened recovery tools.

        Returns:
            frozenset[str]: Tool names permitted this turn.

        Examples:
            >>> allow = MutableToolAllowlist(base=frozenset({"read"}))
            >>> allow.effective == frozenset({"read"})
            True
        """
        return self.base | frozenset(self.extra)

    def widen_diagnostics(self) -> None:
        """Add diagnostic recovery tools that exist in the registry.

        Examples:
            >>> allow = MutableToolAllowlist(
            ...     base=frozenset({"run_skill_script"}),
            ...     registry_names=frozenset({"read", "process"}),
            ... )
            >>> allow.widen_diagnostics()
            >>> "read" in allow.effective
            True
        """
        names = self.registry_names or self.base
        for tool_name in DIAGNOSTIC_RECOVERY_TOOLS:
            if tool_name in names:
                self.extra.add(tool_name)

    def grant_registry_tool(self, tool_name: str) -> bool:
        """Auto-grant a registry-valid tool on first recovered call (P3).

        Args:
            tool_name (str): Tool the model attempted to call.

        Returns:
            bool: ``True`` when ``tool_name`` exists in ``registry_names`` and was added
            to ``extra``.

        Examples:
            >>> allow = MutableToolAllowlist(
            ...     base=frozenset({"read"}),
            ...     registry_names=frozenset({"read", "terminal_run"}),
            ... )
            >>> allow.grant_registry_tool("terminal_run")
            True
            >>> "terminal_run" in allow.effective
            True
            >>> allow.grant_registry_tool("missing")
            False
        """
        names = self.registry_names or self.base
        if tool_name not in names:
            return False
        if self.codemode_blocks_web_autogrants:
            from sevn.agent.adapters.tier_b_capabilities import CODEMODE_LOCAL_WEB_TOOL_NAMES

            if tool_name in CODEMODE_LOCAL_WEB_TOOL_NAMES:
                return False
        self.extra.add(tool_name)
        return True

    def grant_load_tool(self, tool_name: str) -> bool:
        """Explicitly grant a tool after successful ``load_tool`` dispatch (D11 / W7).

        Bypasses ``codemode_blocks_web_autogrants`` — loaded tools are operator-provisioned
        for schema visibility and stream recovery.  Records the name in ``load_granted`` so
        CodeMode steer paths can distinguish explicit loads from P3 auto-grants.

        Args:
            tool_name (str): Registry tool name passed to ``load_tool(name=…)``.

        Returns:
            bool: ``True`` when ``tool_name`` exists in ``registry_names`` and was added
            to ``extra``.

        Examples:
            >>> allow = MutableToolAllowlist(
            ...     base=frozenset({"load_tool"}),
            ...     registry_names=frozenset({"load_tool", "get_page_content"}),
            ...     codemode_blocks_web_autogrants=True,
            ... )
            >>> allow.grant_load_tool("get_page_content")
            True
            >>> "get_page_content" in allow.effective
            True
            >>> "get_page_content" in allow.load_granted
            True
            >>> allow.grant_registry_tool("get_page_content")
            False
        """
        names = self.registry_names or self.base
        if tool_name not in names:
            return False
        self.extra.add(tool_name)
        self.load_granted.add(tool_name)
        return True


def filter_tool_call_parts(
    parts: list[ModelResponsePart],
    *,
    allowed_tool_names: frozenset[str] | MutableToolAllowlist,
    log_prefix: str = "agent",
    on_dropped: Callable[[str], None] | None = None,
    on_granted: Callable[[str], None] | None = None,
) -> list[ModelResponsePart]:
    """Filter ``ToolCallPart`` entries against the per-turn allowlist (P3 auto-grant).

    Registry-valid tools that were not triager-provisioned are auto-granted on first
    recovered call (added to :class:`MutableToolAllowlist` ``extra``) instead of
    silently dropped.  Successful ``load_tool`` grants via
    :meth:`MutableToolAllowlist.grant_load_tool` must run **before** stream recovery
    so explicitly loaded names are already in ``extra``. Tools absent from the registry
    invoke ``on_dropped`` so the harness can steer with a ``TOOL_NOT_PROVISIONED`` hint.

    Prevents XML-recovered tool calls for tools that were not registered in this
    turn from reaching the provider as ``tool_use`` blocks — the Anthropic wire
    rejects unknown-tool references with HTTP 400.

    Args:
        parts (list[ModelResponsePart]): Post-conversion assistant parts.
        allowed_tool_names (frozenset[str] | MutableToolAllowlist): Tool names the
            pydantic-ai agent may dispatch this turn.
        log_prefix (str): Log message prefix identifying the caller site
            (e.g. ``"triager"`` or ``"tier_b"``).
        on_dropped (Callable[[str], None] | None, optional): Callback invoked with
            each dropped tool name. Defaults to ``None``.
        on_granted (Callable[[str], None] | None, optional): Callback invoked when a
            registry-valid tool is auto-granted (e.g. add to ``loaded_tools``).
            Defaults to ``None``.

    Returns:
        list[ModelResponsePart]: Parts with unknown ``ToolCallPart`` entries removed.

    Examples:
        >>> from pydantic_ai.messages import TextPart, ToolCallPart
        >>> kept = filter_tool_call_parts(
        ...     [TextPart(content="ok"), ToolCallPart(tool_name="find_file", args="{}", tool_call_id="x")],
        ...     allowed_tool_names=frozenset({"read"}),
        ... )
        >>> [type(p).__name__ for p in kept]
        ['TextPart']
        >>> allow = MutableToolAllowlist(
        ...     base=frozenset({"read"}),
        ...     registry_names=frozenset({"read", "terminal_run"}),
        ... )
        >>> granted: list[str] = []
        >>> kept2 = filter_tool_call_parts(
        ...     [ToolCallPart(tool_name="terminal_run", args="{}", tool_call_id="y")],
        ...     allowed_tool_names=allow,
        ...     on_granted=granted.append,
        ... )
        >>> [p.tool_name for p in kept2]  # type: ignore[attr-defined]
        ['terminal_run']
        >>> granted
        ['terminal_run']
    """
    if isinstance(allowed_tool_names, MutableToolAllowlist):
        allowed = allowed_tool_names.effective
        allowlist = allowed_tool_names
    else:
        allowed = allowed_tool_names
        allowlist = None
    filtered: list[ModelResponsePart] = []
    for part in parts:
        if isinstance(part, ToolCallPart) and part.tool_name not in allowed:
            if allowlist is not None and allowlist.grant_registry_tool(part.tool_name):
                logger.debug(
                    "{} auto-granted registry tool name={}",
                    log_prefix,
                    part.tool_name,
                )
                if on_granted is not None:
                    on_granted(part.tool_name)
                filtered.append(part)
                continue
            logger.debug(
                "{} dropping unknown recovered tool call name={}",
                log_prefix,
                part.tool_name,
            )
            if on_dropped is not None:
                on_dropped(part.tool_name)
            continue
        filtered.append(part)
    return filtered


__all__ = [
    "DIAGNOSTIC_RECOVERY_TOOLS",
    "FILE_PIPELINE_TOOL_IDS",
    "RECOVERY_WIDEN_FAILURE_THRESHOLD",
    "MutableToolAllowlist",
    "filter_tool_call_parts",
]
