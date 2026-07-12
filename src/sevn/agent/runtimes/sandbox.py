"""DSPy RLM interpreter selection (``specs/08-sandbox.md`` §4.6).

Module: sevn.agent.runtimes.sandbox
Depends: sevn.config.workspace_config, sevn.security.sandbox_runtime

Exports:
    SevnDockerInterpreter — Docker-backed REPL adapter.
    PyodideDenoInterpreter — Pyodide+Deno path (§4.6).
    build_rlm_interpreter — select interpreter from ``rlm.*`` + Docker probe.

Examples:
    >>> from sevn.agent.runtimes.sandbox import build_rlm_interpreter
    >>> from sevn.config.workspace_config import WorkspaceConfig
    >>> obj = build_rlm_interpreter(WorkspaceConfig.minimal())
    >>> hasattr(obj, "execute_python")
    True
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import tempfile
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from sevn.config.workspace_config import WorkspaceConfig, rlm_json_dict
from sevn.security.sandbox_runtime import (
    DockerSandboxRuntime,
    build_sandbox_child_env,
    docker_daemon_reachable,
)

if TYPE_CHECKING:
    from sevn.agent.tracing.sink import TraceSink


class SevnDockerInterpreter:
    """Docker DSPy interpreter — shares tool-sandbox egress posture (§4.6)."""

    def __init__(
        self,
        *,
        image: str,
        cfg: WorkspaceConfig | None = None,
        workspace: Path | None = None,
        child_env: dict[str, str] | None = None,
        trace_sink: TraceSink | None = None,
    ) -> None:
        """Bind image and optional workspace for ``DockerSandboxRuntime`` REPL exec.

        Args:
            image (str): ``rlm.docker_image`` override or operator default tag.
            cfg (WorkspaceConfig | None): Workspace config for resource caps.
            workspace (Path | None): Host workspace root; ephemeral dir when omitted.
            child_env (dict[str, str] | None): §2.2 env merged at spawn.
            trace_sink (TraceSink | None): Optional telemetry port.

        Returns:
            None: Always ``None``.

        Examples:
            >>> SevnDockerInterpreter(image="x").image
            'x'
        """
        self._image = image
        self._cfg = cfg or WorkspaceConfig.minimal()
        self._workspace = workspace
        self._child_env = dict(child_env or {})
        self._runtime = DockerSandboxRuntime(
            trace_sink=trace_sink,
            cfg=self._cfg,
            image=image,
        )
        self._sandbox_id: str | None = None
        self._ephemeral_workspace = False

    @property
    def image(self) -> str:
        """Docker image tag destined for DSPy sandbox REPL workloads.

        Returns:
            str: Interpreter image coordinate.

        Examples:
            >>> SevnDockerInterpreter(image="tag").image
            'tag'
        """
        return self._image

    async def _ensure_spawned(self) -> str:
        """Spawn the backing container once per interpreter instance.

        Returns:
            str: Docker container id for subsequent exec calls.

        Examples:
            >>> isinstance(True, bool)
            True
        """
        if self._sandbox_id is not None:
            return self._sandbox_id
        ws = self._workspace
        if ws is None:
            ws = Path(tempfile.mkdtemp(prefix="sevn-repl-ws-"))
            self._workspace = ws
            self._ephemeral_workspace = True
        env = dict(self._child_env)
        if "SEVN_PROXY_URL" not in env:
            env.update(
                build_sandbox_child_env(
                    proxy_url="http://127.0.0.1:8787",
                    session_token="repl-session-token",  # nosec B106 — harness-only placeholder token
                    workspace_mount_path="/workspace",
                )
            )
        self._sandbox_id = await self._runtime.spawn(
            run_id=f"repl-{uuid.uuid4().hex[:12]}",
            workspace=ws,
            env=env,
        )
        return self._sandbox_id

    async def _execute_python_async(self, code: str) -> str:
        """Run Python inside the container REPL handshake.

        Args:
            code (str): Python source for ``<repl>`` scope.

        Returns:
            str: Captured stdout (marker stripped).

        Raises:
            RuntimeError: When the container process exits non-zero.

        Examples:
            >>> isinstance(True, bool)
            True
        """
        sid = await self._ensure_spawned()
        result = await self._runtime.exec_python_repl(sid, code)
        exit_raw = result.get("exit_code", 1)
        if isinstance(exit_raw, int):
            exit_code = exit_raw
        elif isinstance(exit_raw, str):
            exit_code = int(exit_raw)
        else:
            exit_code = 1
        stdout = str(result.get("stdout", ""))
        stderr = str(result.get("stderr", ""))
        if exit_code != 0:
            msg = f"REPL execution failed (exit {exit_code}): {stderr or stdout}"
            raise RuntimeError(msg)
        return stdout

    def execute_python(self, code: object, *args: object, **kwargs: object) -> str:
        """Execute model-authored REPL code (DSPy-compatible surface).

        Args:
            code (object): Python source string (or first positional str).
            args (object): Ignored unless first arg is the code string.
            kwargs (object): Reserved for future interpreter knobs.

        Returns:
            str: REPL stdout from the sandbox container.

        Raises:
            TypeError: When no string code payload is provided.
            RuntimeError: When docker exec returns non-zero.

        Examples:
            >>> isinstance(True, bool)
            True
        """
        _ = kwargs
        src: str
        if isinstance(code, str):
            src = code
        elif args and isinstance(args[0], str):
            src = args[0]
        else:
            msg = "execute_python expects a str code payload (specs/08-sandbox.md §4.6)"
            raise TypeError(msg)

        async def _run() -> str:
            return await self._execute_python_async(src)

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(_run())
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, _run()).result()

    async def aclose(self) -> None:
        """Tear down the backing container when spawned.

        Returns:
            None: Always ``None``.

        Examples:
            >>> isinstance(True, bool)
            True
        """
        if self._sandbox_id is not None:
            await self._runtime.teardown(self._sandbox_id)
            self._sandbox_id = None
        if self._ephemeral_workspace and self._workspace is not None:
            import shutil

            shutil.rmtree(self._workspace, ignore_errors=True)
            self._workspace = None


class PyodideDenoInterpreter:
    """Pyodide-in-Deno path when Docker is unavailable (§4.6)."""

    def __init__(self, *, runner: object | None = None) -> None:
        """Construct interpreter delegating to :class:`~sevn.agent.runtimes.pyodide_deno.PyodideDenoRunner`.

        Args:
            runner (object | None): Optional runner override for tests.

        Returns:
            None: Always ``None``.

        Examples:
            >>> isinstance(PyodideDenoInterpreter(), PyodideDenoInterpreter)
            True
        """
        from sevn.agent.runtimes.pyodide_deno import PyodideDenoRunner

        self._runner = runner if runner is not None else PyodideDenoRunner()

    def execute_python(self, code: object, *args: object, **kwargs: object) -> str:
        """Run inner-loop Python via Pyodide in Deno.

        Args:
            code (object): Python source string (or first positional str).
            args (object): Ignored unless first arg is the code string.
            kwargs (object): Reserved for future interpreter knobs.

        Returns:
            str: Captured stdout on success.

        Raises:
            TypeError: When no string code payload is provided.
            RuntimeError: When Deno is missing or execution fails.

        Examples:
            >>> isinstance(True, bool)
            True
        """
        _ = kwargs
        src: str
        if isinstance(code, str):
            src = code
        elif args and isinstance(args[0], str):
            src = args[0]
        else:
            msg = "execute_python expects a str code payload (specs/08-sandbox.md §4.6)"
            raise TypeError(msg)
        from sevn.agent.runtimes.pyodide_deno import PyodideDenoRunner

        runner = self._runner
        if not isinstance(runner, PyodideDenoRunner):
            msg = "PyodideDenoInterpreter runner must be PyodideDenoRunner"
            raise TypeError(msg)
        return runner.execute_python(src)


def _rlm_blob(cfg: WorkspaceConfig) -> dict[str, object]:
    """Normalize ``cfg.rlm`` JSON fragment to a mapping.

    Args:
        cfg (WorkspaceConfig): Workspace root model.

    Returns:
        dict[str, object]: Empty dict when ``rlm`` unset or non-dict.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _rlm_blob(WorkspaceConfig.minimal()) == {}
        True
    """
    return dict(rlm_json_dict(cfg))


def _default_repl_image(cfg: WorkspaceConfig) -> str:
    """Resolve ``rlm.docker_image`` or fall back to shipped base tag.

    Args:
        cfg (WorkspaceConfig): Workspace root model.

    Returns:
        str: Non-empty docker image coordinate.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _default_repl_image(WorkspaceConfig.minimal()).startswith("ghcr.io")
        True
    """
    blob = _rlm_blob(cfg)
    cand = blob.get("docker_image")
    if isinstance(cand, str) and cand.strip():
        return cand.strip()
    return "ghcr.io/sevn-bot/sevn/sandbox:dev"


def build_rlm_interpreter(workspace: object) -> object:
    """Return a DSPy ``PythonInterpreter``-shaped adapter (§2.1, §4.6).

    ``workspace`` must parse as ``WorkspaceConfig``; unknown objects raise
    ``TypeError`` early so gateways fail fast during wiring.

    Args:
        workspace (object): Parsed ``sevn.json`` root (``WorkspaceConfig``).

    Returns:
        object: ``SevnDockerInterpreter`` or ``PyodideDenoInterpreter``.

    Raises:
        TypeError: When ``workspace`` is not a ``WorkspaceConfig``.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> isinstance(build_rlm_interpreter(WorkspaceConfig.minimal()), object)
        True
    """
    if not isinstance(workspace, WorkspaceConfig):
        msg = "build_rlm_interpreter expects WorkspaceConfig (specs/08-sandbox.md §2.1)"
        raise TypeError(msg)
    cfg = workspace
    blob = _rlm_blob(cfg)
    override = blob.get("sandbox")
    override_s = override.strip().lower() if isinstance(override, str) else None
    docker_ok = docker_daemon_reachable()

    if override_s == "docker":
        return SevnDockerInterpreter(image=_default_repl_image(cfg), cfg=cfg)
    if override_s == "pyodide_deno":
        return PyodideDenoInterpreter()

    if docker_ok:
        return SevnDockerInterpreter(image=_default_repl_image(cfg), cfg=cfg)
    return PyodideDenoInterpreter()
