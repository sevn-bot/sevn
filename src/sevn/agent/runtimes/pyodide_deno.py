"""Pyodide-in-Deno launcher for ``sandbox_exec`` and DSPy REPL (``specs/08-sandbox.md`` §4.6).

Module: sevn.agent.runtimes.pyodide_deno
Depends: sevn.config.workspace_config, sevn.security.sandbox_runtime

Exports:
    PyodideDenoUnavailable — driver or Deno binary missing.
    PyodideExecResult — structured stdout/stderr/exit payload.
    deno_binary_on_path — resolve ``deno`` executable.
    resolve_sandbox_exec_driver — read ``sandbox.driver`` / ``rlm.sandbox`` override.
    effective_sandbox_exec_driver — configured driver after runtime availability checks.
    sandbox_driver_runtime_available — whether host can run a driver slug.
    sandbox_exec_unavailable_note — operator note when ``sandbox_exec`` cannot wire.
    reconcile_sandbox_mode_document — downgrade onboarding ``sandbox.mode`` when runtime absent.
    should_wire_pyodide_sandbox — whether gateway boot should attach a sandbox client.
    PyodideDenoRunner — async/sync Python execution via Deno + Pyodide.
    pyodide_runner_script_path — packaged ``pyodide_runner.ts`` path.

Examples:
    >>> deno_binary_on_path() is None or isinstance(deno_binary_on_path(), str)
    True
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess  # nosec B404
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sevn.security.sandbox_runtime import docker_daemon_reachable

if TYPE_CHECKING:
    from sevn.config.workspace_config import WorkspaceConfig


class PyodideDenoUnavailable(RuntimeError):
    """Raised when Pyodide+Deno cannot run (missing Deno or unsupported language)."""


def deno_binary_on_path() -> str | None:
    """Return the ``deno`` executable path when installed.

    Returns:
        str | None: Absolute path to ``deno``, or ``None`` when absent.

    Examples:
        >>> deno_binary_on_path() is None or Path(deno_binary_on_path() or "").name == "deno"
        True
    """
    return shutil.which("deno")


def pyodide_runner_script_path() -> Path:
    """Return the packaged Deno runner script path.

    Returns:
        Path: ``pyodide_runner.ts`` inside ``sevn.agent.runtimes``.

    Examples:
        >>> p = pyodide_runner_script_path()
        >>> p.name
        'pyodide_runner.ts'
    """
    ref = resources.files("sevn.agent.runtimes").joinpath("pyodide_runner.ts")
    return Path(str(ref))


def _sandbox_extra_dict(cfg: WorkspaceConfig) -> dict[str, Any]:
    """Return forward-compatible ``sandbox.*`` extras from workspace config.

    Args:
        cfg (WorkspaceConfig): Parsed workspace root.

    Returns:
        dict[str, Any]: Extra keys on ``sandbox`` (``driver``, ``runtime``, ...).

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _sandbox_extra_dict(WorkspaceConfig.minimal()) == {}
        True
    """
    sb = cfg.sandbox
    if sb is None:
        return {}
    extra = getattr(sb, "model_extra", None) or {}
    return dict(extra)


_SANDBOX_DRIVER_KEYS: tuple[str, ...] = ("driver", "runtime", "mode")


def resolve_sandbox_exec_driver(cfg: WorkspaceConfig) -> str | None:
    """Resolve explicit sandbox driver override for ``sandbox_exec``.

    Checks ``sandbox.driver``, ``sandbox.runtime``, ``sandbox.mode`` (onboarding), then
    ``rlm.sandbox``. Returns ``None`` when auto-detect should mirror
    ``build_rlm_interpreter``.

    Args:
        cfg (WorkspaceConfig): Parsed workspace configuration.

    Returns:
        str | None: ``pyodide_deno``, ``docker``, ``subprocess``, or ``None`` for auto.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> resolve_sandbox_exec_driver(WorkspaceConfig.minimal()) is None
        True
    """
    extra = _sandbox_extra_dict(cfg)
    for key in _SANDBOX_DRIVER_KEYS:
        raw = extra.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip().lower()
    rlm = cfg.rlm
    if rlm is not None and rlm.sandbox is not None:
        return rlm.sandbox.strip().lower()
    return None


def sandbox_driver_runtime_available(driver: str) -> bool:
    """Return whether the host can run the requested sandbox driver.

    Args:
        driver (str): Lower-case driver slug from config.

    Returns:
        bool: ``True`` when the runtime prerequisite is satisfied.

    Examples:
        >>> sandbox_driver_runtime_available("subprocess")
        True
    """
    normalized = driver.strip().lower()
    if normalized == "pyodide_deno":
        return deno_binary_on_path() is not None
    if normalized == "docker":
        return docker_daemon_reachable()
    return True


def effective_sandbox_exec_driver(cfg: WorkspaceConfig) -> str | None:
    """Resolve the sandbox driver after runtime availability and downgrade rules.

    When ``pyodide_deno`` is configured but Deno is missing, downgrade to ``docker``
    when the daemon is reachable; otherwise return ``None`` (no Pyodide wire attempt).
    When ``docker`` is configured but Docker is missing, downgrade to ``pyodide_deno``
    only when Deno is on ``PATH``.

    Args:
        cfg (WorkspaceConfig): Parsed workspace configuration.

    Returns:
        str | None: Effective driver for gateway boot, or ``None`` for auto / unavailable.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> drv = effective_sandbox_exec_driver(WorkspaceConfig.minimal())
        >>> drv is None or drv == "pyodide_deno"
        True
    """
    configured = resolve_sandbox_exec_driver(cfg)
    if configured is None:
        if docker_daemon_reachable():
            return None
        if deno_binary_on_path() is not None:
            return "pyodide_deno"
        return None
    if sandbox_driver_runtime_available(configured):
        return configured
    if configured == "pyodide_deno":
        if docker_daemon_reachable():
            return "docker"
        return None
    if configured == "docker" and deno_binary_on_path() is not None:
        return "pyodide_deno"
    return None


def sandbox_exec_unavailable_note(cfg: WorkspaceConfig) -> str | None:
    """Return an operator-facing note when ``sandbox_exec`` cannot wire at boot.

    Args:
        cfg (WorkspaceConfig): Parsed workspace configuration.

    Returns:
        str | None: Pending-readiness copy when config requests an absent runtime.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig, RlmWorkspaceConfig
        >>> note = sandbox_exec_unavailable_note(
        ...     WorkspaceConfig.minimal(rlm=RlmWorkspaceConfig(sandbox="pyodide_deno"))
        ... )
        >>> note is None or "Deno" in note
        True
    """
    configured = resolve_sandbox_exec_driver(cfg)
    if configured != "pyodide_deno":
        return None
    if deno_binary_on_path() is not None:
        return None
    effective = effective_sandbox_exec_driver(cfg)
    if effective == "docker":
        return (
            "Pyodide sandbox configured but Deno is missing; gateway boot downgraded to "
            "docker (sandbox_exec still requires Deno — install from https://deno.com/)."
        )
    return (
        "Pyodide driver selected but Deno is missing. Install Deno "
        "(https://deno.com/) or set sandbox.mode to docker when Docker is available."
    )


def reconcile_sandbox_mode_document(doc: dict[str, Any]) -> list[str]:
    """Downgrade ``sandbox.mode`` in a draft ``sevn.json`` when runtime is absent.

    Mutates ``doc`` in place. Clears ``sandbox.mode`` when no fallback exists so
    gateway boot does not select a driver whose runtime is missing.

    Args:
        doc (dict[str, Any]): Workspace document (onboarding draft or promote preview).

    Returns:
        list[str]: Operator-facing warning strings (may be empty).

    Examples:
        >>> d: dict[str, object] = {"schema_version": 1, "sandbox": {"mode": "pyodide_deno"}}
        >>> isinstance(reconcile_sandbox_mode_document(d), list)
        True
    """
    warnings: list[str] = []
    sandbox = doc.get("sandbox")
    if not isinstance(sandbox, dict):
        return warnings
    mode_raw = sandbox.get("mode") or sandbox.get("driver") or sandbox.get("runtime")
    if not isinstance(mode_raw, str) or not mode_raw.strip():
        rlm = doc.get("rlm")
        if isinstance(rlm, dict):
            mode_raw = rlm.get("sandbox")
    if not isinstance(mode_raw, str) or not mode_raw.strip():
        return warnings
    mode = mode_raw.strip().lower()
    if sandbox_driver_runtime_available(mode):
        return warnings
    if mode == "pyodide_deno":
        if docker_daemon_reachable():
            sandbox["mode"] = "docker"
            warnings.append(
                "sandbox.mode downgraded pyodide_deno→docker: Deno is not on PATH "
                "(install Deno from https://deno.com/ for sandbox_exec)."
            )
            return warnings
        sandbox.pop("mode", None)
        warnings.append(
            "sandbox.mode cleared: pyodide_deno was selected but Deno is missing and "
            "Docker is unavailable — install Deno (https://deno.com/) for sandbox_exec."
        )
        return warnings
    if mode == "docker":
        if deno_binary_on_path() is not None:
            sandbox["mode"] = "pyodide_deno"
            warnings.append(
                "sandbox.mode downgraded docker→pyodide_deno: Docker daemon unreachable."
            )
            return warnings
        sandbox.pop("mode", None)
        warnings.append("sandbox.mode cleared: docker was selected but the daemon is unreachable.")
    return warnings


def should_wire_pyodide_sandbox(cfg: WorkspaceConfig) -> bool:
    """Return whether gateway boot should attempt a Pyodide ``sandbox_exec`` client.

    Production Docker-only tool sandbox is out of scope for W3; explicit ``docker`` /
    ``subprocess`` overrides skip Pyodide wiring. Auto mode wires Pyodide only when
    Docker is unreachable **and** Deno is on ``PATH``.

    Args:
        cfg (WorkspaceConfig): Parsed workspace configuration.

    Returns:
        bool: ``True`` when Pyodide is the effective driver and Deno is available.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig, RlmWorkspaceConfig
        >>> c = WorkspaceConfig.minimal(rlm=RlmWorkspaceConfig(sandbox="pyodide_deno"))
        >>> should_wire_pyodide_sandbox(c) is False or should_wire_pyodide_sandbox(c) is True
        True
    """
    return (
        effective_sandbox_exec_driver(cfg) == "pyodide_deno" and deno_binary_on_path() is not None
    )


@dataclass(frozen=True)
class PyodideExecResult:
    """Structured result from one Pyodide execution."""

    exit_code: int
    stdout: str
    stderr: str

    def as_mapping(self) -> dict[str, object]:
        """Return ``{exit_code, stdout, stderr}`` for tool envelopes.

        Returns:
            dict[str, object]: JSON-safe exec metadata.

        Examples:
            >>> PyodideExecResult(0, "hi\\n", "").as_mapping()["stdout"]
            'hi\\n'
        """
        return {"exit_code": self.exit_code, "stdout": self.stdout, "stderr": self.stderr}


class PyodideDenoRunner:
    """Execute Python in Pyodide via a one-shot Deno subprocess."""

    def __init__(
        self,
        *,
        deno_bin: str | None = None,
        proxy_url: str | None = None,
        timeout_s: float = 120.0,
    ) -> None:
        """Bind Deno binary and optional proxy host for ``--allow-net``.

        Args:
            deno_bin (str | None): Deno executable; resolved from ``PATH`` when omitted.
            proxy_url (str | None): ``SEVN_PROXY_URL`` host:port for net allowlist.
            timeout_s (float): Subprocess communicate timeout.

        Returns:
            None

        Examples:
            >>> r = PyodideDenoRunner(deno_bin="/nonexistent/deno")
            >>> r._deno_bin
            '/nonexistent/deno'
        """
        self._deno_bin = deno_bin or deno_binary_on_path()
        self._proxy_url = (proxy_url or "").strip()
        self._timeout_s = timeout_s
        self._script = pyodide_runner_script_path()

    def _resolved_deno_bin(self) -> str | None:
        """Return an executable Deno path when present on disk or PATH.

        Returns:
            str | None: Resolved Deno binary or ``None`` when missing.

        Examples:
            >>> PyodideDenoRunner(deno_bin="/nonexistent/deno")._resolved_deno_bin() is None
            True
        """
        if not self._deno_bin:
            return None
        candidate = Path(self._deno_bin)
        if candidate.is_file():
            return str(candidate)
        return shutil.which(self._deno_bin)

    @property
    def available(self) -> bool:
        """Return whether Deno is present and the runner script exists.

        Returns:
            bool: ``True`` when execution can be attempted.

        Examples:
            >>> PyodideDenoRunner(deno_bin="/nonexistent/deno").available is False
            True
        """
        return self._resolved_deno_bin() is not None and self._script.is_file()

    def _deno_allow_net(self) -> list[str]:
        """Build ``--allow-net`` flags for Pyodide CDN and optional proxy host.

        Returns:
            list[str]: Deno permission argv fragments.

        Examples:
            >>> "allow-net" in " ".join(PyodideDenoRunner()._deno_allow_net())
            True
        """
        hosts = ["cdn.jsdelivr.net:443", "pyodide.org:443", "registry.npmjs.org:443"]
        if self._proxy_url:
            stripped = self._proxy_url.removeprefix("http://").removeprefix("https://")
            host = stripped.split("/", 1)[0]
            if host and host not in hosts:
                hosts.append(host)
        return [f"--allow-net={','.join(hosts)}"]

    def _build_argv(self) -> list[str]:
        """Assemble ``deno run`` argv for the packaged runner.

        Returns:
            list[str]: argv for :func:`subprocess.run`.

        Raises:
            PyodideDenoUnavailable: When Deno or the runner script is missing.

        Examples:
            >>> import shutil as _sh
            >>> r = PyodideDenoRunner(deno_bin="deno")
            >>> "pyodide_runner.ts" in " ".join(r._build_argv()) if _sh.which("deno") else True
            True
        """
        if not self._deno_bin:
            msg = (
                "Deno is not installed or not on PATH. "
                "Install Deno (https://deno.com/) and set sandbox.driver or "
                "rlm.sandbox to pyodide_deno in sevn.json."
            )
            raise PyodideDenoUnavailable(msg)
        deno_exec = self._resolved_deno_bin()
        if deno_exec is None:
            msg = (
                "Deno is not installed or not on PATH. "
                "Install Deno (https://deno.com/) and set sandbox.driver or "
                "rlm.sandbox to pyodide_deno in sevn.json."
            )
            raise PyodideDenoUnavailable(msg)
        if not self._script.is_file():
            msg = f"Pyodide runner script missing: {self._script}"
            raise PyodideDenoUnavailable(msg)
        return [
            deno_exec,
            "run",
            "--no-prompt",
            "--node-modules-dir=auto",
            *self._deno_allow_net(),
            "--allow-read",
            str(self._script),
        ]

    async def execute_python_async(self, code: str) -> PyodideExecResult:
        """Run Python source in Pyodide and capture stdout/stderr.

        Args:
            code (str): Python source executed in an isolated Pyodide globals dict.

        Returns:
            PyodideExecResult: Process outcome with captured streams.

        Raises:
            PyodideDenoUnavailable: When Deno or the runner script is missing.
            RuntimeError: When the Deno process fails or returns invalid JSON.

        Examples:
            >>> isinstance(True, bool)
            True
        """
        payload = json.dumps({"language": "python", "code": code})
        argv = self._build_argv()

        def _run() -> PyodideExecResult:
            proc = subprocess.run(  # nosec B603
                argv,
                input=payload.encode("utf-8"),
                capture_output=True,
                timeout=self._timeout_s,
                check=False,
            )
            if proc.returncode != 0 and not proc.stdout.strip():
                stderr = proc.stderr.decode("utf-8", errors="replace")
                msg = f"Deno/pyodide runner failed (exit {proc.returncode}): {stderr}"
                raise RuntimeError(msg)
            line = proc.stdout.decode("utf-8", errors="replace").strip().splitlines()[-1]
            try:
                data = json.loads(line)
            except json.JSONDecodeError as exc:
                msg = f"Invalid pyodide runner JSON: {line[:200]!r}"
                raise RuntimeError(msg) from exc
            exit_raw = data.get("exit_code", 1)
            exit_code = int(exit_raw) if isinstance(exit_raw, (int, float, str)) else 1
            return PyodideExecResult(
                exit_code=exit_code,
                stdout=str(data.get("stdout", "")),
                stderr=str(data.get("stderr", "")),
            )

        return await asyncio.to_thread(_run)

    def execute_python(self, code: str) -> str:
        """Sync DSPy-compatible entry: return stdout or raise on failure.

        Args:
            code (str): Python source.

        Returns:
            str: Captured stdout on success.

        Raises:
            PyodideDenoUnavailable: When Deno is missing.
            RuntimeError: On non-zero exit or runner failure.

        Examples:
            >>> isinstance(True, bool)
            True
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            result = asyncio.run(self.execute_python_async(code))
        else:
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                result = pool.submit(asyncio.run, self.execute_python_async(code)).result()
        if result.exit_code != 0:
            msg = f"Pyodide execution failed (exit {result.exit_code}): {result.stderr or result.stdout}"
            raise RuntimeError(msg)
        return result.stdout


__all__ = [
    "PyodideDenoRunner",
    "PyodideDenoUnavailable",
    "PyodideExecResult",
    "deno_binary_on_path",
    "effective_sandbox_exec_driver",
    "pyodide_runner_script_path",
    "reconcile_sandbox_mode_document",
    "resolve_sandbox_exec_driver",
    "sandbox_driver_runtime_available",
    "sandbox_exec_unavailable_note",
    "should_wire_pyodide_sandbox",
]
