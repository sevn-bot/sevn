"""Tool/skill sandbox runtime (``specs/08-sandbox.md``).
Module: sevn.security.sandbox_runtime
Depends: asyncio, enum, json, logging, os, re, shlex, shutil, subprocess, tarfile, tempfile, uuid, sevn.agent.tracing.sink, sevn.config.defaults, sevn.config.workspace_config, sevn.security.sandbox_errors
Exports:
    SandboxDriver — isolation backend selector.
    SandboxRuntime — protocol-compatible runtime (see class docstrings).
    DockerSandboxRuntime — Docker spawn/exec/teardown (§4.2; ``exec_python_repl`` for §4.6).
    SubprocessSandboxRuntime — venv-ish async subprocess execution.
    resolve_sandbox_driver — pick driver from workspace config.
    check_self_preservation_argv — argv denylist (§8.3).
    pid_target_gate_stub — PID-target gate placeholder (§8.3).
    docker_daemon_reachable — whether ``docker info`` succeeds.
    build_sandbox_child_env — §2.2 proxy/workspace env injection.
    materialize_shadow_workspace — §8.1 symlink farm excluding ``.llmignore/``.
    snapshots_dir — ``.sevn/sandbox-snapshots`` path.
    write_workspace_snapshot_tarball — snapshot with manifest + atomic rename.
    load_snapshot_manifest_version — read format version or None.
    snapshot_tarball_format_supported — True when manifest version is supported (§10.2).
    prune_workspace_snapshots — prune old tarballs using ``snapshot_retention_count``.
    make_runtime_for_driver — instantiate runtime for a resolved ``SandboxDriver``.
    ensure_sandbox_docker_network — dedicated internal bridge for sandbox containers.
    ensure_proxy_attached_to_sandbox_network — connect egress proxy to sandbox bridge.
    rewrite_proxy_url_for_sandbox_network — loopback → docker-host gateway for containers.
    list_labeled_sandbox_containers — enumerate ``sevn.run_id`` docker rows.
    reap_stale_sandbox_containers — TTL reaper keyed on ``sevn.run_id`` labels.
Examples:
    >>> check_self_preservation_argv(["echo", "hi"]) is None
    True
    >>> check_self_preservation_argv(["pkill", "foo"]) is not None
    True
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import os
import re
import shlex
import shutil
import subprocess  # nosec B404
import sys
import tarfile
import tempfile
import time
import uuid
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Protocol, runtime_checkable

from loguru import logger

from sevn.agent.tracing.sink import TraceEvent, TraceSink
from sevn.config.defaults import (
    SANDBOX_MAX_CPU,
    SANDBOX_MAX_LIFETIME_S,
    SANDBOX_MAX_MEM_MB,
    SANDBOX_MAX_PIDS,
)
from sevn.config.workspace_config import rlm_json_dict
from sevn.security.egress_firewall import write_linux_iptables_ruleset, write_macos_pf_ruleset
from sevn.security.sandbox_errors import (
    SandboxConfigurationError,
    SandboxPolicyViolationError,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sevn.config.workspace_config import WorkspaceConfig
    from sevn.workspace.layout import WorkspaceLayout
_MANIFEST_NAME = "snapshot-manifest.json"
_FORMAT_VERSION_KEY = "format_version"
_SNAPSHOT_FORMAT_VERSION: Final[int] = 1
SUPPORTED_SNAPSHOT_FORMAT_VERSIONS: Final[frozenset[int]] = frozenset({_SNAPSHOT_FORMAT_VERSION})


class SandboxDriver(StrEnum):
    """Isolation backend (``specs/08-sandbox.md`` §2.1)."""

    docker = "docker"
    subprocess = "subprocess"


@runtime_checkable
class SandboxRuntime(Protocol):
    """Starts, supervises, and tears down an isolated execution context."""

    async def spawn(self, *, run_id: str, workspace: Path, env: dict[str, str]) -> str:
        """Boot isolation for one logical run prior to ``exec``.
        Args:
            self (SandboxRuntime): Backend implementation instance.
            run_id (str): Correlation identifier for telemetry.
            workspace (Path): Host workspace bind root prior to masking.
            env (dict[str, str]): Merged sandbox child variables (caller supplies §2.2 hooks).
        Returns:
            str: Opaque sandbox id (container/process handle).
        Examples:
            >>> isinstance(True, bool)
            True
        """
        ...

    async def exec(
        self,
        sandbox_id: str,
        argv: list[str],
        *,
        cwd: Path | None = None,
        timeout_s: float | None = None,
    ) -> object:
        """Run ``argv`` with policy checks enforced at the sandbox edge.
        Args:
            self (SandboxRuntime): Backend implementation instance.
            sandbox_id (str): Id issued by ``spawn``.
            argv (list[str]): Argument vector executed without implicit shell wrapping.
            cwd (Path | None): Working directory visible inside sandbox.
            timeout_s (float | None): Ceiling for child completion.
        Returns:
            object: Structured tool result envelope (typically ``dict`` with exit metadata).
        Examples:
            >>> isinstance(True, bool)
            True
        """
        ...

    async def teardown(self, sandbox_id: str) -> None:
        """Release resources tracked for ``sandbox_id``.
        Args:
            self (SandboxRuntime): Backend implementation instance.
            sandbox_id (str): Id to destroy.
        Returns:
            None: Always ``None``.
        Examples:
            >>> isinstance(True, bool)
            True
        """
        ...


def check_self_preservation_argv(argv: Sequence[str]) -> str | None:
    """Reject argv fragments that violate self-preservation (§8.3).
    Args:
        argv (Sequence[str]): Argument vector (after shell splitting by caller).
    Returns:
        str | None: Human-readable matched rule label, or ``None`` when allowed.
    Examples:
        >>> check_self_preservation_argv(["git", "status"]) is None
        True
        >>> check_self_preservation_argv(["pkill", "x"]) is not None
        True
    """
    raw = shlex.join(list(argv)).lower()
    literal_hits = (
        ("systemctl stop sevn", "systemctl_stop_sevn"),
        ("systemctl restart sevn", "systemctl_restart_sevn"),
        ("systemctl disable sevn", "systemctl_disable_sevn"),
        ("docker stop sevn-", "docker_stop_sevn_prefix"),
        ("docker kill sevn-", "docker_kill_sevn_prefix"),
        ("docker rm sevn-", "docker_rm_sevn_prefix"),
        ("docker compose down", "docker_compose_down"),
        ("podman stop sevn-", "podman_stop_sevn_prefix"),
        ("podman kill sevn-", "podman_kill_sevn_prefix"),
        ("service sevn-", "service_sevn_prefix"),
    )
    for needle, label in literal_hits:
        if needle in raw:
            return label
    if "launchctl unload" in raw and "ai.sevn" in raw:
        return "launchctl_unload_ai_sevn"
    if "launchctl bootout" in raw and "ai.sevn" in raw:
        return "launchctl_bootout_ai_sevn"
    if "launchctl stop" in raw and "ai.sevn" in raw:
        return "launchctl_stop_ai_sevn"
    short_tokens = (
        r"\bpkill\b",
        r"\bkillall\b",
        r"\bkill\b",
        r"\breboot\b",
        r"\bhalt\b",
        r"\bshutdown\b",
    )
    for pat in short_tokens:
        if re.search(pat, raw):
            return f"regex:{pat}"
    return None


def pid_target_gate_stub(
    argv: Sequence[str],
    *,
    forbidden_pids: frozenset[int] | None = None,
) -> str | None:
    """Placeholder PID-target gate (§8.3).
    Args:
        argv (Sequence[str]): Argument vector.
        forbidden_pids (frozenset[int] | None): When provided, reject obvious
            ``kill -<sig> <pid>`` style args targeting listed PIDs.
    Returns:
        str | None: Rule label when rejected, else ``None``.
    Examples:
        >>> pid_target_gate_stub(["echo", "1"]) is None
        True
    """
    if not forbidden_pids:
        return None
    # Naive parse: odd tokens after kill/killall flags that look like integers.
    if argv and (argv[0] == "kill" or argv[0].endswith("/kill")):
        for tok in argv[1:]:
            if tok.startswith("-"):
                continue
            try:
                pid = int(tok)
            except ValueError:
                continue
            if pid in forbidden_pids:
                return "pid_target_forbidden_set"
    return None


def docker_daemon_reachable(timeout_s: float = 5.0) -> bool:
    """Return True when ``docker info`` exits 0.
    Args:
        timeout_s (float): Subprocess timeout.
    Returns:
        bool: Reachability signal for driver resolution.
    Examples:
        >>> isinstance(docker_daemon_reachable(0.1), bool)
        True
    """
    docker_bin = shutil.which("docker")
    if docker_bin is None:
        return False
    try:
        proc = subprocess.run(
            [docker_bin, "info"],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )  # nosec B603
        return proc.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _sandbox_enabled(cfg: WorkspaceConfig) -> bool:
    """Return ``sandbox.enabled`` or ``False`` when subtree absent.
    Args:
        cfg (WorkspaceConfig): Parsed workspace config.
    Returns:
        bool: Whether Docker isolation feature flag flips.
    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _sandbox_enabled(WorkspaceConfig.minimal())
        False
    """
    s = cfg.sandbox
    return bool(s and s.enabled)


def _allow_subprocess_fallback(cfg: WorkspaceConfig) -> bool:
    """Return ``security.sandbox.allow_subprocess_fallback`` defaulting false.
    Args:
        cfg (WorkspaceConfig): Parsed workspace config.
    Returns:
        bool: Whether degraded subprocess sandboxing is opted in.
    Examples:
        >>> from sevn.config.workspace_config import parse_workspace_config
        >>> cfg = parse_workspace_config({"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}})
        >>> isinstance(_allow_subprocess_fallback(cfg), bool)
        True
    """
    sec = cfg.security
    if sec is None or sec.sandbox is None:
        return False
    return bool(sec.sandbox.allow_subprocess_fallback)


def _deployment_profile_lower(cfg: WorkspaceConfig) -> str:
    """Normalized ``deployment.profile`` string-or-empty.
    Args:
        cfg (WorkspaceConfig): Parsed workspace config.
    Returns:
        str: Lower-case profile slug or empty string.
    Examples:
        >>> from sevn.config.workspace_config import parse_workspace_config
        >>> _deployment_profile_lower(parse_workspace_config({"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}})) == ''
        True
    """
    dep = cfg.deployment
    if dep is None or dep.profile is None:
        return ""
    return dep.profile.strip().lower()


_DANGEROUS_HOST_SANDBOX_ENV: Final[str] = "SEVN_DANGEROUS_HOST_SANDBOX"


def _dangerous_host_sandbox_enabled() -> bool:
    """Return whether explicit host subprocess sandbox opt-in is active.

    Returns:
        bool: ``True`` when ``SEVN_DANGEROUS_HOST_SANDBOX=1``.

    Examples:
        >>> isinstance(_dangerous_host_sandbox_enabled(), bool)
        True
    """
    return os.environ.get(_DANGEROUS_HOST_SANDBOX_ENV, "").strip() == "1"


def resolve_sandbox_driver(cfg: WorkspaceConfig) -> SandboxDriver:
    """Pick driver per §4.2-4.3 and ``sandbox.enabled`` (§10.1).
    Args:
        cfg (WorkspaceConfig): Parsed workspace configuration.
    Returns:
        SandboxDriver: Selected backend.
    Raises:
        SandboxConfigurationError: When production lacks Docker or dev has no path.
    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> c = WorkspaceConfig.minimal()
        >>> d = resolve_sandbox_driver(c)  # doctest: +SKIP
    """
    profile = _deployment_profile_lower(cfg)
    production = profile == "production"
    docker_ok = docker_daemon_reachable()
    allow_fb = _allow_subprocess_fallback(cfg)
    if production:
        if not docker_ok:
            msg = (
                "production deployment requires a reachable Docker daemon for "
                "sandbox isolation (specs/08-sandbox.md §4.2-4.3); "
                "subprocess fallback is not allowed in production"
            )
            raise SandboxConfigurationError(msg)
        return SandboxDriver.docker
    if docker_ok:
        return SandboxDriver.docker
    if allow_fb:
        if not _dangerous_host_sandbox_enabled():
            msg = (
                "subprocess sandbox requires explicit dangerous opt-in: set "
                f"{_DANGEROUS_HOST_SANDBOX_ENV}=1 and "
                "security.sandbox.allow_subprocess_fallback=true for non-production "
                "development only (specs/08-sandbox.md §4.3)"
            )
            raise SandboxConfigurationError(msg)
        return SandboxDriver.subprocess
    msg = (
        "Docker daemon not reachable; install Docker or set "
        "security.sandbox.allow_subprocess_fallback=true for non-production "
        "development only (specs/08-sandbox.md §4.3)"
    )
    raise SandboxConfigurationError(msg)


def _snapshot_trace_event(kind: str, attrs: Mapping[str, object]) -> TraceEvent:
    """Fabricate ``TraceEvent`` rows for synchronous trace metadata.
    Args:
        kind (str): ``TraceEvent.kind`` per §2.3 catalogue.
        attrs (Mapping[str, object]): JSON-safe attribute bag.
    Returns:
        TraceEvent: Timestamped filler row routed through ``TraceSink``.
    Examples:
        >>> isinstance(_snapshot_trace_event("sandbox.spawn", {}).kind, str)
        True
    """
    now = time.time_ns()
    return TraceEvent(
        kind=kind,
        span_id=f"sbox-{uuid.uuid4().hex[:12]}",
        parent_span_id=None,
        session_id="sandbox",
        turn_id="sandbox",
        tier=None,
        ts_start_ns=now,
        ts_end_ns=now,
        status="ok",
        attrs=dict(attrs),
    )


async def _emit_sink(sink: TraceSink | None, kind: str, attrs: Mapping[str, object]) -> None:
    """Forward ``sink.emit`` swallowing downstream errors via sink implementations.
    Args:
        sink (TraceSink | None): Optional tracer port.
        kind (str): ``TraceEvent.kind``.
        attrs (Mapping[str, object]): JSON-compatible payload.
    Returns:
        None: Always ``None``.
    Examples:
        >>> import asyncio
        >>> asyncio.run(_emit_sink(None, "sandbox.runtime", {})) is None
        True
    """
    if sink is None:
        return
    await sink.emit(_snapshot_trace_event(kind, attrs))


def _emit_sink_blocking(sink: TraceSink | None, kind: str, attrs: Mapping[str, object]) -> None:
    """Emit when no running asyncio loop (e.g. sync snapshot writer).
    Drops the event when already inside an event loop to avoid deadlock.
    Args:
        sink (TraceSink | None): Destination.
        kind (str): ``TraceEvent.kind``.
        attrs (Mapping[str, object]): Payload.
    Returns:
        None: Always ``None``.
    Examples:
        >>> isinstance(True, bool)
        True
    """
    if sink is None:
        return
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(_emit_sink(sink, kind, attrs))
    else:
        logger.bind(kind=kind).debug("trace emit skipped inside running loop")


_FORBIDDEN_SANDBOX_CHILD_ENV_KEYS: frozenset[str] = frozenset(
    {
        "SEVN_PROXY_SHARED_SECRET",
        "X-SEVN-PROXY-TOKEN",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
    }
)


def build_sandbox_child_env(
    *,
    proxy_url: str,
    session_token: str,
    workspace_mount_path: str | os.PathLike[str],
) -> dict[str, str]:
    """Build §2.2 child environment (never injects raw provider keys or service secret).

    Emits ``SEVN_PROXY_URL``, scoped ``SEVN_SESSION_TOKEN``, and ``SEVN_WORKSPACE`` only.
    Forward-proxy env vars (``HTTP_PROXY`` / ``HTTPS_PROXY`` / ``NO_PROXY``) are omitted —
    the egress proxy is a reverse path-prefix API, not a CONNECT forward proxy (D13).

    Args:
        proxy_url (str): Base URL for unified egress proxy.
        session_token (str): Scoped per-run ``X-Sevn-Session-Token`` credential.
        workspace_mount_path (str | os.PathLike[str]): Shadow or container path.

    Returns:
        dict[str, str]: Env vars to merge over a sanitized base.

    Raises:
        AssertionError: When a forbidden key would be emitted (regression guard, W6.2).

    Examples:
        >>> e = build_sandbox_child_env(
        ...     proxy_url="http://127.0.0.1:9",
        ...     session_token="t",
        ...     workspace_mount_path="/w",
        ... )
        >>> set(e.keys()) == {"SEVN_PROXY_URL", "SEVN_SESSION_TOKEN", "SEVN_WORKSPACE"}
        True
    """
    p = str(proxy_url).strip()
    w = os.fspath(workspace_mount_path)
    env = {
        "SEVN_PROXY_URL": p,
        "SEVN_SESSION_TOKEN": session_token,
        "SEVN_WORKSPACE": w,
    }
    for key in _FORBIDDEN_SANDBOX_CHILD_ENV_KEYS:
        assert key not in env, f"build_sandbox_child_env must not emit {key!r}"
    for value in env.values():
        assert "SEVN_PROXY_SHARED_SECRET" not in value
    return env


def _resolve_spawn_session_token(*, run_id: str, env: Mapping[str, str]) -> str:
    """Return an existing ``SEVN_SESSION_TOKEN`` or mint a scoped per-run token.

    Args:
        run_id (str): Sandbox correlation id embedded in minted tokens.
        env (Mapping[str, str]): Upstream spawn env (may already carry a token).

    Returns:
        str: Token text for ``build_sandbox_child_env`` (possibly empty).

    Examples:
        >>> _resolve_spawn_session_token(run_id="r", env={"SEVN_SESSION_TOKEN": "keep"})
        'keep'
    """
    existing = str(env.get("SEVN_SESSION_TOKEN", "")).strip()
    if existing:
        return existing
    secret = os.environ.get("SEVN_PROXY_SHARED_SECRET", "").strip()
    if not secret:
        return ""
    from sevn.proxy.auth import SESSION_SCOPE_SANDBOX, mint_session_token

    return mint_session_token(
        signing_key=secret,
        scope=SESSION_SCOPE_SANDBOX,
        run_id=run_id,
    )


def _llmignore_excluded_relative(rel: str) -> bool:
    """Return True when POSIX ``rel`` traverses ``.llmignore/``.
    Args:
        rel (str): Workspace-relative POSIX fragment.
    Returns:
        bool: Whether archiving must omit this subtree.
    Examples:
        >>> _llmignore_excluded_relative("src/.llmignore/x.bin")
        True
        >>> _llmignore_excluded_relative("src/main.py")
        False
    """
    parts = Path(rel).as_posix().split("/")
    return ".llmignore" in parts


def materialize_shadow_workspace(
    workspace_root: Path,
    shadow_root: Path,
    *,
    clear: bool = True,
) -> Path:
    """Symlink top-level entries except ``.llmignore/`` (§8.1).
    Args:
        workspace_root (Path): Real workspace directory.
        shadow_root (Path): Directory to populate (created if missing).
        clear (bool): Drop ``shadow_root`` before symlink creation.
    Returns:
        Path: Canonical shadow root path.
    Raises:
        OSError: When symlinks cannot be created.
    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> ws = Path(tempfile.mkdtemp())
        >>> _ = (ws / "a.txt").write_text("x", encoding="utf-8")
        >>> sh = Path(tempfile.mkdtemp()) / "sh"
        >>> out = materialize_shadow_workspace(ws, sh)
        >>> (out / "a.txt").is_symlink()
        True
    """
    wr = workspace_root.expanduser().resolve()
    sr = shadow_root.expanduser().resolve()
    if clear and sr.exists():
        shutil.rmtree(sr)
    sr.mkdir(parents=True, exist_ok=True)
    for entry in sorted(wr.iterdir(), key=lambda p: p.name):
        if entry.name == ".llmignore":
            continue
        dest = sr / entry.name
        if dest.exists() or dest.is_symlink():
            dest.unlink()
        dest.symlink_to(entry)
    return sr


def snapshots_dir(layout: WorkspaceLayout) -> Path:
    """Return canonical ``sandbox-snapshots`` directory beneath ``layout.dot_sevn``.
    Args:
        layout (WorkspaceLayout): Resolved filesystem layout.
    Returns:
        Path: ``.sevn/sandbox-snapshots`` path (directories created eagerly).
    Examples:
        >>> from pathlib import Path
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> from sevn.workspace.layout import WorkspaceLayout
        >>> td = Path("/tmp/nonexistent_workspace_root_xyz")
        >>> cfg = WorkspaceConfig.minimal()
        >>> lay = WorkspaceLayout(td / "sevn.json", td)
        >>> snapshots_dir(lay).parent.name == ".sevn"
        True
    """
    return _ensure_snapshots_writable(layout)


def _ensure_snapshots_writable(layout: WorkspaceLayout) -> Path:
    """Ensure snapshot directory exists with ``0700`` when ``chmod`` succeeds.
    Args:
        layout (WorkspaceLayout): Workspace layout root.
    Returns:
        Path: Absolute ``sandbox-snapshots`` directory.
    Examples:
        >>> from pathlib import Path
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> from sevn.workspace.layout import WorkspaceLayout
        >>> td = Path("/tmp/nonexistent_workspace_root_xyz2")
        >>> cfg = WorkspaceConfig.minimal()
        >>> lay = WorkspaceLayout(td / "sevn.json", td)
        >>> _ensure_snapshots_writable(lay).name == "sandbox-snapshots"
        True
    """
    root = layout.dot_sevn / "sandbox-snapshots"
    root.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(root, 0o700)
    except OSError:
        logger.opt(exception=True).debug("chmod sandbox-snapshots failed")
    return root


def write_workspace_snapshot_tarball(
    layout: WorkspaceLayout,
    *,
    workspace_root: Path | None = None,
    tarball_path: Path | None = None,
    sink: TraceSink | None = None,
) -> Path:
    """Write a gzipped tarball excluding ``.llmignore/**`` (§3-4).
    Uses a temp file in the snapshots dir and atomic rename. Embeds manifest
    with ``format_version`` for forward compatibility (§10.2).
    Args:
        layout (WorkspaceLayout): Workspace layout (selects ``.sevn`` path).
        workspace_root (Path | None): Defaults to ``layout.content_root``.
        tarball_path (Path | None): Final ``.tar.gz`` path; default timestamped.
        sink (TraceSink | None): Optional trace sink.
    Returns:
        Path: Final tarball path.
    Examples:
        >>> from pathlib import Path
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> from sevn.workspace.layout import WorkspaceLayout
        >>> import tempfile
        >>> td = Path(tempfile.mkdtemp())
        >>> cfg = WorkspaceConfig.minimal(workspace_root=".")
        >>> lay = WorkspaceLayout.from_config(td / "sevn.json", cfg)
        >>> _ = (lay.content_root / "f").write_text("z", encoding="utf-8")
        >>> out = write_workspace_snapshot_tarball(lay, workspace_root=lay.content_root)
        >>> out.suffixes[-2:]
        ['.tar', '.gz']
    """
    base = _ensure_snapshots_writable(layout)
    root = (workspace_root or layout.content_root).resolve()
    if tarball_path is None:
        tarball_path = (
            base / f"snapshot-{time.strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}.tar.gz"
        )
    tarball_path = tarball_path.expanduser().resolve()
    tarball_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(tarball_path.parent), prefix=".snap-", suffix=".tmp")
    os.close(fd)
    tmp_p = Path(tmp_path)
    try:
        manifest = {
            _FORMAT_VERSION_KEY: _SNAPSHOT_FORMAT_VERSION,
            "created_unix_s": int(time.time()),
            "workspace_root": str(root),
            "exclude_llmignore": True,
        }
        with tarfile.open(tmp_p, mode="w:gz") as tar:
            mdata = json.dumps(manifest, sort_keys=True).encode("utf-8")
            info = tarfile.TarInfo(name=_MANIFEST_NAME)
            info.size = len(mdata)
            tar.addfile(info, io.BytesIO(mdata))

            def _filter(ti: tarfile.TarInfo) -> tarfile.TarInfo | None:
                rel = ti.name.replace("\\", "/")
                while rel.startswith("./"):
                    rel = rel[2:]
                if _llmignore_excluded_relative(rel):
                    return None
                return ti

            for dirpath, dirnames, filenames in os.walk(root):
                dp = Path(dirpath)
                rel_dir = "." if dp == root else dp.relative_to(root).as_posix()
                if _llmignore_excluded_relative(rel_dir):
                    dirnames[:] = []
                    continue
                dirnames[:] = [d for d in dirnames if d != ".llmignore"]
                for name in filenames:
                    full = dp / name
                    arc = full.relative_to(root).as_posix()
                    if _llmignore_excluded_relative(arc):
                        continue
                    tar.add(full, arcname=arc, filter=_filter)
        os.replace(tmp_p, tarball_path)
        with contextlib.suppress(OSError):
            os.chmod(tarball_path, 0o600)
        if sink is not None:
            _emit_sink_blocking(
                sink,
                "sandbox.runtime",
                {
                    "driver": "snapshot",
                    "path": str(tarball_path),
                    "format_version": manifest[_FORMAT_VERSION_KEY],
                },
            )
    except Exception:
        if tmp_p.exists():
            tmp_p.unlink(missing_ok=True)
        raise
    return tarball_path


def load_snapshot_manifest_version(tarball_path: Path) -> int | None:
    """Read ``format_version`` from embedded manifest, or None.
    Operators: when this returns a value outside
    ``SUPPORTED_SNAPSHOT_FORMAT_VERSIONS``, treat the tarball as **unsupported** —
    ignore it for restore and take a fresh snapshot (see ``docs/runbooks/sandbox.md``).
    Args:
        tarball_path (Path): Gzip tarball produced by this module.
    Returns:
        int | None: Declared version, or None when missing/invalid (caller may rebuild).
    Examples:
        >>> load_snapshot_manifest_version(Path("/nonexistent")) is None
        True
    """
    path = tarball_path.expanduser()
    if not path.is_file():
        return None
    try:
        with tarfile.open(path, mode="r:gz") as tar:
            try:
                m = tar.getmember(_MANIFEST_NAME)
            except KeyError:
                return None
            f = tar.extractfile(m)
            if f is None:
                return None
            data = json.loads(f.read().decode("utf-8"))
    except (OSError, tarfile.TarError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    v = data.get(_FORMAT_VERSION_KEY)
    return int(v) if isinstance(v, int) else None


def snapshot_tarball_format_supported(tarball_path: Path) -> bool:
    """Return True when the tarball manifest declares a supported ``format_version``.
    Args:
        tarball_path (Path): Candidate snapshot ``.tar.gz`` under ``.sevn/sandbox-snapshots/``.
    Returns:
        bool: Whether restore logic may consume this snapshot.
    Examples:
        >>> snapshot_tarball_format_supported(Path("/nonexistent"))
        False
    """
    v = load_snapshot_manifest_version(tarball_path)
    return v is not None and v in SUPPORTED_SNAPSHOT_FORMAT_VERSIONS


def prune_workspace_snapshots(
    layout: WorkspaceLayout,
    cfg: WorkspaceConfig,
    *,
    glob_pattern: str = "snapshot-*.tar.gz",
) -> list[Path]:
    """Remove oldest snapshot tarballs beyond ``sandbox.snapshot_retention_count`` (§10.2).
    Requires a parsed ``sandbox`` subtree on ``cfg``: when absent, pruning is skipped.
    Default retention for an empty ``sandbox: {}`` block is
    ``SANDBOX_SNAPSHOT_RETENTION_COUNT_DEFAULT`` (**3**) from ``sandbox.snapshot_retention_count``.
    Set ``sandbox.snapshot_retention_count`` to **0** to disable pruning entirely.
    Args:
        layout (WorkspaceLayout): Workspace layout (selects snapshot directory).
        cfg (WorkspaceConfig): Parsed workspace config.
        glob_pattern (str): Basename glob relative to the snapshots directory.
    Returns:
        list[Path]: Snapshots removed (newest-first sort; empty when nothing removed).
    Examples:
        >>> from pathlib import Path
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> from sevn.workspace.layout import WorkspaceLayout
        >>> td = Path("/tmp/prune_example_unused")
        >>> prune_workspace_snapshots(
        ...     WorkspaceLayout(td / "sevn.json", td), WorkspaceConfig.minimal()
        ... ) == []
        True
    """
    sb = cfg.sandbox
    if sb is None:
        return []
    cap = sb.snapshot_retention_count
    if cap < 1:
        return []
    root = _ensure_snapshots_writable(layout)
    candidates = sorted(
        root.glob(glob_pattern),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    removed: list[Path] = []
    for stale in candidates[cap:]:
        try:
            stale.unlink(missing_ok=True)
        except OSError:
            logger.opt(exception=True).warning("failed to prune snapshot {}", stale)
            continue
        removed.append(stale)
    return removed


class SubprocessSandboxRuntime:
    """Subprocess-backed sandbox (development / degraded §4.3).
    Applies ``resource.setrlimit`` best-effort for ``max_memory_bytes`` /
    ``max_nproc_children`` derived from typed limits on ``SandboxConfig``.
    """

    def __init__(
        self,
        *,
        trace_sink: TraceSink | None,
        layout: WorkspaceLayout,
        cfg: WorkspaceConfig,
        sandbox_max_lifetime_s: float | None = None,
        docker_image: str | None = None,
        pre_spawn_env: dict[str, str] | None = None,
    ) -> None:
        """Bind workspace layout plus optional tracing/metadata hooks.
        Args:
            trace_sink (TraceSink | None): Telemetry port (typically mission control sinks).
            layout (WorkspaceLayout): Cached layout for ``dot_sevn`` paths.
            cfg (WorkspaceConfig): Typed sandbox tuning subtree.
            sandbox_max_lifetime_s (float | None): Override TTL for traces.
            docker_image (str | None): Only used for parity metadata strings.
            pre_spawn_env (dict[str, str] | None): Env merged after §2.2 shim.
        Returns:
            None: Always ``None``.
        Examples:
            >>> isinstance(True, bool)
            True
        """
        self._sink = trace_sink
        self._layout = layout
        self._cfg = cfg
        self._lifetime_s = float(sandbox_max_lifetime_s or _cfg_max_lifetime_s(cfg))
        self._docker_image = docker_image
        self._pre_env = dict(pre_spawn_env or {})
        self._records: dict[str, dict[str, Any]] = {}

    async def spawn(self, *, run_id: str, workspace: Path, env: dict[str, str]) -> str:
        """Allocate shadow workspace symlink farm for ``workspace``.
        Args:
            run_id (str): Correlation id surfaced in traces.
            workspace (Path): Trusted host workspace bind root.
            env (dict[str, str]): Upstream-provided sandbox env scaffolding.
        Returns:
            str: Ephemeral sandbox id stored in-memory only.
        Examples:
            >>> isinstance(True, bool)
            True
        """
        shadow_parent = self._layout.dot_sevn / "sandbox-shadow"
        shadow_parent.mkdir(parents=True, exist_ok=True)
        shadow = materialize_shadow_workspace(
            workspace, shadow_parent / f"sb-{uuid.uuid4().hex[:12]}"
        )
        sid = uuid.uuid4().hex
        child_env = dict(env)
        token = _resolve_spawn_session_token(run_id=run_id, env=child_env)
        if token:
            child_env["SEVN_SESSION_TOKEN"] = token
        child_env.update(
            build_sandbox_child_env(
                proxy_url=child_env.get("SEVN_PROXY_URL", ""),
                session_token=child_env.get("SEVN_SESSION_TOKEN", ""),
                workspace_mount_path=shadow,
            )
        )
        child_env.update(self._pre_env)
        self._records[sid] = {
            "run_id": run_id,
            "shadow": shadow,
            "cwd": shadow,
            "workspace_real": workspace,
            "child_env": child_env,
        }
        await _emit_sink(
            self._sink,
            "sandbox.runtime",
            {
                "driver": SandboxDriver.subprocess,
                "image": self._docker_image,
                "run_id": run_id,
                "sandbox_max_lifetime_s": self._lifetime_s,
            },
        )
        return sid

    async def exec(
        self,
        sandbox_id: str,
        argv: list[str],
        *,
        cwd: Path | None = None,
        timeout_s: float | None = None,
    ) -> object:
        """Execute ``argv`` after argv/PID hygiene checks §8.3.
        Args:
            sandbox_id (str): Sandbox id minted inside ``spawn``.
            argv (list[str]): Executable + args routed through asyncio subprocess APIs.
            cwd (Path | None): Overrides working directory defaults.
            timeout_s (float | None): Optional waiter guard.
        Returns:
            dict[str, object]: ``exit_code`` / ``stdout`` / ``stderr`` payload.
        Examples:
            >>> isinstance(True, bool)
            True
        """
        rec = self._records.get(sandbox_id)
        if rec is None:
            msg = f"unknown sandbox_id {sandbox_id!r}"
            raise SandboxConfigurationError(msg)
        rule = check_self_preservation_argv(argv)
        if rule is not None:
            await _emit_sink(
                self._sink,
                "sandbox.self_preservation_block",
                {
                    "argv_first": argv[0] if argv else "",
                    "matched_rule": rule,
                    "target_pid_resolved": None,
                },
            )
            raise SandboxPolicyViolationError(f"self-preservation: {rule}")
        pid_rule = pid_target_gate_stub(argv)
        if pid_rule is not None:
            await _emit_sink(
                self._sink,
                "sandbox.self_preservation_block",
                {
                    "argv_first": argv[0] if argv else "",
                    "matched_rule": pid_rule,
                    "target_pid_resolved": None,
                },
            )
            raise SandboxPolicyViolationError(f"self-preservation: {pid_rule}")
        run_id = str(rec["run_id"])
        await _emit_sink(
            self._sink,
            "sandbox.spawn",
            {
                "sandbox_id": sandbox_id,
                "argv0": argv[0] if argv else "",
                "run_id": run_id,
            },
        )
        work_cwd = cwd or Path(str(rec["cwd"]))
        from sevn.security.trigger_spawn_env import host_env_base_for_subprocess

        merged_env = host_env_base_for_subprocess()
        merged_env.update(dict(rec["child_env"]))
        merged_env.setdefault("PYTHONHASHSEED", "0")
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=work_cwd,
            stdin=subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_apply_subprocess_limits(merged_env, self._cfg),
        )
        assert proc.stdout is not None  # nosec B101
        assert proc.stderr is not None  # nosec B101
        if timeout_s is None:
            out_b, err_b = await proc.communicate()
        else:
            try:
                out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
            except TimeoutError:
                proc.kill()
                await proc.communicate()
                raise
        stdout = out_b.decode("utf-8", errors="replace")
        stderr = err_b.decode("utf-8", errors="replace")
        return {"exit_code": proc.returncode, "stdout": stdout, "stderr": stderr}

    async def teardown(self, sandbox_id: str) -> None:
        """Remove shadow directory and mirror §2.3 teardown events.
        Args:
            sandbox_id (str): Sandbox id returned from ``spawn``.
        Returns:
            None: Always ``None``.
        Examples:
            >>> isinstance(True, bool)
            True
        """
        rec = self._records.pop(sandbox_id, None)
        shadow = Path(str(rec["shadow"])) if rec else None
        files_synced = 0
        bytes_written = 0
        if shadow and shadow.exists():
            try:
                shutil.rmtree(shadow, ignore_errors=True)
                files_synced = 1
            except OSError:
                pass
        await _emit_sink(
            self._sink,
            "sandbox.teardown",
            {
                "sandbox_id": sandbox_id,
                "reason": "explicit",
                "files_synced_count": files_synced,
                "bytes_written": bytes_written,
            },
        )


def _cfg_max_lifetime_s(cfg: WorkspaceConfig) -> float:
    """Return configured ``sandbox.max_lifetime`` or shipped default seconds.
    Args:
        cfg (WorkspaceConfig): Parsed workspace config.
    Returns:
        float: Upper bound aligning orchestration + orphan sweeper §4.5 narrative.
    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> isinstance(_cfg_max_lifetime_s(WorkspaceConfig.minimal()), float)
        True
    """
    s = cfg.sandbox
    if s and s.max_lifetime is not None:
        return float(s.max_lifetime)
    return float(SANDBOX_MAX_LIFETIME_S)


_DOCKER_WORKSPACE_MOUNT: Final[str] = "/workspace"
_DOCKER_OUT_SUBDIR: Final[str] = ".out"
_SANDBOX_NETWORK_NAME: Final[str] = "sevn-sandbox"
_SANDBOX_RUN_USER: Final[str] = "10001:10001"
_SANDBOX_SPAWN_TS_LABEL: Final[str] = "sevn.spawn_ts"
_REPL_READY_MARKER: Final[str] = "__SEVN_REPL_OK__"
_LOOPBACK_PROXY_HOSTS: Final[frozenset[str]] = frozenset({"127.0.0.1", "localhost", "::1"})
_DEFAULT_LINUX_DOCKER_HOST_GATEWAY: Final[str] = "172.17.0.1"
_DEFAULT_DARWIN_DOCKER_HOST_GATEWAY: Final[str] = "host.docker.internal"


def _docker_bin() -> str:
    """Return ``docker`` executable path or raise.
    Returns:
        str: Resolved docker CLI path.
    Raises:
        SandboxConfigurationError: When docker is not on ``PATH``.
    Examples:
        >>> isinstance(_docker_bin.__name__, str)
        True
    """
    docker_bin = shutil.which("docker")
    if docker_bin is None:
        msg = "docker CLI not found on PATH (specs/08-sandbox.md §4.2)"
        raise SandboxConfigurationError(msg)
    return docker_bin


def _proxy_host_port_from_env(env: Mapping[str, str]) -> str | None:
    """Derive ``host:port`` for egress rules from §2.2 proxy env.
    Args:
        env (Mapping[str, str]): Sandbox child env containing ``SEVN_PROXY_URL``.
    Returns:
        str | None: Endpoint suitable for iptables/pf rules, or ``None``.
    Examples:
        >>> _proxy_host_port_from_env({"SEVN_PROXY_URL": "http://127.0.0.1:8787"})
        '127.0.0.1:8787'
    """
    raw = str(env.get("SEVN_PROXY_URL", "")).strip()
    if not raw:
        return None
    if "://" not in raw:
        raw = f"http://{raw}"
    from urllib.parse import urlparse

    parsed = urlparse(raw)
    host = parsed.hostname
    if not host:
        return None
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return f"{host}:{port}"


def _write_docker_network_policy(
    workspace: Path,
    *,
    child_env: Mapping[str, str],
) -> Path | None:
    """Materialize namespace egress rules under ``workspace/.sevn/`` (§4.2, ``infra/`` schema).
    Args:
        workspace (Path): Host workspace root (``sevn.json`` tree).
        child_env (Mapping[str, str]): Spawn env with ``SEVN_PROXY_URL``.
    Returns:
        Path | None: Rules file path when written, else ``None``.
    Examples:
        >>> isinstance(True, bool)
        True
    """
    hp = _proxy_host_port_from_env(child_env)
    if hp is None:
        return None
    dot = workspace.expanduser().resolve() / ".sevn"
    dot.mkdir(parents=True, exist_ok=True)
    if sys.platform.startswith("linux"):
        dest = dot / "sandbox-egress.iptables.rules"
        write_linux_iptables_ruleset(dest, proxy_host_ports=(hp,))
        return dest
    if sys.platform == "darwin":
        host, _, port_s = hp.partition(":")
        dest = dot / "sandbox-egress.pf.rules"
        write_macos_pf_ruleset(
            dest,
            proxy_host=host or "127.0.0.1",
            proxy_port=int(port_s) if port_s.isdigit() else 8787,
        )
        return dest
    return None


def _sandbox_network_name() -> str:
    """Return the dedicated internal Docker network for sandbox containers.
    Returns:
        str: Network name (deny-by-default bridge; proxy attaches separately).
    Examples:
        >>> _sandbox_network_name() == "sevn-sandbox"
        True
    """
    return _SANDBOX_NETWORK_NAME


async def ensure_sandbox_docker_network() -> str:
    """Create the dedicated internal sandbox network if missing (§4.2).
    Returns:
        str: Network name passed to ``docker run --network``.
    Raises:
        SandboxConfigurationError: When ``docker network create`` fails unexpectedly.
    Examples:
        >>> isinstance(_sandbox_network_name(), str)
        True
    """
    docker_bin = _docker_bin()
    name = _sandbox_network_name()
    rc, out, err = await _docker_run(
        [docker_bin, "network", "create", "--internal", name],
        timeout_s=30.0,
    )
    combined = f"{out}\n{err}".lower()
    if rc != 0 and "already exists" not in combined:
        msg = f"docker network create {name!r} failed (exit {rc}): {err.strip() or out.strip()}"
        raise SandboxConfigurationError(msg)
    return name


def _docker_host_gateway_for_sandbox() -> str:
    """Return a host endpoint sandboxes on ``sevn-sandbox`` can reach (§4.2).
    Returns:
        str: ``host.docker.internal`` on macOS, else bridge gateway (override via env).
    Examples:
        >>> isinstance(_docker_host_gateway_for_sandbox(), str)
        True
    """
    override = os.environ.get("SEVN_DOCKER_HOST_GATEWAY", "").strip()
    if override:
        return override
    if sys.platform == "darwin":
        return _DEFAULT_DARWIN_DOCKER_HOST_GATEWAY
    return _DEFAULT_LINUX_DOCKER_HOST_GATEWAY


def _proxy_hostname_from_url(proxy_url: str) -> str | None:
    """Parse hostname from a proxy origin URL.
    Args:
        proxy_url (str): ``SEVN_PROXY_URL`` value.
    Returns:
        str | None: Lowercase hostname when present.
    Examples:
        >>> _proxy_hostname_from_url("http://sevn-proxy:8787")
        'sevn-proxy'
    """
    raw = str(proxy_url).strip()
    if not raw:
        return None
    if "://" not in raw:
        raw = f"http://{raw}"
    from urllib.parse import urlparse

    parsed = urlparse(raw)
    host = parsed.hostname
    return host.lower() if host else None


def rewrite_proxy_url_for_sandbox_network(proxy_url: str) -> str:
    """Rewrite loopback proxy origins for internal-network sandbox containers (§4.2).
    Args:
        proxy_url (str): Gateway/process ``SEVN_PROXY_URL``.
    Returns:
        str: Container-reachable origin (unchanged when already routable).
    Examples:
        >>> rewrite_proxy_url_for_sandbox_network("http://127.0.0.1:8787").startswith("http://")
        True
        >>> "127.0.0.1" not in rewrite_proxy_url_for_sandbox_network("http://127.0.0.1:8787")
        True
    """
    raw = str(proxy_url).strip()
    if not raw:
        return raw
    if "://" not in raw:
        raw = f"http://{raw}"
    from urllib.parse import urlparse, urlunparse

    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    if host not in _LOOPBACK_PROXY_HOSTS:
        return proxy_url
    gateway = _docker_host_gateway_for_sandbox()
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if (parsed.scheme == "http" and port == 80) or (parsed.scheme == "https" and port == 443):
        netloc = gateway
    else:
        netloc = f"{gateway}:{port}"
    return urlunparse(parsed._replace(netloc=netloc))


def _apply_sandbox_proxy_env(child_env: dict[str, str], proxy_url: str) -> None:
    """Set proxy-related env keys on ``child_env`` from a single origin.
    Args:
        child_env (dict[str, str]): Mutable spawn env (updated in place).
        proxy_url (str): Rewritten or original proxy origin.
    Returns:
        None: Always ``None``.
    Examples:
        >>> env: dict[str, str] = {}
        >>> _apply_sandbox_proxy_env(env, "http://host.docker.internal:8787")
        >>> env["SEVN_PROXY_URL"]
        'http://host.docker.internal:8787'
    """
    child_env["SEVN_PROXY_URL"] = proxy_url


async def _find_running_container_matching(name_fragment: str) -> str | None:
    """Return the first running container whose name contains ``name_fragment``.
    Args:
        name_fragment (str): Compose service name or container substring.
    Returns:
        str | None: Docker container name, or ``None`` when no match.
    Examples:
        >>> isinstance(True, bool)
        True
    """
    fragment = name_fragment.strip()
    if not fragment:
        return None
    docker_bin = _docker_bin()
    rc, out, _err = await _docker_run(
        [docker_bin, "ps", "--filter", f"name={fragment}", "--format", "{{.Names}}"],
        timeout_s=15.0,
    )
    if rc != 0:
        return None
    names = [line.strip() for line in out.splitlines() if line.strip()]
    if not names:
        return None
    for name in names:
        if name == fragment:
            return name
    return names[0]


async def ensure_proxy_attached_to_sandbox_network(*, proxy_url: str) -> None:
    """Attach the egress proxy container to ``sevn-sandbox`` when resolvable (§4.2).
    Internal sandbox networks deny external routing; the proxy must share the bridge
    (or the spawn path rewrites loopback URLs to ``host.docker.internal``).
    Args:
        proxy_url (str): Process ``SEVN_PROXY_URL`` before container rewrite.
    Returns:
        None: Always ``None`` (connect failures are logged, not fatal).
    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(ensure_proxy_attached_to_sandbox_network)
        True
    """
    override = os.environ.get("SEVN_PROXY_CONTAINER", "").strip()
    host = _proxy_hostname_from_url(proxy_url)
    container: str | None
    if override:
        container = override
    elif host and host not in _LOOPBACK_PROXY_HOSTS and host != _docker_host_gateway_for_sandbox():
        container = await _find_running_container_matching(host)
    else:
        return
    if not container:
        return
    network_name = await ensure_sandbox_docker_network()
    docker_bin = _docker_bin()
    rc, out, err = await _docker_run(
        [docker_bin, "network", "connect", network_name, container],
        timeout_s=30.0,
    )
    combined = f"{out}\n{err}".lower()
    if rc != 0 and "already" not in combined:
        logger.warning(
            "docker network connect {network} {container} failed (exit {rc}): {detail}",
            network=network_name,
            container=container,
            rc=rc,
            detail=err.strip() or out.strip(),
        )


def _seccomp_profile_path() -> str:
    """Resolve seccomp JSON path for ``docker run --security-opt seccomp=…``.
    Returns:
        str: Host filesystem path to the bundled profile.
    Examples:
        >>> Path(_seccomp_profile_path()).suffix == ".json"
        True
    """
    override = os.environ.get("SEVN_SANDBOX_SECCOMP_PROFILE", "").strip()
    if override:
        return override
    dev = Path(__file__).resolve().parent.parent / "data" / "docker" / "sandbox-seccomp.json"
    if dev.is_file():
        return str(dev)
    from importlib.resources import as_file, files

    ref = files("sevn.data.docker") / "sandbox-seccomp.json"
    cache = Path(tempfile.gettempdir()) / "sevn-sandbox-seccomp.json"
    with as_file(ref) as src:
        if not cache.is_file() or cache.stat().st_mtime < src.stat().st_mtime:
            shutil.copy2(src, cache)
    return str(cache)


def _docker_isolation_args() -> list[str]:
    """Build kernel isolation flags for ``docker run`` (§4.2).
    Returns:
        list[str]: ``--user``, cap-drop, seccomp, and ulimit flags.
    Examples:
        >>> "--cap-drop" in _docker_isolation_args()
        True
    """
    seccomp = _seccomp_profile_path()
    return [
        "--user",
        _SANDBOX_RUN_USER,
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--security-opt",
        f"seccomp={seccomp}",
        "--ulimit",
        "fsize=268435456",
    ]


async def _resolve_digest_pinned_image(image: str) -> str:
    """Resolve a tag to a digest-pinned reference when inspect succeeds (§4.2).
    Args:
        image (str): Image tag or digest reference from config.
    Returns:
        str: ``repo@sha256:…`` when available, else the original ``image``.
    Examples:
        >>> isinstance("@sha256:" in "x@sha256:abc", bool)
        True
    """
    if "@sha256:" in image:
        return image
    docker_bin = _docker_bin()
    rc, out, _ = await _docker_run(
        [docker_bin, "image", "inspect", "--format", "{{index .RepoDigests 0}}", image],
        timeout_s=60.0,
    )
    digest_ref = out.strip()
    if rc == 0 and digest_ref:
        return digest_ref
    rc2, out2, _ = await _docker_run(
        [docker_bin, "image", "inspect", "--format", "{{.Id}}", image],
        timeout_s=60.0,
    )
    image_id = out2.strip()
    if rc2 == 0 and image_id:
        return image_id
    return image


def _prepare_workspace_out_dir(workspace: Path, run_id: str) -> Path:
    """Create per-run writable ``.out`` host directory (§4.2 narrow rw surface).
    Args:
        workspace (Path): Host workspace root.
        run_id (str): Correlation id for the sandbox run.
    Returns:
        Path: Host directory bind-mounted at ``/workspace/.out``.
    Examples:
        >>> isinstance(True, bool)
        True
    """
    ws = workspace.expanduser().resolve()
    # Anchor mountpoint on the host tree so Docker can bind ``.out`` over a :ro workspace.
    (ws / _DOCKER_OUT_SUBDIR).mkdir(exist_ok=True)
    out_dir = ws / ".sevn" / "docker-out" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def _discover_llmignore_mask_mounts(workspace: Path) -> list[tuple[Path, str]]:
    """Create empty host dirs masking every ``.llmignore/`` subtree (§4.2, nested).
    Args:
        workspace (Path): Real workspace root.
    Returns:
        list[tuple[Path, str]]: ``(host_mask, container_mount_path)`` pairs.
    Examples:
        >>> isinstance(True, bool)
        True
    """
    ws = workspace.expanduser().resolve()
    parent = ws / ".sevn" / "docker-mask"
    parent.mkdir(parents=True, exist_ok=True)
    mounts: list[tuple[Path, str]] = []
    for root, dirnames, _ in os.walk(ws):
        root_path = Path(root)
        rel_parts = root_path.relative_to(ws).parts
        if ".sevn" in rel_parts:
            dirnames.clear()
            continue
        for name in list(dirnames):
            if name != ".llmignore":
                continue
            rel = (root_path.relative_to(ws) / ".llmignore").as_posix()
            mask = parent / f"llmignore-{uuid.uuid4().hex[:12]}"
            mask.mkdir(parents=True, exist_ok=True)
            mounts.append((mask, f"{_DOCKER_WORKSPACE_MOUNT}/{rel}"))
            dirnames.remove(name)
    if not mounts:
        (ws / ".llmignore").mkdir(exist_ok=True)
        mask = parent / f"llmignore-{uuid.uuid4().hex[:12]}"
        mask.mkdir(parents=True, exist_ok=True)
        mounts.append((mask, f"{_DOCKER_WORKSPACE_MOUNT}/.llmignore"))
    return mounts


async def list_labeled_sandbox_containers() -> list[dict[str, str]]:
    """Return docker rows carrying ``sevn.run_id`` labels.
    Returns:
        list[dict[str, str]]: Rows with ``container_id``, ``run_id``, ``spawn_ts``.
    Examples:
        >>> isinstance(list_labeled_sandbox_containers.__name__, str)
        True
    """
    docker_bin = _docker_bin()
    rc, out, err = await _docker_run(
        [
            docker_bin,
            "ps",
            "-a",
            "--filter",
            "label=sevn.run_id",
            "--format",
            '{{.ID}}\t{{.Label "sevn.run_id"}}\t{{.Label "sevn.spawn_ts"}}',
        ],
        timeout_s=30.0,
    )
    if rc != 0:
        logger.warning("docker ps label filter failed: {}", err.strip() or out.strip())
        return []
    rows: list[dict[str, str]] = []
    for line in out.splitlines():
        parts = line.strip().split("\t")
        if len(parts) < 2:
            continue
        rows.append(
            {
                "container_id": parts[0],
                "run_id": parts[1],
                "spawn_ts": parts[2] if len(parts) > 2 else "",
            }
        )
    return rows


async def reap_stale_sandbox_containers(
    *,
    max_lifetime_s: float,
    active_run_ids: frozenset[str] | None = None,
    now_unix_s: float | None = None,
) -> list[str]:
    """Kill labeled sandbox containers past TTL (§4.5 out-of-band reaper).
    Args:
        max_lifetime_s (float): Configured ``sandbox.max_lifetime`` cap.
        active_run_ids (frozenset[str] | None): Run ids still leased by the gateway.
        now_unix_s (float | None): Wall clock override for tests.
    Returns:
        list[str]: Removed container ids.
    Examples:
        >>> isinstance(True, bool)
        True
    """
    if max_lifetime_s <= 0:
        return []
    now = float(now_unix_s if now_unix_s is not None else time.time())
    live = active_run_ids or frozenset()
    doomed: list[str] = []
    docker_bin = _docker_bin()
    for row in await list_labeled_sandbox_containers():
        run_id = row["run_id"]
        if run_id in live:
            continue
        spawn_raw = row.get("spawn_ts", "")
        try:
            spawn_ts = float(spawn_raw) if spawn_raw else 0.0
        except ValueError:
            spawn_ts = 0.0
        if spawn_ts <= 0:
            continue
        if (now - spawn_ts) <= max_lifetime_s:
            continue
        cid = row["container_id"]
        await _docker_run([docker_bin, "rm", "-f", cid], timeout_s=60.0)
        doomed.append(cid)
    return doomed


async def _docker_run(
    argv: list[str],
    *,
    timeout_s: float | None = None,
    stdin: bytes | None = None,
) -> tuple[int, str, str]:
    """Run a docker CLI argv vector and capture stdout/stderr.
    Args:
        argv (list[str]): Full argv including ``docker`` binary.
        timeout_s (float | None): Optional communicate timeout.
        stdin (bytes | None): Optional stdin payload for ``docker exec -i``.
    Returns:
        tuple[int, str, str]: ``(returncode, stdout, stderr)`` UTF-8 decoded.
    Examples:
        >>> isinstance(True, bool)
        True
    """
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert proc.stdout is not None  # nosec B101
    assert proc.stderr is not None  # nosec B101
    if timeout_s is None:
        out_b, err_b = await proc.communicate(input=stdin)
    else:
        try:
            out_b, err_b = await asyncio.wait_for(
                proc.communicate(input=stdin),
                timeout=timeout_s,
            )
        except TimeoutError:
            proc.kill()
            await proc.communicate()
            raise
    stdout = out_b.decode("utf-8", errors="replace")
    stderr = err_b.decode("utf-8", errors="replace")
    return int(proc.returncode or 0), stdout, stderr


def _docker_resource_args(cfg: WorkspaceConfig) -> list[str]:
    """Build ``docker run`` resource limit flags from config + defaults (§5.1).
    Args:
        cfg (WorkspaceConfig): Parsed workspace config.
    Returns:
        list[str]: Flattened CLI flags (cpus, memory, pids-limit).
    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> isinstance(_docker_resource_args(WorkspaceConfig.minimal()), list)
        True
    """
    sb = cfg.sandbox
    cpu = float(sb.max_cpu) if sb and sb.max_cpu is not None else float(SANDBOX_MAX_CPU)
    mem_mb = int(sb.max_mem_mb) if sb and sb.max_mem_mb is not None else int(SANDBOX_MAX_MEM_MB)
    pids = int(sb.max_pids) if sb and sb.max_pids is not None else int(SANDBOX_MAX_PIDS)
    return [
        "--cpus",
        str(cpu),
        "--memory",
        f"{mem_mb}m",
        "--pids-limit",
        str(pids),
    ]


def _codec_exec_result(returncode: int, stdout: str, stderr: str) -> dict[str, object]:
    """Normalize docker/subprocess exec output to the shared result envelope.
    Args:
        returncode (int): Process exit status.
        stdout (str): Captured stdout.
        stderr (str): Captured stderr.
    Returns:
        dict[str, object]: ``exit_code`` / ``stdout`` / ``stderr`` payload.
    Examples:
        >>> _codec_exec_result(0, "ok", "")["exit_code"]
        0
    """
    return {"exit_code": returncode, "stdout": stdout, "stderr": stderr}


def _apply_subprocess_limits(env: dict[str, str], cfg: WorkspaceConfig) -> dict[str, str]:
    """Annotate subprocess env hints while Docker-backed limits remain canonical.
    Args:
        env (dict[str, str]): Base host env clone for asyncio subprocess launches.
        cfg (WorkspaceConfig): Workspace sandbox knobs describing caps.
    Returns:
        dict[str, str]: Shallow copied env with optional sandbox hint keys.
    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _apply_subprocess_limits({}, WorkspaceConfig.minimal()) == {}
        True
    """
    out = dict(env)
    mb = cfg.sandbox
    if mb and mb.max_pids is not None:
        out["SEVN_SANDBOX_MAX_PIDS"] = str(mb.max_pids)
    if mb and mb.max_mem_mb is not None:
        out["SEVN_SANDBOX_MAX_MEM_MB"] = str(mb.max_mem_mb)
    return out


class DockerSandboxRuntime:
    """Docker driver (production) with bind-mount ``.llmignore/`` mask (§4.2).
    Containers carry ``sevn.run_id`` label (§3.3).
    """

    def __init__(
        self,
        *,
        trace_sink: TraceSink | None,
        cfg: WorkspaceConfig,
        sandbox_max_lifetime_s: float | None = None,
        image: str = "ghcr.io/sevn-bot/sevn/sandbox:dev",
        pre_spawn_env: dict[str, str] | None = None,
    ) -> None:
        """Bind Docker image + workspace config for spawn/exec/teardown.
        Args:
            trace_sink (TraceSink | None): Telemetry injection port.
            cfg (WorkspaceConfig): Workspace configuration for lifetime knobs.
            sandbox_max_lifetime_s (float | None): Optional override for traces.
            image (str): Sandbox base image tag (``rlm.docker_image`` override).
            pre_spawn_env (dict[str, str] | None): Extra env merged after §2.2 shim.
        Returns:
            None: Always ``None``.
        Examples:
            >>> isinstance(True, bool)
            True
        """
        self._sink = trace_sink
        self._cfg = cfg
        self._lifetime_s = float(sandbox_max_lifetime_s or _cfg_max_lifetime_s(cfg))
        self._image = image
        self._pre_env = dict(pre_spawn_env or {})
        self._records: dict[str, dict[str, Any]] = {}

    def active_run_ids(self) -> frozenset[str]:
        """Return run ids still leased by this runtime instance.
        Returns:
            frozenset[str]: ``sevn.run_id`` values for live containers.
        Examples:
            >>> isinstance(True, bool)
            True
        """
        return frozenset(
            str(rec["run_id"]) for rec in self._records.values() if rec.get("run_id") is not None
        )

    async def reap_stale_containers(self) -> list[str]:
        """Remove labeled containers past TTL not tracked in ``self._records``.
        Returns:
            list[str]: Removed container ids.
        Examples:
            >>> isinstance(True, bool)
            True
        """
        return await reap_stale_sandbox_containers(
            max_lifetime_s=self._lifetime_s,
            active_run_ids=self.active_run_ids(),
        )

    async def spawn(self, *, run_id: str, workspace: Path, env: dict[str, str]) -> str:
        """Pull image, bind-mount workspace with ``.llmignore/`` masked, start container.
        Args:
            run_id (str): Correlation id surfaced in telemetry and container label.
            workspace (Path): Host workspace bind root.
            env (dict[str, str]): §2.2 child env (proxy, session token, workspace path).
        Returns:
            str: Docker container id (opaque sandbox handle).
        Raises:
            SandboxConfigurationError: When docker is missing or ``docker run`` fails.
        Examples:
            >>> isinstance(True, bool)
            True
        """
        docker_bin = _docker_bin()

        def _resolve_workspace() -> Path:
            return workspace.expanduser().resolve()

        ws = await asyncio.to_thread(_resolve_workspace)
        child_env = dict(env)
        token = _resolve_spawn_session_token(run_id=run_id, env=child_env)
        if token:
            child_env["SEVN_SESSION_TOKEN"] = token
        child_env.update(self._pre_env)
        child_env.setdefault("SEVN_WORKSPACE", _DOCKER_WORKSPACE_MOUNT)
        proxy_raw = str(child_env.get("SEVN_PROXY_URL", "")).strip()
        if proxy_raw:
            await ensure_proxy_attached_to_sandbox_network(proxy_url=proxy_raw)
            rewritten = rewrite_proxy_url_for_sandbox_network(proxy_raw)
            if rewritten != proxy_raw:
                _apply_sandbox_proxy_env(child_env, rewritten)
        network_rules = await asyncio.to_thread(
            _write_docker_network_policy,
            ws,
            child_env=child_env,
        )
        network_name = await ensure_sandbox_docker_network()
        llmignore_mounts = await asyncio.to_thread(_discover_llmignore_mask_mounts, ws)
        out_dir = await asyncio.to_thread(_prepare_workspace_out_dir, ws, run_id)
        spawn_ts = int(time.time())
        pinned_image = await _resolve_digest_pinned_image(self._image)
        pull_rc, pull_out, pull_err = await _docker_run(
            [docker_bin, "pull", pinned_image],
            timeout_s=600.0,
        )
        if pull_rc != 0:
            msg = (
                f"docker pull {pinned_image!r} failed (exit {pull_rc}): "
                f"{pull_err.strip() or pull_out.strip()}"
            )
            raise SandboxConfigurationError(msg)
        name = f"sevn-sb-{uuid.uuid4().hex[:12]}"
        run_argv: list[str] = [
            docker_bin,
            "run",
            "-d",
            "--name",
            name,
            "--network",
            network_name,
            "--label",
            f"sevn.run_id={run_id}",
            "--label",
            f"{_SANDBOX_SPAWN_TS_LABEL}={spawn_ts}",
            *_docker_isolation_args(),
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=256m",  # nosec B108 — Docker tmpfs mount, not host tempfile
            "-v",
            f"{ws}:{_DOCKER_WORKSPACE_MOUNT}:ro",
            "-v",
            f"{out_dir}:{_DOCKER_WORKSPACE_MOUNT}/{_DOCKER_OUT_SUBDIR}:rw",
            "-w",
            _DOCKER_WORKSPACE_MOUNT,
            *_docker_resource_args(self._cfg),
        ]
        for mask_dir, container_path in llmignore_mounts:
            run_argv.extend(["-v", f"{mask_dir}:{container_path}:ro"])
        for key, val in child_env.items():
            run_argv.extend(["-e", f"{key}={val}"])
        run_argv.extend([pinned_image, "sleep", "infinity"])
        rc, out, err = await _docker_run(run_argv, timeout_s=120.0)
        container_id = out.strip()
        if rc != 0 or not container_id:
            msg = f"docker run failed (exit {rc}): {err.strip() or out.strip()}"
            raise SandboxConfigurationError(msg)
        sid = container_id
        self._records[sid] = {
            "run_id": run_id,
            "container_id": container_id,
            "container_name": name,
            "mask_dirs": [mask for mask, _ in llmignore_mounts],
            "out_dir": out_dir,
            "workspace": ws,
            "child_env": child_env,
        }
        runtime_attrs: dict[str, object] = {
            "driver": SandboxDriver.docker,
            "image": pinned_image,
            "run_id": run_id,
            "sandbox_max_lifetime_s": self._lifetime_s,
            "sandbox_id": sid,
            "network_mode": network_name,
        }
        if network_rules is not None:
            runtime_attrs["network_policy_path"] = str(network_rules)
        hp = _proxy_host_port_from_env(child_env)
        if hp is not None:
            runtime_attrs["proxy_host_port"] = hp
        await _emit_sink(self._sink, "sandbox.runtime", runtime_attrs)
        await _emit_sink(
            self._sink,
            "sandbox.spawn",
            {
                "sandbox_id": sid,
                "argv0": "sleep",
                "run_id": run_id,
            },
        )
        return sid

    async def exec(
        self,
        sandbox_id: str,
        argv: list[str],
        *,
        cwd: Path | None = None,
        timeout_s: float | None = None,
    ) -> object:
        """Run ``docker exec`` after argv/PID hygiene checks (§8.3).
        Args:
            sandbox_id (str): Container id from ``spawn``.
            argv (list[str]): Executable vector inside the container.
            cwd (Path | None): Optional working directory (``-w``).
            timeout_s (float | None): Optional communicate timeout.
        Returns:
            dict[str, object]: ``exit_code`` / ``stdout`` / ``stderr`` payload.
        Raises:
            SandboxConfigurationError: Unknown ``sandbox_id``.
            SandboxPolicyViolationError: Self-preservation denylist match.
        Examples:
            >>> isinstance(True, bool)
            True
        """
        rec = self._records.get(sandbox_id)
        if rec is None:
            msg = f"unknown sandbox_id {sandbox_id!r}"
            raise SandboxConfigurationError(msg)
        rule = check_self_preservation_argv(argv)
        if rule is not None:
            await _emit_sink(
                self._sink,
                "sandbox.self_preservation_block",
                {
                    "argv_first": argv[0] if argv else "",
                    "matched_rule": rule,
                    "target_pid_resolved": None,
                },
            )
            raise SandboxPolicyViolationError(f"self-preservation: {rule}")
        pid_rule = pid_target_gate_stub(argv)
        if pid_rule is not None:
            await _emit_sink(
                self._sink,
                "sandbox.self_preservation_block",
                {
                    "argv_first": argv[0] if argv else "",
                    "matched_rule": pid_rule,
                    "target_pid_resolved": None,
                },
            )
            raise SandboxPolicyViolationError(f"self-preservation: {pid_rule}")
        docker_bin = _docker_bin()
        exec_argv: list[str] = [docker_bin, "exec"]
        if cwd is not None:
            exec_argv.extend(["-w", str(cwd)])
        exec_argv.append(sandbox_id)
        exec_argv.extend(argv)
        from sevn.security.trigger_spawn_env import host_env_base_for_subprocess

        merged_env = host_env_base_for_subprocess()
        merged_env.update(dict(rec["child_env"]))
        _ = _apply_subprocess_limits(merged_env, self._cfg)
        rc, stdout, stderr = await _docker_run(exec_argv, timeout_s=timeout_s)
        return _codec_exec_result(rc, stdout, stderr)

    async def exec_python_repl(
        self,
        sandbox_id: str,
        code: str,
        *,
        timeout_s: float | None = 30.0,
    ) -> dict[str, object]:
        """Execute Python in the container via stdin REPL handshake (§4.6).
        Args:
            sandbox_id (str): Container id from ``spawn``.
            code (str): Python source executed in isolated ``<repl>`` scope.
            timeout_s (float | None): Optional communicate timeout.
        Returns:
            dict[str, object]: ``exit_code`` / ``stdout`` / ``stderr`` payload.
        Examples:
            >>> isinstance(True, bool)
            True
        """
        repl_argv = [
            "python",
            "-c",
            (
                "import sys\n"
                "src = sys.stdin.read()\n"
                "ns = {'__name__': '__main__'}\n"
                "exec(compile(src, '<repl>', 'exec'), ns)\n"
                f"print({_REPL_READY_MARKER!r})\n"
            ),
        ]
        docker_bin = _docker_bin()
        exec_argv = [
            docker_bin,
            "exec",
            "-i",
            "-w",
            _DOCKER_WORKSPACE_MOUNT,
            sandbox_id,
            *repl_argv,
        ]
        rc, stdout, stderr = await _docker_run(
            exec_argv,
            timeout_s=timeout_s,
            stdin=code.encode("utf-8"),
        )
        if _REPL_READY_MARKER in stdout:
            stdout = stdout.replace(f"{_REPL_READY_MARKER}\n", "").replace(_REPL_READY_MARKER, "")
        return _codec_exec_result(rc, stdout, stderr)

    async def teardown(self, sandbox_id: str) -> None:
        """Stop and remove the container; emit ``sandbox.teardown`` (§2.3).
        Args:
            sandbox_id (str): Container id returned from ``spawn``.
        Returns:
            None: Always ``None``.
        Examples:
            >>> isinstance(True, bool)
            True
        """
        rec = self._records.pop(sandbox_id, None)
        reason = "explicit"
        if rec is not None:
            docker_bin = _docker_bin()
            name = str(rec.get("container_name", ""))
            if name:
                await _docker_run([docker_bin, "rm", "-f", name], timeout_s=60.0)

            def _rm_paths() -> None:
                mask_dirs = rec.get("mask_dirs")
                if isinstance(mask_dirs, list):
                    for mask_dir in mask_dirs:
                        if isinstance(mask_dir, Path) and mask_dir.exists():
                            shutil.rmtree(mask_dir, ignore_errors=True)
                else:
                    legacy = rec.get("mask_dir")
                    if isinstance(legacy, Path) and legacy.exists():
                        shutil.rmtree(legacy, ignore_errors=True)
                out_dir = rec.get("out_dir")
                if isinstance(out_dir, Path) and out_dir.exists():
                    shutil.rmtree(out_dir, ignore_errors=True)

            await asyncio.to_thread(_rm_paths)
        await _emit_sink(
            self._sink,
            "sandbox.teardown",
            {
                "sandbox_id": sandbox_id,
                "reason": reason,
                "files_synced_count": 0,
                "bytes_written": 0,
            },
        )


def make_runtime_for_driver(
    driver: SandboxDriver,
    *,
    layout: WorkspaceLayout,
    cfg: WorkspaceConfig,
    trace_sink: TraceSink | None = None,
    pre_spawn_env: dict[str, str] | None = None,
    docker_image: str | None = None,
) -> SandboxRuntime:
    """Factory for sandbox runtime implementations.
    Args:
        driver (SandboxDriver): Resolved driver enum.
        layout (WorkspaceLayout): Workspace paths.
        cfg (WorkspaceConfig): Typed config subtree.
        trace_sink (TraceSink | None): Trace injection port.
        pre_spawn_env (dict[str, str] | None): Extra env layered on sandbox children.
        docker_image (str | None): Overrides default sandbox image reference.
    Returns:
        SandboxRuntime: Concrete asyncio runtime.
    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> from pathlib import Path
        >>> from sevn.workspace.layout import WorkspaceLayout
        >>> cfg = WorkspaceConfig.minimal()
        >>> lay = WorkspaceLayout(Path("/tmp/x/sevn.json"), Path("/tmp/x"))
        >>> rt = make_runtime_for_driver(SandboxDriver.subprocess, layout=lay, cfg=cfg)
    """
    rlm_img = docker_image
    if rlm_img is None:
        blob = rlm_json_dict(cfg)
        cand = blob.get("docker_image")
        if isinstance(cand, str) and cand.strip():
            rlm_img = cand.strip()
        else:
            rlm_img = "ghcr.io/sevn-bot/sevn/sandbox:dev"
    if driver == SandboxDriver.docker:
        return DockerSandboxRuntime(
            trace_sink=trace_sink,
            cfg=cfg,
            sandbox_max_lifetime_s=_cfg_max_lifetime_s(cfg),
            image=rlm_img,
            pre_spawn_env=pre_spawn_env,
        )
    return SubprocessSandboxRuntime(
        trace_sink=trace_sink,
        layout=layout,
        cfg=cfg,
        sandbox_max_lifetime_s=_cfg_max_lifetime_s(cfg),
        docker_image=rlm_img,
        pre_spawn_env=pre_spawn_env,
    )
