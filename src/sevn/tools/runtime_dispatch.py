"""Runtime hooks wiring ``integration_call`` / ``sandbox_exec`` / MCP stdio (`specs/11-tools-registry.md` §4.1, §4.2, §10.1).

Phase-2 ``register_feature_stubs`` registers ``integration_call`` and ``sandbox_exec`` as
disabled scaffolding rows. Wave T activates them by injecting :class:`RuntimeToolBindings`
that delegate dispatch to the Wave Q sandbox runtime + egress-paired proxy, and replaces the
:class:`sevn.tools.registry.McpUnavailableTool` placeholder with :class:`McpStdioTool`
when a Wave S MCP server entry is declared.

Module: sevn.tools.runtime_dispatch
Depends: sevn.tools.base, sevn.tools.codes, sevn.tools.context

Exports:
    Protocols:
        IntegrationProxyClient — egress-paired proxy ``/integration`` dispatcher.
        SandboxExecutorClient — sandbox runtime entrypoint for ``sandbox_exec`` bodies.
        McpStdioClient — Wave S stdio dispatcher invoked from MCP tool descriptors.
    Classes:
        RuntimeToolBindings — frozen bundle holding the three runtime hooks.
        McpStdioTool — :class:`FunctionTool` wrapper delegating to ``McpStdioClient``.
    Functions:
        make_integration_call_tool — build an enabled ``integration_call`` Tool wired to bindings.
        make_sandbox_exec_tool — build an enabled ``sandbox_exec`` Tool wired to bindings.

Examples:
    >>> RuntimeToolBindings().integration is None
    True
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from sevn.tools.base import FunctionTool, ToolDefinition, enveloped_failure, enveloped_success
from sevn.tools.codes import ToolResultCode
from sevn.tools.context import ToolContext
from sevn.tools.integration_gh_repo import GITHUB_INTEGRATION_SERVICE
from sevn.tools.integration_proxy_client import IntegrationCredentialRequired

_UPSTREAM_STATUS_RE = re.compile(r"\bproxy status (\d{3})\b", re.IGNORECASE)
_GITHUB_REPO_SLUG_RE = re.compile(
    r"^(?:https?://(?:www\.)?github\.com/)?(?P<owner>[^/\s]+)/(?P<repo>[^/\s#?]+)",
    re.IGNORECASE,
)


def _looks_like_missing_repo_args(detail: str) -> bool:
    """Heuristic: does ``detail`` read like a missing ``owner``/``repo`` complaint?

    Args:
        detail (str): Exception message from the integration client.

    Returns:
        bool: ``True`` when the message mentions both ``owner`` and ``repo``.

    Examples:
        >>> _looks_like_missing_repo_args("owner and repo are required for github.pulls.list")
        True
        >>> _looks_like_missing_repo_args("proxy status 404")
        False
    """
    lowered = detail.lower()
    return "owner" in lowered and "repo" in lowered


def _github_missing_owner_repo(
    service: str,
    args: Mapping[str, Any],
    detail: str,
) -> bool:
    """Return whether ``detail`` is a missing github ``owner``/``repo`` complaint.

    Args:
        service (str): Integration namespace.
        args (Mapping[str, Any]): Call arguments.
        detail (str): Exception message from the integration client.

    Returns:
        bool: ``True`` only for github calls that omitted both ``owner`` and ``repo``.

    Examples:
        >>> _github_missing_owner_repo("github", {}, "owner and repo are required")
        True
        >>> _github_missing_owner_repo(
        ...     "github",
        ...     {"owner": "o", "repo": "r"},
        ...     "owner and repo are required",
        ... )
        False
    """
    return (
        service == GITHUB_INTEGRATION_SERVICE
        and not (args.get("owner") and args.get("repo"))
        and _looks_like_missing_repo_args(detail)
    )


def _default_github_repo(ctx: ToolContext) -> tuple[str, str] | None:
    """Best-effort ``self_improve.hub.repo`` lookup for github owner/repo resolution.

    Reads the raw ``sevn.json`` dict (no full :class:`WorkspaceConfig` validation, mirroring
    :func:`sevn.tools.browser._browser_tools_cfg`) so a partially-configured workspace never
    raises here — this is a best-effort fallback, not a required config path.

    Args:
        ctx (ToolContext): Active dispatch context (provides the workspace root).

    Returns:
        tuple[str, str] | None: ``(owner, repo)`` when a configured slug parses; else ``None``.

    Examples:
        >>> from pathlib import Path
        >>> ctx = ToolContext(session_id="s", workspace_path=Path("/does/not/exist"),
        ...     workspace_id="w", registry_version=1)
        >>> _default_github_repo(ctx) is None
        True
    """
    path = ctx.workspace_path / "sevn.json"
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    hub = raw.get("self_improve", {})
    hub = hub.get("hub", {}) if isinstance(hub, dict) else {}
    repo = hub.get("repo") if isinstance(hub, dict) else None
    if not isinstance(repo, str) or not repo.strip():
        return None
    slug = repo.strip()
    if slug.endswith(".git"):
        slug = slug[: -len(".git")]
    match = _GITHUB_REPO_SLUG_RE.match(slug)
    if match is None:
        return None
    return match.group("owner"), match.group("repo")


@runtime_checkable
class IntegrationProxyClient(Protocol):
    """Egress-paired proxy ``/integration`` dispatcher (`specs/11-tools-registry.md` §4.1)."""

    async def integration_call(
        self,
        *,
        service: str,
        method: str,
        args: Mapping[str, Any],
        ctx: ToolContext,
    ) -> Mapping[str, Any]:
        """Forward to proxy ``/integration`` with session token; return result payload.

        Args:
            service (str): Dotted integration namespace (``github``, ``slack``, ...).
            method (str): Method identifier within ``service``.
            args (Mapping[str, Any]): JSON-safe positional payload forwarded verbatim.
            ctx (ToolContext): Active tool runtime frame for tracing / session token resolution.

        Returns:
            Mapping[str, Any]: Provider response body decoded into a JSON-safe mapping.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(IntegrationProxyClient.integration_call)
            True
        """
        ...


@runtime_checkable
class SandboxExecutorClient(Protocol):
    """Sandbox runtime entrypoint backing ``sandbox_exec`` (`specs/08-sandbox.md` §4.6)."""

    async def sandbox_exec(
        self,
        *,
        language: str,
        code: str,
        ctx: ToolContext,
    ) -> Mapping[str, Any]:
        """Execute ``code`` in the Wave Q sandbox runtime and return exec metadata.

        Args:
            language (str): Source language (``python``, ``bash``, ...).
            code (str): Source string to evaluate inside the sandbox.
            ctx (ToolContext): Active runtime frame (session id, workspace, trace).

        Returns:
            Mapping[str, Any]: ``{exit_code, stdout, stderr}`` style payload.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(SandboxExecutorClient.sandbox_exec)
            True
        """
        ...


@runtime_checkable
class McpStdioClient(Protocol):
    """Dispatcher for MCP stdio servers declared by Wave S (`specs/11-tools-registry.md` §2.7)."""

    async def call_tool(
        self,
        *,
        server_id: str,
        tool_name: str,
        arguments: Mapping[str, Any],
        ctx: ToolContext,
    ) -> Mapping[str, Any]:
        """Open a stdio session for ``server_id`` and invoke ``tool_name``.

        Args:
            server_id (str): Stable ``mcp_servers`` key (e.g. ``code_review_graph``).
            tool_name (str): Upstream MCP tool name from the server's ``tools/list``.
            arguments (Mapping[str, Any]): JSON-safe arguments to forward.
            ctx (ToolContext): Active runtime frame for tracing / cancellation.

        Returns:
            Mapping[str, Any]: Decoded ``tools/call`` result payload.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(McpStdioClient.call_tool)
            True
        """
        ...


@dataclass(frozen=True)
class RuntimeToolBindings:
    """Bundle wiring registry placeholders to live runtimes (`specs/11-tools-registry.md` §10.1).

    Each field is optional; absent hooks keep the corresponding placeholder behavior
    (``integration_call`` / ``sandbox_exec`` stay disabled; MCP descriptors fall back to
    :class:`sevn.tools.registry.McpUnavailableTool`).
    """

    integration: IntegrationProxyClient | None = None
    sandbox: SandboxExecutorClient | None = None
    mcp: McpStdioClient | None = None
    mcp_servers: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)


def _server_id_for_tool(tool_name: str) -> str:
    """Return the MCP server id portion of a dotted tool name (``server.tool``).

    Args:
        tool_name (str): Registry tool name (typically ``server.tool``).

    Returns:
        str: Substring up to the first ``.``; the full string when no dot is present.

    Examples:
        >>> _server_id_for_tool("code_review_graph.get_minimal_context_tool")
        'code_review_graph'
        >>> _server_id_for_tool("plain")
        'plain'
    """
    head, sep, _tail = tool_name.partition(".")
    return head if sep else tool_name


def make_integration_call_tool(bindings: RuntimeToolBindings) -> FunctionTool:
    """Build an enabled ``integration_call`` :class:`FunctionTool` wired to ``bindings.integration``.

    Args:
        bindings (RuntimeToolBindings): Runtime bundle (``integration`` must be set).

    Returns:
        FunctionTool: Live tool delegating to :meth:`IntegrationProxyClient.integration_call`.

    Raises:
        ValueError: When ``bindings.integration`` is ``None``.

    Examples:
        >>> import asyncio
        >>> class _Fake:
        ...     async def integration_call(self, *, service, method, args, ctx):
        ...         return {"service": service, "method": method, "args": dict(args)}
        >>> tool = make_integration_call_tool(RuntimeToolBindings(integration=_Fake()))
        >>> tool.definition().enabled
        True
    """
    if bindings.integration is None:
        msg = "make_integration_call_tool requires bindings.integration"
        raise ValueError(msg)
    client = bindings.integration
    definition = ToolDefinition(
        name="integration_call",
        category="integrations",
        description="Third-party egress proxy dispatcher (Wave T runtime).",
        parameters={
            "type": "object",
            "properties": {
                "service": {"type": "string"},
                "method": {"type": "string"},
                "args": {"type": "object"},
            },
            "required": ["service", "method", "args"],
        },
        enabled=True,
        abortable=False,
    )

    async def _resolve_or_guide_missing_repo(
        ctx: ToolContext,
        *,
        service: str,
        method: str,
        args: dict[str, Any],
        detail: str,
    ) -> str:
        """Retry once with a resolved ``owner``/``repo``, else return a guide error.

        Never fabricates values (W5.3, `build-plan-from-review/waves/
        voice-duplex-tts-menu-log-fixes-wave-plan.md`) — resolution only fires from a
        configured ``self_improve.hub.repo`` slug, and only when the caller actually
        omitted ``owner``/``repo``.

        Args:
            ctx (ToolContext): Active dispatch context.
            service (str): Integration namespace (``github``, ...).
            method (str): Dotted method identifier.
            args (dict[str, Any]): Original call arguments (owner/repo missing).
            detail (str): Upstream detail describing the missing-args failure.

        Returns:
            str: §3.1 JSON envelope — success on a resolved retry, else a
                ``VALIDATION_ERROR`` guide naming the missing params.
        """
        if service == GITHUB_INTEGRATION_SERVICE and not (args.get("owner") and args.get("repo")):
            resolved = _default_github_repo(ctx)
            if resolved is not None:
                owner, repo = resolved
                merged = {
                    **args,
                    "owner": args.get("owner") or owner,
                    "repo": args.get("repo") or repo,
                }
                try:
                    payload = await client.integration_call(
                        service=service,
                        method=method,
                        args=merged,
                        ctx=ctx,
                    )
                except Exception as retry_exc:
                    return await _integration_call_failure_envelope(
                        ctx,
                        service=service,
                        method=method,
                        args=merged,
                        exc=retry_exc,
                        context_note=(
                            "still failing after resolving owner/repo from self_improve.hub.repo"
                        ),
                    )
                return enveloped_success(dict(payload))
        return enveloped_failure(
            f"integration_call {service}.{method} needs owner/repo: {detail}. Pass them "
            'explicitly (e.g. {"owner": "org", "repo": "name"}) or set self_improve.hub.repo '
            "in sevn.json — sevn.bot never fabricates repository identifiers.",
            code=ToolResultCode.VALIDATION_ERROR,
            data={"service": service, "method": method, "missing": ["owner", "repo"]},
        )

    async def _integration_call_failure_envelope(
        ctx: ToolContext,
        *,
        service: str,
        method: str,
        args: dict[str, Any],
        exc: Exception,
        context_note: str = "",
    ) -> str:
        detail = str(exc)
        if _github_missing_owner_repo(service, args, detail):
            return await _resolve_or_guide_missing_repo(
                ctx,
                service=service,
                method=method,
                args=args,
                detail=detail,
            )
        status_match = _UPSTREAM_STATUS_RE.search(detail)
        prefix = f"integration_call {service}.{method}"
        if status_match is not None:
            message = (
                f"{prefix} {context_note}: {detail}"
                if context_note
                else f"{prefix} upstream error: {detail}"
            )
            return enveloped_failure(
                message,
                code=ToolResultCode.UPSTREAM_ERROR,
                data={
                    "service": service,
                    "method": method,
                    "status": int(status_match.group(1)),
                    "retryable": True,
                },
            )
        message = (
            f"{prefix} {context_note}: {exc}" if context_note else f"integration_call failed: {exc}"
        )
        return enveloped_failure(
            message,
            code=ToolResultCode.INTERNAL_ERROR,
            data={"service": service, "method": method},
        )

    async def _invoke(
        ctx: ToolContext,
        *,
        service: str,
        method: str,
        args: dict[str, Any],
    ) -> str:
        try:
            payload = await client.integration_call(
                service=service,
                method=method,
                args=args,
                ctx=ctx,
            )
        except IntegrationCredentialRequired as exc:
            return enveloped_failure(
                str(exc.detail),
                code=ToolResultCode.PERMISSION_DENIED,
                data={
                    "service": service,
                    "method": method,
                    "readiness": "needs_key",
                },
            )
        except ValueError as exc:
            if _github_missing_owner_repo(service, args, str(exc)):
                return await _resolve_or_guide_missing_repo(
                    ctx,
                    service=service,
                    method=method,
                    args=args,
                    detail=str(exc),
                )
            return enveloped_failure(
                f"integration_call {service}.{method} invalid arguments: {exc}",
                code=ToolResultCode.VALIDATION_ERROR,
                data={"service": service, "method": method},
            )
        except Exception as exc:
            return await _integration_call_failure_envelope(
                ctx,
                service=service,
                method=method,
                args=args,
                exc=exc,
            )
        return enveloped_success(dict(payload))

    return FunctionTool(definition, _invoke)


def make_sandbox_exec_tool(bindings: RuntimeToolBindings) -> FunctionTool:
    """Build an enabled ``sandbox_exec`` :class:`FunctionTool` wired to ``bindings.sandbox``.

    Args:
        bindings (RuntimeToolBindings): Runtime bundle (``sandbox`` must be set).

    Returns:
        FunctionTool: Live tool delegating to :meth:`SandboxExecutorClient.sandbox_exec`.

    Raises:
        ValueError: When ``bindings.sandbox`` is ``None``.

    Examples:
        >>> import asyncio
        >>> class _Fake:
        ...     async def sandbox_exec(self, *, language, code, ctx):
        ...         return {"exit_code": 0, "stdout": code, "stderr": ""}
        >>> tool = make_sandbox_exec_tool(RuntimeToolBindings(sandbox=_Fake()))
        >>> tool.definition().sandbox_mode
        'docker'
    """
    if bindings.sandbox is None:
        msg = "make_sandbox_exec_tool requires bindings.sandbox"
        raise ValueError(msg)
    client = bindings.sandbox
    definition = ToolDefinition(
        name="sandbox_exec",
        category="sandbox",
        description="Single v1 sandbox entrypoint (Wave T runtime).",
        parameters={
            "type": "object",
            "properties": {
                "language": {"type": "string"},
                "code": {"type": "string"},
            },
            "required": ["language", "code"],
        },
        enabled=True,
        sandbox_mode="docker",
    )

    async def _invoke(ctx: ToolContext, *, language: str, code: str) -> str:
        try:
            payload = await client.sandbox_exec(language=language, code=code, ctx=ctx)
        except Exception as exc:
            return enveloped_failure(
                f"sandbox_exec failed: {exc}",
                code=ToolResultCode.INTERNAL_ERROR,
                data={"language": language},
            )
        return enveloped_success(dict(payload))

    return FunctionTool(definition, _invoke)


class McpStdioTool(FunctionTool):
    """MCP tool wrapper dispatching to :class:`McpStdioClient` (`specs/11-tools-registry.md` §2.7).

    Falls back to a ``MCP_UNAVAILABLE`` envelope when the underlying client raises so the
    contract from :class:`sevn.tools.registry.McpUnavailableTool` is preserved on transport
    failure.
    """

    def __init__(
        self,
        definition_obj: ToolDefinition,
        *,
        client: McpStdioClient,
        server_id: str | None = None,
    ) -> None:
        """Bind a workspace-declared MCP descriptor to a live stdio client.

        Args:
            definition_obj (ToolDefinition): Session-declared MCP tool row (``server.tool``).
            client (McpStdioClient): Wave S stdio dispatcher.
            server_id (str | None): Override for the ``mcp_servers`` key; defaults to the
                substring of ``definition_obj.name`` up to the first ``.``.

        Returns:
            None

        Examples:
            >>> d = ToolDefinition(
            ...     name="srv.tool",
            ...     category="mcp",
            ...     description="demo",
            ...     parameters={"type": "object", "properties": {}},
            ... )
            >>> class _Fake:
            ...     async def call_tool(self, **_):
            ...         return {"ok": True}
            >>> isinstance(McpStdioTool(d, client=_Fake()), McpStdioTool)
            True
        """
        self._client = client
        self._server_id = server_id or _server_id_for_tool(definition_obj.name)
        upstream_tool_name = definition_obj.name[len(self._server_id) + 1 :] or definition_obj.name

        async def _invoke(ctx: ToolContext, **kwargs: Any) -> str:
            try:
                payload = await self._client.call_tool(
                    server_id=self._server_id,
                    tool_name=upstream_tool_name,
                    arguments=kwargs,
                    ctx=ctx,
                )
            except Exception as exc:
                return enveloped_failure(
                    f"MCP stdio call failed: {exc}",
                    code=ToolResultCode.MCP_UNAVAILABLE,
                    data={"tool": definition_obj.name, "server_id": self._server_id},
                )
            return enveloped_success(dict(payload))

        super().__init__(definition_obj, _invoke)

    @property
    def server_id(self) -> str:
        """Return the ``mcp_servers`` key this tool dispatches against.

        Returns:
            str: Stable server id derived from the descriptor name or constructor override.

        Examples:
            >>> d = ToolDefinition(
            ...     name="srv.tool",
            ...     category="mcp",
            ...     description="demo",
            ...     parameters={"type": "object", "properties": {}},
            ... )
            >>> class _Fake:
            ...     async def call_tool(self, **_):
            ...         return {}
            >>> McpStdioTool(d, client=_Fake()).server_id
            'srv'
        """
        return self._server_id


__all__ = [
    "IntegrationProxyClient",
    "McpStdioClient",
    "McpStdioTool",
    "RuntimeToolBindings",
    "SandboxExecutorClient",
    "make_integration_call_tool",
    "make_sandbox_exec_tool",
]
