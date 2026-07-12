"""Single gateway-boot factory for :class:`~sevn.tools.runtime_dispatch.RuntimeToolBindings`.

Module: sevn.tools.runtime_bindings_factory
Depends: sevn.agent.runtimes.sandbox_client, sevn.tools.integration_proxy_client,
    sevn.tools.mcp_stdio_client, sevn.tools.readiness, sevn.tools.runtime_dispatch

Exports:
    build_runtime_tool_bindings — construct integration + sandbox + MCP hooks at boot.
    apply_readiness_from_bindings — flip static readiness rows after bindings resolve.

Examples:
    >>> from sevn.config.workspace_config import WorkspaceConfig
    >>> b = build_runtime_tool_bindings(WorkspaceConfig.minimal(), mcp_servers={})
    >>> b.integration is None
    True
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from loguru import logger

from sevn.agent.runtimes.sandbox_client import build_sandbox_executor_client
from sevn.config.workspace_config import WorkspaceConfig
from sevn.tools.integration_proxy_client import build_integration_proxy_client
from sevn.tools.mcp_stdio_client import build_mcp_stdio_client
from sevn.tools.readiness import set_tool_readiness_override
from sevn.tools.runtime_dispatch import (
    IntegrationProxyClient,
    McpStdioClient,
    RuntimeToolBindings,
    SandboxExecutorClient,
)


def build_runtime_tool_bindings(
    cfg: WorkspaceConfig,
    *,
    mcp_servers: Mapping[str, Mapping[str, Any]],
    integration: IntegrationProxyClient | None = None,
    proxy_url: str | None = None,
    session_token: str | None = None,
    proxy_shared_secret: str | None = None,
) -> RuntimeToolBindings:
    """Build the unified runtime hook bundle for gateway boot (W2/W3/W6 seam).

    W2 supplies ``integration`` when wired; W3 builds ``sandbox`` from Pyodide+Deno when
    the driver resolves; W6 builds ``mcp`` from declared stdio servers.

    Args:
        cfg (WorkspaceConfig): Parsed workspace configuration.
        mcp_servers (Mapping[str, Mapping[str, Any]]): Effective MCP server map.
        integration (IntegrationProxyClient | None): Optional W2 proxy client override.
        proxy_url (str | None): Egress proxy URL (W2 integration + W3 sandbox net caps).
        session_token (str | None, optional): Per-run ``SEVN_SESSION_TOKEN`` for proxy auth.
        proxy_shared_secret (str | None, optional): Optional ``SEVN_PROXY_SHARED_SECRET``.

    Returns:
        RuntimeToolBindings: Frozen bundle passed to ``build_agent_run_turn``.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> b = build_runtime_tool_bindings(WorkspaceConfig.minimal(), mcp_servers={})
        >>> b.mcp is None
        True
    """
    resolved_integration: IntegrationProxyClient | None = integration
    if resolved_integration is None:
        built = build_integration_proxy_client(
            proxy_url=proxy_url,
            session_token=session_token,
            proxy_shared_secret=proxy_shared_secret,
        )
        if built is not None:
            resolved_integration = cast("IntegrationProxyClient", built)
    sandbox: SandboxExecutorClient | None = build_sandbox_executor_client(cfg, proxy_url=proxy_url)
    mcp: McpStdioClient | None = build_mcp_stdio_client(mcp_servers)
    bindings = RuntimeToolBindings(
        integration=resolved_integration,
        sandbox=sandbox,
        mcp=mcp,
        mcp_servers=dict(mcp_servers),
    )
    apply_readiness_from_bindings(bindings, cfg)
    return bindings


def apply_readiness_from_bindings(
    bindings: RuntimeToolBindings,
    cfg: WorkspaceConfig,
) -> None:
    """Update static readiness rows for scaffolding tools after boot resolution.

    Args:
        bindings (RuntimeToolBindings): Constructed hook bundle.
        cfg (WorkspaceConfig): Workspace config (driver hints for pending copy).

    Returns:
        None

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> from sevn.tools.runtime_dispatch import RuntimeToolBindings
        >>> apply_readiness_from_bindings(RuntimeToolBindings(), WorkspaceConfig.minimal())
    """
    _ = cfg
    if bindings.integration is not None:
        set_tool_readiness_override(
            "integration_call",
            status="ready",
            note=(
                "Dispatches via egress proxy POST /integration. "
                "GitHub: integration.github.token (or GITHUB_TOKEN) on the proxy. "
                "Cursor: integration.cursor.api_key on the proxy."
            ),
        )
    else:
        set_tool_readiness_override(
            "integration_call",
            status="needs_proxy",
            note=(
                "Requires SEVN_PROXY_URL paired with the gateway. "
                "Provider tokens live in proxy secrets, never the gateway process."
            ),
        )
    if bindings.sandbox is not None:
        set_tool_readiness_override(
            "sandbox_exec",
            status="ready",
            note="Pyodide+Deno sandbox wired at gateway boot (sandbox_exec).",
        )
    else:
        from sevn.agent.runtimes.pyodide_deno import sandbox_exec_unavailable_note

        pending_note = sandbox_exec_unavailable_note(cfg)
        if pending_note:
            logger.warning("sandbox_exec pending at gateway boot: {}", pending_note)
            set_tool_readiness_override(
                "sandbox_exec",
                status="pending",
                note=pending_note,
            )


__all__ = ["apply_readiness_from_bindings", "build_runtime_tool_bindings"]
