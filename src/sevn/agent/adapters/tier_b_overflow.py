"""Tier-B overflow capability — provider-neutral tool output size management (D6).

Intercepts tool results via ``after_tool_execute`` and **returns full content to the model**
(operator directive, transcript-review-2026-06-22): the LLM never faces truncation notices or
spill pointers for normal session / log / file reads. Two cases:

- **full inline** (≤ ``spill_threshold``, default 1 MiB): the result is returned in full. A
  CodeMode ``ToolReturn`` wrapper is unwrapped first so its repr never leaks to the model.
- **spill safety valve** (> ``spill_threshold``): only pathological results exceeding the inline
  budget are written to a session-scoped temp file (full data captured by code) and surfaced as a
  graceful head+tail note to avoid blowing the context window. Raise ``spill_threshold`` to
  disable the valve entirely.

The ``read_tool_result`` native tool is still registered so the model can page through a
safety-valve spill on demand, but it is not needed for normal-sized results.

Module: sevn.agent.adapters.tier_b_overflow
Depends: pydantic_ai.capabilities.abstract, sevn.agent.executors.b_types

Exports:
    OverflowingToolOutput — capability subclass applying size bands.
    build_overflow_capability — factory with default thresholds.

Examples:
    >>> cap = build_overflow_capability()
    >>> cap.__class__.__name__
    'OverflowingToolOutput'
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger
from pydantic_ai.capabilities.abstract import AbstractCapability
from pydantic_ai.messages import ToolReturn
from pydantic_ai.tools import AgentDepsT, RunContext

if TYPE_CHECKING:
    from pydantic_ai.messages import ToolCallPart
    from pydantic_ai.tools import ToolDefinition
    from pydantic_ai.toolsets import AbstractToolset

OVERFLOW_TRUNCATE_FLOOR: int = 4096
"""Tool output below this byte count passes through unchanged (cheap path)."""

OVERFLOW_SPILL_THRESHOLD: int = 1_048_576
"""Inline ceiling: results up to this size are returned to the model **in full** (the operator
directive — the LLM never faces truncation or spill pointers for normal session / log / file
reads). Only pathological results above this (1 MiB) hit the disk-spill safety valve, which
still captures the full content and surfaces a graceful head+tail note. Raise to disable the
valve entirely."""


def _unwrap_tool_return(result: object) -> tuple[Any, bool]:
    """Extract the model-visible value from a pydantic-ai ``ToolReturn`` wrapper.

    CodeMode (``run_code``) returns a ``ToolReturn(return_value=…, metadata=…)``; without
    unwrapping, size-banding and spill serialization operate on the object repr
    (``"ToolReturn(return_value='…')"``) instead of the real content, corrupting what the model
    sees (transcript-review-2026-06-22).

    Args:
        result (object): Raw tool return value (possibly a ``ToolReturn``).

    Returns:
        tuple[Any, bool]: ``(inner_value, was_tool_return)``.

    Examples:
        >>> _unwrap_tool_return("hi")
        ('hi', False)
        >>> from pydantic_ai.messages import ToolReturn
        >>> _unwrap_tool_return(ToolReturn(return_value='{"ok":true}'))
        ('{"ok":true}', True)
    """
    if isinstance(result, ToolReturn):
        return result.return_value, True
    return result, False


_SPILL_NOTICE = "\n\n[… {total} bytes exceeded the inline budget; head+tail shown above. Full content captured on disk — call read_tool_result(id='{spill_id}') to page the rest.]"

_SPILL_HEAD_BYTES: int = 4096
"""Leading bytes shown inline for a safety-valve spill."""

_SPILL_TAIL_BYTES: int = 2048
"""Trailing bytes shown inline for a safety-valve spill."""


def _byte_len(value: Any) -> int:
    """Estimate byte length of a tool result for band classification.

    Args:
        value (Any): Tool return value (str, dict, or other serializable).

    Returns:
        int: Byte length of the string or JSON representation.

    Examples:
        >>> _byte_len("hello")
        5
        >>> _byte_len({"a": 1})
        8
    """
    if isinstance(value, str):
        return len(value.encode("utf-8", errors="replace"))
    if isinstance(value, bytes):
        return len(value)
    try:
        return len(json.dumps(value, default=str).encode("utf-8", errors="replace"))
    except (TypeError, ValueError):
        return len(str(value).encode("utf-8", errors="replace"))


def _serialize_for_spill(value: Any) -> str:
    """Serialize a tool result to string for disk spill.

    Args:
        value (Any): Tool return value.

    Returns:
        str: String representation suitable for disk storage.

    Examples:
        >>> _serialize_for_spill("hello")
        'hello'
        >>> _serialize_for_spill({"a": 1})
        '{\\n  "a": 1\\n}'
    """
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    try:
        return json.dumps(value, indent=2, default=str)
    except (TypeError, ValueError):
        return str(value)


@dataclass
class _SpillEntry:
    """A single spilled tool output on disk."""

    path: Path
    total_bytes: int
    tool_name: str
    tool_call_id: str


@dataclass
class OverflowingToolOutput(AbstractCapability[AgentDepsT]):
    """Provider-neutral tool output overflow management (D6).

    Returns full tool content to the model via ``after_tool_execute`` (the LLM never faces
    truncation or spill pointers for normal results); only results above ``spill_threshold``
    hit the disk-spill safety valve. Unwraps CodeMode ``ToolReturn`` wrappers first.

    Args:
        truncate_floor (int): Retained for back-compat; no longer truncates (kept so existing
            callers/config keep working). Results are inlined in full up to ``spill_threshold``.
        spill_threshold (int): Inline ceiling — results > this hit the spill safety valve.
            Default 1 MiB.
        spill_dir (Path | None): Directory for spill files. Defaults to a session-scoped
            temp directory created on first spill.

    Examples:
        >>> cap = OverflowingToolOutput()
        >>> cap.spill_threshold
        1048576
    """

    truncate_floor: int = OVERFLOW_TRUNCATE_FLOOR
    spill_threshold: int = OVERFLOW_SPILL_THRESHOLD
    spill_dir: Path | None = None
    _spills: dict[str, _SpillEntry] = field(default_factory=dict, repr=False)
    _spill_counter: int = field(default=0, repr=False)

    def _ensure_spill_dir(self) -> Path:
        """Create or return the spill directory.

        Returns:
            Path: Directory for spill files.

        Examples:
            >>> cap = OverflowingToolOutput(spill_dir=Path("/tmp/test_spill"))
            >>> cap._ensure_spill_dir() == Path("/tmp/test_spill")
            True
        """
        if self.spill_dir is None:
            self.spill_dir = Path(tempfile.mkdtemp(prefix="sevn_overflow_"))
        self.spill_dir.mkdir(parents=True, exist_ok=True)
        return self.spill_dir

    def _next_spill_id(self) -> str:
        """Generate a monotonic spill identifier.

        Returns:
            str: Unique spill id like ``spill_0``, ``spill_1``, etc.

        Examples:
            >>> cap = OverflowingToolOutput()
            >>> cap._next_spill_id()
            'spill_0'
            >>> cap._next_spill_id()
            'spill_1'
        """
        sid = f"spill_{self._spill_counter}"
        self._spill_counter += 1
        return sid

    async def after_tool_execute(
        self,
        ctx: RunContext[AgentDepsT],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: dict[str, Any],
        result: Any,
    ) -> Any:
        """Apply size-band overflow to tool results.

        Args:
            ctx (RunContext): Agent run context.
            call (ToolCallPart): The tool call that produced this result.
            tool_def (ToolDefinition): Definition of the called tool.
            args (dict[str, Any]): Validated arguments that were passed.
            result (Any): Raw tool return value.

        Returns:
            Any: Original, truncated, or spill-pointer result.

        Examples:
            >>> import asyncio
            >>> from unittest.mock import MagicMock
            >>> cap = OverflowingToolOutput(truncate_floor=10, spill_threshold=50)
            >>> ctx = MagicMock()
            >>> call = MagicMock(); call.tool_name = "test"; call.tool_call_id = "c1"
            >>> td = MagicMock()
            >>> # Small result passes through
            >>> asyncio.run(cap.after_tool_execute(ctx, call=call, tool_def=td, args={}, result="hi"))
            'hi'
        """
        if call.tool_name == "read_tool_result":
            return result

        # Unwrap CodeMode ``ToolReturn`` so banding + the model see real content, not the repr.
        content, was_tool_return = _unwrap_tool_return(result)
        size = _byte_len(content)
        if size <= self.spill_threshold:
            # Full content to the model — the LLM never faces truncation or a spill pointer for
            # normal results (operator directive). Return the unwrapped value for ToolReturn so
            # the repr never leaks; otherwise return the original object untouched.
            return content if was_tool_return else result

        # Safety valve only (size beyond the 1 MiB inline budget): capture the full content to
        # disk and return a graceful head+tail note so context is not blown. The full data is
        # still retrievable via ``read_tool_result``.
        return self._spill(content, size, call.tool_name, call.tool_call_id or "unknown")

    def _spill(self, result: Any, size: int, tool_name: str, tool_call_id: str) -> str:
        """Spill a large result to disk and return a pointer.

        Args:
            result (Any): Tool return value.
            size (int): Byte length of the result.
            tool_name (str): Name of the tool that produced the result.
            tool_call_id (str): Call id for correlation.

        Returns:
            str: Head+tail preview plus a note; full content is captured on disk and
            paginable via ``read_tool_result``.

        Examples:
            >>> import tempfile
            >>> cap = OverflowingToolOutput(
            ...     truncate_floor=5, spill_threshold=10,
            ...     spill_dir=Path(tempfile.mkdtemp()),
            ... )
            >>> out = cap._spill("x" * 100, 100, "glob", "c1")
            >>> "read_tool_result" in out
            True
        """
        text = _serialize_for_spill(result)
        spill_id = self._next_spill_id()
        spill_dir = self._ensure_spill_dir()
        spill_path = spill_dir / f"{spill_id}.txt"
        spill_path.write_text(text, encoding="utf-8")
        self._spills[spill_id] = _SpillEntry(
            path=spill_path,
            total_bytes=size,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
        )
        logger.debug(
            "overflow.spill tool={} size={} spill_id={} path={}",
            tool_name,
            size,
            spill_id,
            spill_path,
        )
        head = text[:_SPILL_HEAD_BYTES]
        tail = (
            text[-_SPILL_TAIL_BYTES:] if len(text) > _SPILL_HEAD_BYTES + _SPILL_TAIL_BYTES else ""
        )
        preview = f"{head}\n…\n{tail}" if tail else head
        return preview + _SPILL_NOTICE.format(total=size, spill_id=spill_id)

    def read_spill(self, spill_id: str, *, offset: int = 0, limit: int = 4096) -> str:
        """Read a slice of a spilled tool output.

        Args:
            spill_id (str): Identifier returned in the spill/truncation notice.
            offset (int): Byte offset to start reading from.
            limit (int): Maximum bytes to return.

        Returns:
            str: Content slice, or an error message if the spill id is unknown.

        Examples:
            >>> import tempfile
            >>> cap = OverflowingToolOutput(
            ...     truncate_floor=5, spill_threshold=10,
            ...     spill_dir=Path(tempfile.mkdtemp()),
            ... )
            >>> _ = cap._spill("hello world content", 19, "test", "c1")
            >>> "hello" in cap.read_spill("spill_0", offset=0, limit=5)
            True
        """
        entry = self._spills.get(spill_id)
        if entry is None:
            return (
                f"[error: unknown spill id '{spill_id}'. Available: {sorted(self._spills.keys())}]"
            )
        if not entry.path.exists():
            return f"[error: spill file for '{spill_id}' no longer exists on disk]"
        content = entry.path.read_text(encoding="utf-8")
        slice_content = content[offset : offset + limit]
        remaining = max(0, len(content) - offset - limit)
        header = f"[spill '{spill_id}': showing bytes {offset}-{offset + len(slice_content)} of {entry.total_bytes} total"
        if remaining > 0:
            header += f"; {remaining} bytes remain"
        header += "]\n"
        return header + slice_content

    def get_toolset(self) -> AbstractToolset[AgentDepsT] | None:
        """Register the ``read_tool_result`` function tool via a toolset.

        Returns:
            AbstractToolset | None: Toolset containing the read-back tool.

        Examples:
            >>> cap = OverflowingToolOutput()
            >>> ts = cap.get_toolset()
            >>> ts is not None
            True
        """
        from pydantic_ai.tools import Tool
        from pydantic_ai.toolsets.function import FunctionToolset

        async def read_tool_result(
            ctx: RunContext[AgentDepsT],
            id: str,
            offset: int = 0,
            limit: int = 4096,
        ) -> str:
            """Read a slice of a previously spilled tool output.

            When a tool's output exceeds the context-window budget, it is spilled to
            disk and a pointer is returned. Use this tool to retrieve slices of that
            output on demand.

            Args:
                ctx: Run context (injected by pydantic-ai).
                id: The spill identifier from the overflow notice (e.g. 'spill_0').
                offset: Byte offset to start reading from. Default 0.
                limit: Maximum bytes to return per call. Default 4096.

            Returns:
                The requested content slice with metadata header.
            """
            return self.read_spill(id, offset=offset, limit=limit)

        tool = Tool(read_tool_result, takes_ctx=True, name="read_tool_result")
        return FunctionToolset([tool])

    def cleanup(self) -> None:
        """Remove spill files from disk (best-effort).

        Examples:
            >>> import tempfile
            >>> cap = OverflowingToolOutput(spill_dir=Path(tempfile.mkdtemp()))
            >>> cap.cleanup()  # no-op when no spills exist
        """
        import contextlib

        for entry in self._spills.values():
            with contextlib.suppress(OSError):
                entry.path.unlink(missing_ok=True)
        self._spills.clear()


def build_overflow_capability(
    *,
    truncate_floor: int = OVERFLOW_TRUNCATE_FLOOR,
    spill_threshold: int = OVERFLOW_SPILL_THRESHOLD,
    spill_dir: Path | None = None,
) -> AbstractCapability[Any]:
    """Build the tier-B overflow capability with configurable thresholds (D6).

    Args:
        truncate_floor (int): Results ≤ this pass through unchanged. Default 4096.
        spill_threshold (int): Results > this spill to disk. Default 32768.
        spill_dir (Path | None): Optional explicit spill directory.

    Returns:
        AbstractCapability: ``OverflowingToolOutput`` instance.

    Examples:
        >>> cap = build_overflow_capability(truncate_floor=1024, spill_threshold=8192)
        >>> cap.truncate_floor
        1024
    """
    return OverflowingToolOutput(
        truncate_floor=truncate_floor,
        spill_threshold=spill_threshold,
        spill_dir=spill_dir,
    )


__all__ = [
    "OVERFLOW_SPILL_THRESHOLD",
    "OVERFLOW_TRUNCATE_FLOOR",
    "OverflowingToolOutput",
    "build_overflow_capability",
]
