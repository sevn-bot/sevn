"""Concrete :class:`~sevn.tools.runtime_dispatch.SandboxExecutorClient` over Pyodide+Deno.

Module: sevn.agent.runtimes.sandbox_client
Depends: sevn.agent.runtimes.pyodide_deno, sevn.tools.context

Exports:
    build_sandbox_executor_client — factory when Pyodide driver + Deno resolve.
    SevnSandboxExecutorClient — ``sandbox_exec`` runtime hook for :class:`RuntimeToolBindings`.

Examples:
    >>> from sevn.config.workspace_config import WorkspaceConfig
    >>> c = SevnSandboxExecutorClient(WorkspaceConfig.minimal())
    >>> c.driver
    'pyodide_deno'
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sevn.agent.runtimes.pyodide_deno import (
    PyodideDenoRunner,
    PyodideDenoUnavailable,
    deno_binary_on_path,
    should_wire_pyodide_sandbox,
)

if TYPE_CHECKING:
    from sevn.config.workspace_config import WorkspaceConfig
    from sevn.tools.context import ToolContext


def build_sandbox_executor_client(
    cfg: WorkspaceConfig,
    *,
    proxy_url: str | None = None,
) -> SevnSandboxExecutorClient | None:
    """Return a live sandbox client when the Pyodide driver resolves.

    Args:
        cfg (WorkspaceConfig): Parsed workspace configuration.
        proxy_url (str | None): Optional egress proxy URL for Deno net caps.

    Returns:
        SevnSandboxExecutorClient | None: Client when Pyodide is selected and Deno is on
            ``PATH``; ``None`` otherwise (registry keeps disabled stub + pending readiness).

    Examples:
        >>> from unittest.mock import patch
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> with patch("sevn.agent.runtimes.sandbox_client.deno_binary_on_path", return_value=None):
        ...     build_sandbox_executor_client(WorkspaceConfig.minimal()) is None
        True
    """
    if not should_wire_pyodide_sandbox(cfg):
        return None
    if deno_binary_on_path() is None:
        return None
    return SevnSandboxExecutorClient(cfg, proxy_url=proxy_url)


class SevnSandboxExecutorClient:
    """Wave W3 ``sandbox_exec`` client backed by :class:`PyodideDenoRunner`."""

    driver: str = "pyodide_deno"

    def __init__(
        self,
        cfg: WorkspaceConfig,
        *,
        proxy_url: str | None = None,
        runner: PyodideDenoRunner | None = None,
    ) -> None:
        """Bind workspace config and optional runner override (tests).

        Args:
            cfg (WorkspaceConfig): Parsed workspace root.
            proxy_url (str | None): Egress proxy base URL for Deno ``--allow-net``.
            runner (PyodideDenoRunner | None): Inject a fake runner in unit tests.

        Returns:
            None

        Examples:
            >>> from sevn.config.workspace_config import WorkspaceConfig
            >>> isinstance(SevnSandboxExecutorClient(WorkspaceConfig.minimal()), SevnSandboxExecutorClient)
            True
        """
        _ = cfg
        self._runner = runner or PyodideDenoRunner(proxy_url=proxy_url)

    async def sandbox_exec(
        self,
        *,
        language: str,
        code: str,
        ctx: ToolContext,
    ) -> dict[str, Any]:
        """Execute ``code`` in Pyodide and return exec metadata.

        Args:
            language (str): Source language (``python`` supported in W3).
            code (str): Source string.
            ctx (ToolContext): Active tool frame (session id for tracing; unused in W3).

        Returns:
            dict[str, Any]: ``{exit_code, stdout, stderr, driver}`` mapping.

        Raises:
            PyodideDenoUnavailable: When Deno or the runner is missing.
            RuntimeError: When execution fails.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(SevnSandboxExecutorClient.sandbox_exec)
            True
        """
        _ = ctx
        lang = language.strip().lower()
        if not self._runner.available:
            msg = (
                "Pyodide+Deno sandbox unavailable: install Deno and set "
                "sandbox.driver or rlm.sandbox to pyodide_deno in sevn.json."
            )
            raise PyodideDenoUnavailable(msg)
        if lang != "python":
            return {
                "exit_code": 1,
                "stdout": "",
                "stderr": f"unsupported language: {language} (pyodide_deno supports python only)",
                "driver": self.driver,
            }
        result = await self._runner.execute_python_async(code)
        payload = result.as_mapping()
        payload["driver"] = self.driver
        return dict(payload)


__all__ = ["SevnSandboxExecutorClient", "build_sandbox_executor_client"]
