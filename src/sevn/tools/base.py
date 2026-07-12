"""Core registry types: definitions, envelopes, dispatcher (`specs/11-tools-registry.md` §2-§3).

Implements JSON result envelopes (§3.1), coarse validation, timeouts, tracing hooks,
``.llmignore`` aware spill paths, and non-abortable ``asyncio.shield`` wrapping.

Module: sevn.tools.base
Depends: sevn.agent.tracing.sink, sevn.config.defaults, sevn.tools.codes,
    sevn.tools.context, sevn.tools.validation

Exports:
    Classes:
        ToolDefinition — static catalog metadata.
        ToolCall — inbound invocation envelope from adapters.
        Tool — ABC bridging metadata and ``execute``.
        FunctionTool — concrete ``Tool`` wrapping an async or sync callable.
        BoundToolCallable — Phase-2 shim carrying decorator metadata.
        ToolExecutor — registry + ``dispatch``.
    Functions:
        enveloped_success — serialize a §3.1 success envelope.
        enveloped_failure — serialize a §3.1 failure envelope.
        maybe_spill_large_payload — spill ``data`` when responses exceed thresholds.

Examples:
    >>> from sevn.tools.base import enveloped_failure
    >>> from sevn.tools.codes import ToolResultCode
    >>> import json
    >>> json.loads(enveloped_failure("nope", code=ToolResultCode.UNKNOWN_TOOL))["ok"]
    False
"""

from __future__ import annotations

import asyncio
import inspect
import json
import uuid
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from time import time_ns
from typing import Any, Literal, cast

from sevn.agent.tracing.sink import TraceEvent
from sevn.config.defaults import TOOL_LARGE_RESULT_PREVIEW_CHARS, TOOL_LARGE_RESULT_THRESHOLD_BYTES
from sevn.plugins.hook import Block
from sevn.plugins.hook import HookContext as PHookCtx
from sevn.tools.codes import ToolResultCode
from sevn.tools.context import ToolContext
from sevn.tools.validation import (
    coerce_string_scalars_to_schema,
    validate_json_schema_subset,
)

SandboxMode = Literal["none", "subprocess", "docker"]

# Spill artifacts written by :func:`maybe_spill_large_payload` live under this
# workspace-relative segment. A ``read`` of such an artifact must be terminal —
# see :func:`_is_spill_artifact_read`.
_SPILL_DIR_SEGMENT = ".sevn/tool_results/"


@dataclass
class ToolDefinition:
    """Static metadata advertised to Triager adapters and ``load_tool``.

    The ``description`` field is the always-loaded short form (one line; ranked into the
    Triager narrowed prompt). For tools that want longer prose available on demand
    (`specs/11-tools-registry.md` §2.3), set ``long_description_file`` to a workspace-relative
    path such as ``tools/log_query.md``; ``load_tool`` resolves the file at dispatch time
    (workspace overlay first, packaged template fallback) so operators can edit per-tool
    guidance without code changes.
    """

    name: str
    category: str
    description: str
    parameters: dict[str, Any]
    requires_human: bool = False
    abortable: bool = True
    sandbox_mode: SandboxMode = "none"
    large_result: bool = False
    see_also: tuple[str, ...] = field(default_factory=tuple)
    enabled: bool = True
    capability_key: str | None = None
    long_description_file: str | None = None
    dispatch_timeout_seconds: float | None | Literal["inherit"] = "inherit"
    """Per-tool override for the ``ToolExecutor.dispatch`` deadline.

    ``"inherit"`` (default) uses ``ToolExecutor.default_timeout_seconds``. A float sets an
    explicit deadline for this tool; ``None`` disables the outer ``asyncio.wait_for`` guard
    entirely — use it for tools that enforce their own wall-clock budget internally (e.g.
    ``run_skill_script`` defers to each skill's ``max_wall_seconds``), so the generic 30 s
    default cannot pre-empt a legitimately long run and orphan its subprocess."""

    def to_dict(self) -> dict[str, Any]:
        """Return a dict suitable for nesting inside ``load_tool`` ``schema``.

        Args:
            self (ToolDefinition): Active definition.

        Returns:
            dict[str, Any]: ``name``, ``category``, ``description``, ``parameters`` snapshot.

        Examples:
            >>> d = ToolDefinition(
            ...     name="demo",
            ...     category="meta",
            ...     description="demo",
            ...     parameters={"type": "object", "properties": {}},
            ... )
            >>> d.to_dict()["name"]
            'demo'
        """
        return {
            "name": self.name,
            "category": self.category,
            "description": self.description,
            "parameters": dict(self.parameters),
            "sandbox_mode": self.sandbox_mode,
            "abortable": self.abortable,
            "requires_human": self.requires_human,
            "large_result": self.large_result,
            "see_also": list(self.see_also),
            "enabled": self.enabled,
            "long_description_file": self.long_description_file,
        }


@dataclass(frozen=True)
class ToolCall:
    """Inbound tool request (name + JSON object arguments)."""

    name: str
    arguments: dict[str, Any]


class Tool(ABC):
    """Executable surface combining metadata + async JSON envelope output."""

    @abstractmethod
    def definition(self) -> ToolDefinition:
        """Return catalog metadata.

        Returns:
            ToolDefinition: Static descriptor advertised to adapters.

        Examples:
            >>> Tool.__abstractmethods__ >= {"definition"}
            True
        """

    @abstractmethod
    async def execute(self, ctx: ToolContext, **kwargs: Any) -> str:
        """Run the tool and return §3.1 JSON string.

        Args:
            ctx (ToolContext): Runtime envelope provided by ``ToolExecutor``.
            kwargs (Any): Validated arguments forwarded from the adapter.

        Returns:
            str: §3.1 JSON envelope string.

        Examples:
            >>> Tool.__abstractmethods__ >= {"execute"}
            True
        """


async def _trace_emit(
    ctx: ToolContext,
    *,
    kind: str,
    status: str,
    attrs: dict[str, Any],
) -> None:
    """Emit one synthetic ``TraceEvent`` if ``ctx.trace`` is wired.

    Args:
        ctx (ToolContext): Runtime envelope carrying optional trace sink.
        kind (str): Event ``kind`` field (``tool.invoke``, ``tool.error`` ...).
        status (str): Event ``status`` field (``ok``, ``error``, ``cancelled``).
        attrs (dict[str, Any]): Free-form attributes; coerced via
            :func:`_json_safe_attrs`.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_trace_emit)
        True
    """
    if ctx.trace is None:
        return
    now = time_ns()
    event = TraceEvent(
        kind=kind,
        span_id=str(uuid.uuid4()),
        parent_span_id=None,
        session_id=ctx.session_id,
        turn_id=ctx.turn_id,
        tier=ctx.executor_tier,
        ts_start_ns=now,
        ts_end_ns=now,
        status=status,
        attrs=_json_safe_attrs(attrs),
    )
    await ctx.trace.emit(event)


def _json_safe_attrs(attrs: dict[str, Any]) -> dict[str, Any]:
    """Drop or stringify values that JSON cannot serialize naively.

    Args:
        attrs (dict[str, Any]): Raw attribute payload from a trace site.

    Returns:
        dict[str, Any]: Shallow copy where ``Path`` and other non-primitives
            are coerced via :func:`sevn.agent.tracing.attrs.json_safe_trace_attrs`.

    Examples:
        >>> _json_safe_attrs({"a": 1, "p": Path("/tmp/x")}) == {"a": 1, "p": "/tmp/x"}
        True
        >>> _json_safe_attrs({"b": None})
        {'b': None}
    """
    from sevn.agent.tracing.attrs import json_safe_trace_attrs, trace_tool_result_value

    safe = dict(attrs)
    raw_args = safe.get("arguments")
    if isinstance(raw_args, dict):
        safe["arguments"] = json_safe_trace_attrs(raw_args)
    if "result" in safe and isinstance(safe["result"], str):
        safe["result"] = trace_tool_result_value(safe["result"])
    return json_safe_trace_attrs(safe)


def enveloped_success(data: Any | None = None, *, message: str | None = None) -> str:
    """Serialize a compliant success envelope (§3.1).

    Args:
        data (Any | None): Payload placed under ``data`` (mapping recommended).
        message (str | None): Optional auxiliary text.

    Returns:
        str: Minified JSON object string.

    Examples:
        >>> import json
        >>> json.loads(enveloped_success({"x": 1}))["ok"]
        True
    """
    blob: dict[str, Any] = {"ok": True, "message": message}
    if data is None:
        blob["data"] = {}
    else:
        blob["data"] = data
    return json.dumps(blob, separators=(",", ":"), ensure_ascii=False)


def enveloped_failure(
    error: str,
    *,
    code: ToolResultCode,
    data: Mapping[str, Any] | None = None,
) -> str:
    """Serialize a compliant failure envelope (§3.1).

    Args:
        error (str): Human-visible reason string.
        code (ToolResultCode): Machine-readable code.
        data (Mapping[str, Any] | None): Rare extra JSON-safe payload.

    Returns:
        str: Minified JSON object string.

    Examples:
        >>> import json
        >>> from sevn.tools.codes import ToolResultCode
        >>> out = enveloped_failure("missing", code=ToolResultCode.UNKNOWN_TOOL)
        >>> json.loads(out)["code"]
        'UNKNOWN_TOOL'
    """
    payload: dict[str, Any] = {
        "ok": False,
        "error": error,
        "code": str(code),
    }
    if data:
        payload["data"] = dict(data)
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def _is_spill_artifact_read(data: dict[str, Any]) -> bool:
    """Return True when ``data`` is a ``read`` envelope of a spill artifact.

    A ``read`` of an artifact previously written by
    :func:`maybe_spill_large_payload` wraps the spilled bytes in a fresh
    ``{"path", "kind": "file", "content": ...}`` envelope. Re-spilling that
    envelope would recurse forever, so such reads must be terminal. This helper
    recognises them by the ``kind`` plus a ``path`` under
    :data:`_SPILL_DIR_SEGMENT` (matched on the POSIX form so Windows
    backslash separators are handled too).

    Args:
        data (dict[str, Any]): The ``data`` payload of a success envelope.

    Returns:
        bool: True when this is a file read whose path is under the spill root.

    Examples:
        >>> _is_spill_artifact_read({"kind": "file", "path": ".sevn/tool_results/s/a.json"})
        True
        >>> _is_spill_artifact_read({"kind": "file", "path": ".sevn\\\\tool_results\\\\s\\\\a.json"})
        True
        >>> _is_spill_artifact_read({"kind": "file", "path": "memory/USER.md"})
        False
        >>> _is_spill_artifact_read({"kind": "directory", "path": ".sevn/tool_results/s"})
        False
    """
    if data.get("kind") != "file":
        return False
    path = data.get("path")
    if not isinstance(path, str):
        return False
    return _SPILL_DIR_SEGMENT in path.replace("\\", "/")


def maybe_spill_large_payload(
    workspace: Path,
    session_id: str,
    *,
    envelope_str: str,
    threshold_bytes: int = TOOL_LARGE_RESULT_THRESHOLD_BYTES,
) -> str:
    """Spill overweight success payloads before returning to transports (§3.1).

    Args:
        workspace (Path): Workspace content root.
        session_id (str): Logical session subdirectory name.
        envelope_str (str): Final JSON envelope (UTF-8).
        threshold_bytes (int): Byte-length gate before rewriting ``data``.

    Returns:
        str: Possibly rewritten JSON envelope string.

    Examples:
        >>> from pathlib import Path
        >>> import json
        >>> ws = Path("/tmp/_sevn_spill_demo")
        >>> big_data = {"blob": "x" * 35000}
        >>> env = enveloped_success(big_data)
        >>> out = maybe_spill_large_payload(ws, "sess", envelope_str=env)
        >>> payload = json.loads(out)
        >>> isinstance(payload["data"], dict) and "spill_path" in payload["data"]
        True
    """
    raw_bytes = envelope_str.encode("utf-8")
    if len(raw_bytes) <= threshold_bytes:
        return envelope_str
    envelope = json.loads(envelope_str)
    if not isinstance(envelope, dict):
        return envelope_str
    if not envelope.get("ok"):
        return envelope_str
    data = envelope.get("data")
    # Idempotency: a payload that already carries a spill descriptor — either
    # the new shape (``spill_path``) or the legacy shape (``path``) — must not
    # be re-spilled.
    if isinstance(data, dict) and "spill_path" in data and "summary" in data:
        return envelope_str
    if isinstance(data, dict) and {"path", "summary", "size"}.issubset(data.keys()):
        return envelope_str
    # Terminal spill-artifact read: a ``read`` of a file under the spill root is
    # the recovery step itself, so returning it inline must never re-spill.
    if isinstance(data, dict) and _is_spill_artifact_read(data):
        return envelope_str
    # Depth guard (belt-and-suspenders): refuse to spill anything already at
    # depth >= 1 regardless of envelope shape, so a spill-of-a-spill is
    # structurally impossible.
    if isinstance(data, dict) and int(data.get("spill_depth", 0)) >= 1:
        return envelope_str

    spill_dir = workspace / ".sevn" / "tool_results" / session_id
    spill_dir.mkdir(parents=True, exist_ok=True)
    spill_path = spill_dir / f"{uuid.uuid4().hex}.json"
    spilled_json = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    spill_path.write_text(spilled_json, encoding="utf-8")
    rel = spill_path.resolve().relative_to(workspace.resolve())

    preview: str | None = None
    if isinstance(spilled_json, str) and TOOL_LARGE_RESULT_PREVIEW_CHARS > 0:
        preview = spilled_json[:TOOL_LARGE_RESULT_PREVIEW_CHARS]

    # ``spill_path`` (not ``path``) is the distinctive marker — the agent can
    # confuse a plain ``path`` field for the originally-queried path. The
    # ``spill_notice`` tells the agent exactly what to do next.
    spill_rel = str(rel)
    descriptor: dict[str, Any] = {
        "spill_path": spill_rel,
        "summary": "Large tool output spilled to workspace disk",
        "size": spill_path.stat().st_size,
        "spill_depth": 1,
        "spill_notice": (
            f"Tool output exceeded the inline threshold and was written to {spill_rel}. "
            f"Call `read` with path={spill_rel} to load the full payload — reading a spill "
            f"artifact is terminal and will not spill again. If the artifact is itself very "
            f"large, page it with `read path={spill_rel} offset=… limit=…`. Do NOT re-issue "
            f"the original tool call."
        ),
    }
    if preview:
        descriptor["preview"] = preview
    envelope["data"] = descriptor
    return json.dumps(envelope, separators=(",", ":"), ensure_ascii=False)


class FunctionTool(Tool):
    """Concrete ``Tool`` wrapping an async (or sync) Python callable."""

    def __init__(self, definition_obj: ToolDefinition, callable_obj: Any) -> None:
        """Store metadata and callable.

        Args:
            definition_obj (ToolDefinition): Exported catalog metadata.
            callable_obj (Any): Callable ``(ctx: ToolContext, **kwargs) -> str | dict | awaitable``.

        Returns:
            None

        Raises:
            (none)

        Examples:
            >>> ToolDefinition.__name__
            'ToolDefinition'
        """

        self._definition = definition_obj
        self._callable = callable_obj
        inspect.signature(callable_obj)

    def definition(self) -> ToolDefinition:
        """Return immutable metadata.

        Returns:
            ToolDefinition: Frozen catalog row supplied at construction.

        Examples:
            >>> d = ToolDefinition(
            ...     name="d",
            ...     category="meta",
            ...     description="d",
            ...     parameters={"type": "object", "properties": {}},
            ... )
            >>> async def _body(ctx, **_):  # type: ignore[misc,no-untyped-def]
            ...     return '{"ok": true, "data": {}, "message": null}'
            >>> FunctionTool(d, _body).definition().name
            'd'
        """
        return self._definition

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> str:
        """Invoke wrapped body and normalize JSON/text output.

        Args:
            ctx (ToolContext): Runtime envelope passed to the underlying body.
            kwargs (Any): Validated tool arguments forwarded verbatim.

        Returns:
            str: §3.1 JSON envelope; non-JSON text is wrapped as ``INTERNAL_ERROR``.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(FunctionTool.execute)
            True
        """
        result = self._callable(ctx, **kwargs)
        if inspect.isawaitable(result):
            raw_out = await result
        else:
            raw_out = result
        if isinstance(raw_out, str):
            return _ensure_single_json_object_string(raw_out)
        return enveloped_success(raw_out)


def _ensure_single_json_object_string(raw_out: str) -> str:
    """Validate ``raw_out`` is one JSON object; wrap plain text shim-style otherwise.

    Args:
        raw_out (str): String returned by a tool body.

    Returns:
        str: ``raw_out`` unchanged when it decodes to a JSON object; otherwise
            a synthesized ``INTERNAL_ERROR`` failure envelope string.

    Examples:
        >>> import json
        >>> _ensure_single_json_object_string('{"ok": true}')
        '{"ok": true}'
        >>> bad = _ensure_single_json_object_string("not json")
        >>> json.loads(bad)["code"]
        'INTERNAL_ERROR'
    """
    try:
        blob = json.loads(raw_out)
    except json.JSONDecodeError:
        return enveloped_failure("Tool returned non-JSON text", code=ToolResultCode.INTERNAL_ERROR)
    if not isinstance(blob, dict):
        return enveloped_failure("Tool JSON must be an object", code=ToolResultCode.INTERNAL_ERROR)
    return raw_out


@dataclass
class BoundToolCallable:
    """Phase-2 shim when decorator metadata is inspected manually."""

    definition_obj: ToolDefinition
    callable_obj: Any


class ToolExecutor:
    """Registers ``Tool`` instances and exposes async ``dispatch``.

    Typical construction happens in gateway/session scopes (``specs/17-gateway.md``).

    Attributes:
        _tools (dict[str, Tool]): Live registry mapping.
        default_timeout_seconds (float | None): Passed to ``asyncio.wait_for`` when set.
    """

    def __init__(self, *, default_timeout_seconds: float | None = 30.0) -> None:
        """Create an empty registry.

        Args:
            default_timeout_seconds (float | None, optional): Default deadline
                applied by :meth:`dispatch` when callers do not override.
                Defaults to ``30.0``.

        Examples:
            >>> ToolExecutor(default_timeout_seconds=None).default_timeout_seconds is None
            True
        """
        self._tools: dict[str, Tool] = {}
        self.default_timeout_seconds = default_timeout_seconds

    def register(self, tool: Tool) -> None:
        """Add or replace a tool by canonical ``definition().name``.

        Args:
            tool (Tool): Instance to register.

        Raises:
            ValueError: Duplicate registration when sentinel disallows overwrite (not enforced).

        Examples:
            >>> from sevn.tools.base import ToolDefinition, FunctionTool
            >>> execu = ToolExecutor(default_timeout_seconds=None)
            >>> async def body(ctx):  # type: ignore[misc,no-untyped-def]
            ...     return enveloped_success({"k": True})
            >>> d = ToolDefinition(
            ...     name="x",
            ...     category="meta",
            ...     description="x",
            ...     parameters={"type": "object", "properties": {}},
            ... )
            >>> execu.register(FunctionTool(d, body))
            >>> execu.snapshot_definition("x").name
            'x'
        """

        name = tool.definition().name
        self._tools[name] = tool

    def unregister(self, name: str) -> None:
        """Remove ``name`` if present.

        Args:
            name (str): Canonical tool identifier; no-op when missing.

        Examples:
            >>> ex = ToolExecutor(default_timeout_seconds=None)
            >>> ex.unregister("missing") is None
            True
        """
        self._tools.pop(name, None)

    def has(self, name: str) -> bool:
        """Return True when ``name`` is registered.

        Args:
            name (str): Canonical tool identifier.

        Returns:
            bool: Whether the executor currently holds a binding.

        Examples:
            >>> ToolExecutor(default_timeout_seconds=None).has("missing")
            False
        """
        return name in self._tools

    def get(self, name: str) -> Tool | None:
        """Lookup tool by ``name``.

        Args:
            name (str): Tool identifier.

        Returns:
            Tool | ``None``: Instance when registered.

        Examples:
            >>> ToolExecutor(default_timeout_seconds=None).get("nope") is None
            True
        """
        return self._tools.get(name)

    def definitions(self) -> tuple[ToolDefinition, ...]:
        """Return immutable sorted snapshot of definitions for ``ToolSet``.

        Returns:
            tuple[ToolDefinition, ...]: Stable name-sorted snapshot suitable
                for adapter prompts and ``ToolSet`` freezes.

        Examples:
            >>> ToolExecutor(default_timeout_seconds=None).definitions()
            ()
        """
        return tuple(
            sorted((t.definition() for t in self._tools.values()), key=lambda item: item.name)
        )

    def snapshot_definition(self, name: str) -> ToolDefinition | None:
        """Return ``ToolDefinition`` for ``name`` if registered.

        Args:
            name (str): Canonical tool identifier.

        Returns:
            ToolDefinition | None: Definition snapshot or ``None`` when absent.

        Examples:
            >>> ToolExecutor(default_timeout_seconds=None).snapshot_definition("x") is None
            True
        """
        inst = self._tools.get(name)
        return None if inst is None else inst.definition()

    async def dispatch(
        self,
        ctx: ToolContext,
        call: ToolCall,
        *,
        timeout_seconds: float | None | Literal["default"] = "default",
    ) -> str:
        """Resolve ``call.name``, validate, trace, invoke, optionally spill oversized JSON.

        Args:
            ctx (ToolContext): Runtime frame (session/workspace/trace).
            call (ToolCall): Invoked tool identifier + kwargs dict.
            timeout_seconds (float | None | "default"): Per-call deadline; ``None`` disables.

        Returns:
            str: JSON envelope string obeying §3.1.

        Examples:
            >>> import asyncio
            >>> import json
            >>> from pathlib import Path
            >>> from sevn.tools.permissions import AllowAllPermissionPolicy
            >>> from sevn.tools.context import ToolContext
            >>> async def nop(ctx, **_):  # type: ignore[misc,no-untyped-def]
            ...     return enveloped_success({})
            >>> d = ToolDefinition(
            ...     name="noop",
            ...     category="meta",
            ...     description="noop",
            ...     parameters={"type": "object", "properties": {}},
            ... )
            >>> ex = ToolExecutor(default_timeout_seconds=5.0)
            >>> ex.register(FunctionTool(d, nop))
            >>> ctx = ToolContext(
            ...     session_id="s",
            ...     workspace_path=Path("/tmp"),
            ...     workspace_id="w",
            ...     registry_version=1,
            ...     trace=None,
            ...     permissions=AllowAllPermissionPolicy(),
            ... )
            >>> out = asyncio.run(ex.dispatch(ctx, ToolCall(name="noop", arguments={})))
            >>> json.loads(out)["ok"]
            True
        """

        name = call.name
        payload_args = dict(call.arguments)
        tool = self._tools.get(name)
        if tool is None:
            await _trace_emit(ctx, kind="tool.error", status="error", attrs={"name": name})
            return enveloped_failure(
                f"Unknown tool {name}",
                code=ToolResultCode.UNKNOWN_TOOL,
            )
        definition = tool.definition()
        await _trace_emit(
            ctx,
            kind="tool.invoke",
            status="started",
            attrs={
                "name": name,
                "arguments": payload_args,
                "abortable": definition.abortable,
                "requires_human": definition.requires_human,
                "workspace_id": ctx.workspace_id,
            },
        )
        if not definition.enabled:
            await _trace_emit(
                ctx, kind="tool.error", status="error", attrs={"name": name, "reason": "disabled"}
            )
            return enveloped_failure(
                "Tool disabled for this workspace", code=ToolResultCode.DISABLED_TOOL
            )
        permission_gate = ctx.permissions
        if permission_gate is not None and not permission_gate.may_invoke(name):
            await _trace_emit(
                ctx,
                kind="tool.error",
                status="error",
                attrs={"name": name, "code": ToolResultCode.PERMISSION_DENIED.value},
            )
            return enveloped_failure(
                "Permission denied for tool invocation",
                code=ToolResultCode.PERMISSION_DENIED,
            )

        if definition.requires_human and name not in ctx.human_acknowledged_tools:
            await _trace_emit(ctx, kind="tool.error", status="error", attrs={"name": name})
            return enveloped_failure(
                "requires_human gate not acknowledged for this turn",
                code=ToolResultCode.PLAN_HUMAN_GATE,
            )

        chain = ctx.plugin_hooks
        if chain is not None:
            hook_ctx = PHookCtx(
                workspace_id=ctx.workspace_id,
                session_id=ctx.session_id,
                turn_id=ctx.turn_id,
                tier=ctx.executor_tier or "B",
                correlation_id=ctx.turn_id,
            )
            try:
                gate = await chain.run_pre_tool_call(name, payload_args, hook_ctx, ctx.trace)
            except Exception as exc:
                await _trace_emit(
                    ctx,
                    kind="tool.error",
                    status="error",
                    attrs={"name": name, "plugin_hook_exc": type(exc).__name__},
                )
                return enveloped_failure(
                    str(exc),
                    code=ToolResultCode.PLUGIN_HOOK_RAISED,
                    data={"kind": "plugin_hook_raised"},
                )
            if isinstance(gate, Block):
                await _trace_emit(
                    ctx,
                    kind="tool.error",
                    status="error",
                    attrs={"name": name, "code": "plugin_block", "reason": gate.reason},
                )
                return enveloped_failure(
                    gate.reason,
                    code=ToolResultCode.PERMISSION_DENIED,
                    data={"kind": "plugin_block"},
                )

        # CodeMode (run_code) re-enters here with kwargs as the model wrote them — typed
        # values arrive as strings (lines='100', summarize='false', argv='["x"]'). Coerce
        # them to the schema's declared primitive before validation so the call runs instead
        # of being rejected and silently dropped in the sandbox (burning run_code retries).
        # Native pydantic-ai calls already arrive typed, so this is a no-op for them.
        payload_args = coerce_string_scalars_to_schema(definition.parameters, payload_args)
        try:
            validate_json_schema_subset(definition.parameters, payload_args)
        except ValueError as exc:
            await _trace_emit(ctx, kind="tool.error", status="error", attrs={"name": name})
            message = exc.args[0] if exc.args else str(exc)
            return enveloped_failure(message, code=ToolResultCode.VALIDATION_ERROR)

        if timeout_seconds != "default":
            timeout = timeout_seconds
        elif definition.dispatch_timeout_seconds != "inherit":
            # Tool-declared override wins over the executor default. ``None`` disables the
            # outer deadline for tools that enforce their own wall-clock budget internally.
            timeout = definition.dispatch_timeout_seconds
        else:
            timeout = self.default_timeout_seconds
        exec_coro = tool.execute(ctx, **payload_args)

        maybe_shield_coro = exec_coro if definition.abortable else asyncio.shield(exec_coro)

        try:
            if timeout is None:
                raw_str = await maybe_shield_coro
            else:
                raw_str = cast("str", await asyncio.wait_for(maybe_shield_coro, timeout=timeout))

            if chain is not None:
                hook_ctx = PHookCtx(
                    workspace_id=ctx.workspace_id,
                    session_id=ctx.session_id,
                    turn_id=ctx.turn_id,
                    tier=ctx.executor_tier or "B",
                    correlation_id=ctx.turn_id,
                )
                try:
                    blob = json.loads(raw_str)
                except json.JSONDecodeError:
                    pass
                else:
                    if isinstance(blob, dict) and blob.get("ok") is True and "data" in blob:
                        new_data = await chain.run_transform_tool_result(
                            name, blob["data"], hook_ctx, ctx.trace
                        )
                        if isinstance(new_data, str):
                            raw_str = new_data
                        else:
                            blob["data"] = new_data
                            raw_str = json.dumps(blob, separators=(",", ":"), ensure_ascii=False)

            spilled = maybe_spill_large_payload(
                ctx.workspace_path,
                ctx.session_id,
                envelope_str=_ensure_outer_envelope_utf8(raw_str),
            )

            await _trace_emit(
                ctx,
                kind="tool.complete",
                status="ok",
                attrs={"name": name, "result": raw_str},
            )
            return spilled
        except TimeoutError:
            broken = enveloped_failure(
                "Tool invocation timed out", code=ToolResultCode.TOOL_TIMEOUT
            )
            await _trace_emit(
                ctx,
                kind="tool.error",
                status="error",
                attrs={"name": name, "code": ToolResultCode.TOOL_TIMEOUT.value},
            )
            return broken
        except asyncio.CancelledError:
            await _trace_emit(ctx, kind="tool.cancelled", status="cancelled", attrs={"name": name})
            raise
        except Exception as exc:
            broken = enveloped_failure(
                str(exc),
                code=ToolResultCode.INTERNAL_ERROR,
            )
            await _trace_emit(
                ctx,
                kind="tool.error",
                status="error",
                attrs={"name": name, "code": ToolResultCode.INTERNAL_ERROR.value},
            )
            return broken


def _ensure_outer_envelope_utf8(raw_str: str) -> str:
    """Force UTF-8 roundtrip for deterministic byte accounting.

    Args:
        raw_str (str): JSON envelope string emitted by a tool body.

    Returns:
        str: Same characters, guaranteed UTF-8 round-trippable so downstream
            byte-length checks behave deterministically.

    Examples:
        >>> _ensure_outer_envelope_utf8('{"ok": true}')
        '{"ok": true}'
    """
    return raw_str.encode("utf-8").decode("utf-8")


__all__ = [
    "BoundToolCallable",
    "FunctionTool",
    "SandboxMode",
    "Tool",
    "ToolCall",
    "ToolContext",
    "ToolDefinition",
    "ToolExecutor",
    "enveloped_failure",
    "enveloped_success",
    "maybe_spill_large_payload",
]
