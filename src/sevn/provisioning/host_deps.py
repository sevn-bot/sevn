"""Detect and install optional host dependencies (ripgrep, Deno, Pango, Docker).

Module: sevn.provisioning.host_deps
Depends: platform, shutil, subprocess

These are the native tools whose absence the gateway logs as *degraded* (a slower fallback
still runs): ripgrep (``search_in_file`` Python fallback), Deno (``sandbox_exec`` downgrades to
Docker/unavailable), Pango (WeasyPrint → fpdf2 PDF fallback), and Docker (alternative sandbox
runtime). Operators opt in per-dependency via ``provisioning.auto_install`` in ``sevn.json``;
:func:`provision_host_deps` then installs only the *selected-and-missing* ones during
``sevn sync`` and gateway (re)start. It is idempotent (present tools are skipped), never raises
(installers degrade to a ``failed``/``manual`` outcome), and is fully injectable for tests via
the ``runner`` / ``system`` / ``pkg_manager`` parameters.

Exports:
    HostDep — one provisionable host binary/library with probe + install plan.
    ProvisionOutcome — result row for one dependency.
    ProvisionReport — aggregated provisioning results.
    host_dep_ids — sorted registry ids (config allowlist).
    provision_host_deps — install selected-and-missing host dependencies (idempotent).
    summarize_report — one-line human summary of a provisioning pass.

Examples:
    >>> ids = host_dep_ids()
    >>> ids == ("deno", "docker", "pango", "ripgrep")
    True
"""

from __future__ import annotations

import os
import platform as _platform
import shutil
import subprocess  # nosec B404 - provisioning shells out to trusted package managers only
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Literal

# ``(returncode, combined_output)``. Injected in tests so no real installer runs.
Runner = Callable[[Sequence[str]], "tuple[int, str]"]

OutcomeStatus = Literal[
    "already_present",  # probe passed before we did anything
    "installed",  # ran an installer and the probe now passes
    "failed",  # installer ran (or would have) but the probe still fails
    "manual",  # no automated installer for this platform — hint returned
    "unsupported",  # selected id is not in the registry
]

_INSTALL_TIMEOUT_S = 900.0
_LINUX_APT_MANUAL_HINT = (
    "Linux apt installs require root or passwordless sudo — run manually as root, e.g. "
    "`sudo apt-get install -y <packages>`, or run the gateway/`sevn sync` as root"
)


def _linux_apt_privileged(*, privileged: bool | None = None) -> bool:
    """Return whether ``apt-get install`` can run without an interactive sudo password.

    Args:
        privileged (bool | None): Test override; auto-detect when ``None``.

    Returns:
        bool: ``True`` when euid is 0 or passwordless ``sudo apt-get`` works.

    Examples:
        >>> _linux_apt_privileged(privileged=True)
        True
        >>> isinstance(_linux_apt_privileged(privileged=False), bool)
        True
    """
    if privileged is not None:
        return privileged
    if os.geteuid() == 0:
        return True
    sudo = shutil.which("sudo")
    if sudo is None:
        return False
    try:
        proc = subprocess.run(  # nosec B603 - fixed argv, resolved binary
            [sudo, "-n", "apt-get", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


@dataclass(frozen=True, slots=True)
class HostDep:
    """One host dependency: how to detect it and how to install it per platform."""

    id: str
    title: str
    probe: Callable[[], bool]
    fallback_note: str
    manual_hint: str
    brew_formula: tuple[str, ...] | None = None
    brew_cask: tuple[str, ...] | None = None
    apt_packages: tuple[str, ...] | None = None
    post_install_manual: str | None = None

    def install_argv(self, *, system: str, pkg_manager: str | None) -> list[str] | None:
        """Return the installer argv for this platform, or ``None`` when unavailable.

        Args:
            system (str): ``platform.system()`` value (``Darwin``/``Linux``/...).
            pkg_manager (str | None): Detected manager (``brew``/``apt``) or ``None``.

        Returns:
            list[str] | None: Installer argv, or ``None`` when no automated path exists.

        Examples:
            >>> dep = HOST_DEPS["ripgrep"]
            >>> dep.install_argv(system="Darwin", pkg_manager="brew")
            ['brew', 'install', 'ripgrep']
            >>> dep.install_argv(system="Linux", pkg_manager="apt")
            ['apt-get', 'install', '-y', 'ripgrep']
            >>> dep.install_argv(system="Windows", pkg_manager=None) is None
            True
        """
        _ = system
        if pkg_manager == "brew":
            if self.brew_cask is not None:
                return ["brew", "install", "--cask", *self.brew_cask]
            if self.brew_formula is not None:
                return ["brew", "install", *self.brew_formula]
            return None
        if pkg_manager == "apt" and self.apt_packages is not None:
            return ["apt-get", "install", "-y", *self.apt_packages]
        if pkg_manager == "apt" and shutil.which("brew"):
            # brew-only deps (e.g. whisper-cpp) may still install via Linuxbrew while
            # core packages keep using apt above.
            if self.brew_cask is not None:
                return ["brew", "install", "--cask", *self.brew_cask]
            if self.brew_formula is not None:
                return ["brew", "install", *self.brew_formula]
        return None


@dataclass(frozen=True, slots=True)
class ProvisionOutcome:
    """Result of provisioning one dependency."""

    dep_id: str
    status: OutcomeStatus
    detail: str


@dataclass
class ProvisionReport:
    """Aggregated provisioning outcomes for one pass."""

    outcomes: list[ProvisionOutcome] = field(default_factory=list)

    def add(self, outcome: ProvisionOutcome) -> None:
        """Append one outcome.

        Args:
            outcome (ProvisionOutcome): Row to record.

        Examples:
            >>> r = ProvisionReport()
            >>> r.add(ProvisionOutcome("ripgrep", "installed", "ok"))
            >>> len(r.outcomes)
            1
        """
        self.outcomes.append(outcome)

    def by_status(self, status: OutcomeStatus) -> list[ProvisionOutcome]:
        """Return outcomes with the given ``status``.

        Args:
            status (OutcomeStatus): Status filter.

        Returns:
            list[ProvisionOutcome]: Matching rows.

        Examples:
            >>> r = ProvisionReport([ProvisionOutcome("deno", "manual", "x")])
            >>> [o.dep_id for o in r.by_status("manual")]
            ['deno']
        """
        return [o for o in self.outcomes if o.status == status]

    @property
    def changed(self) -> bool:
        """Return whether any dependency was newly installed.

        Returns:
            bool: ``True`` when at least one outcome is ``installed``.

        Examples:
            >>> ProvisionReport([ProvisionOutcome("deno", "installed", "x")]).changed
            True
        """
        return any(o.status == "installed" for o in self.outcomes)


def _probe_ripgrep() -> bool:
    """Return whether ripgrep (``rg``) is on ``PATH``.

    Returns:
        bool: ``True`` when found.

    Examples:
        >>> isinstance(_probe_ripgrep(), bool)
        True
    """
    return shutil.which("rg") is not None


def _probe_deno() -> bool:
    """Return whether the Deno binary resolves for the Pyodide sandbox.

    Returns:
        bool: ``True`` when Deno is discoverable.

    Examples:
        >>> isinstance(_probe_deno(), bool)
        True
    """
    return shutil.which("deno") is not None


def _probe_pango() -> bool:
    """Return whether WeasyPrint's native stack (Pango/GObject) loads.

    Returns:
        bool: ``True`` when WeasyPrint can render (native libs present).

    Examples:
        >>> isinstance(_probe_pango(), bool)
        True
    """
    try:
        from sevn.pdf.doctor_check import probe_weasyprint_render

        return bool(probe_weasyprint_render().ok)
    except Exception:
        return False


def _probe_docker() -> bool:
    """Return whether a Docker daemon is reachable (``docker info`` succeeds).

    Returns:
        bool: ``True`` when the daemon responds.

    Examples:
        >>> isinstance(_probe_docker(), bool)
        True
    """
    docker = shutil.which("docker")
    if docker is None:
        return False
    try:
        proc = subprocess.run(  # nosec B603 - fixed argv, resolved binary
            [docker, "info"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


HOST_DEPS: dict[str, HostDep] = {
    "ripgrep": HostDep(
        id="ripgrep",
        title="ripgrep (rg)",
        probe=_probe_ripgrep,
        brew_formula=("ripgrep",),
        apt_packages=("ripgrep",),
        fallback_note="search_in_file falls back to a slower Python regex scan",
        manual_hint="install ripgrep from https://github.com/BurntSushi/ripgrep#installation",
    ),
    "deno": HostDep(
        id="deno",
        title="Deno",
        probe=_probe_deno,
        brew_formula=("deno",),
        # Deno is not in the default apt repos; the official script is the supported path.
        apt_packages=None,
        fallback_note="sandbox_exec downgrades to the Docker driver (or is unavailable)",
        manual_hint="install Deno: `curl -fsSL https://deno.land/install.sh | sh` "
        "(or set sandbox.mode=docker)",
    ),
    "pango": HostDep(
        id="pango",
        title="Pango (WeasyPrint native libs)",
        probe=_probe_pango,
        brew_formula=("pango",),
        apt_packages=(
            "libpango-1.0-0",
            "libpangocairo-1.0-0",
            "libgdk-pixbuf-2.0-0",
            "libffi-dev",
            "libcairo2",
        ),
        fallback_note="PDF rendering uses the reduced-fidelity fpdf2 fallback",
        manual_hint="install Pango: `brew install pango` (macOS) or the libpango/cairo "
        "packages for your distro",
    ),
    "docker": HostDep(
        id="docker",
        title="Docker",
        probe=_probe_docker,
        brew_cask=("docker",),
        apt_packages=None,
        fallback_note="the Docker sandbox driver is unavailable (use Deno instead)",
        manual_hint="install Docker Desktop from https://www.docker.com/ and start it",
        post_install_manual="launch Docker Desktop / start the Docker daemon before it is usable",
    ),
}


def host_dep_ids() -> tuple[str, ...]:
    """Return the sorted registry ids usable in ``provisioning.auto_install``.

    Returns:
        tuple[str, ...]: Sorted dependency ids.

    Examples:
        >>> host_dep_ids()
        ('deno', 'docker', 'pango', 'ripgrep')
    """
    return tuple(sorted(HOST_DEPS))


def _detect_pkg_manager(system: str) -> str | None:
    """Return the platform package manager id, or ``None`` when none is available.

    Args:
        system (str): ``platform.system()`` value.

    Returns:
        str | None: ``brew``, ``apt``, or ``None``.

    Examples:
        >>> _detect_pkg_manager("Windows") is None
        True
    """
    if system == "Darwin":
        return "brew" if shutil.which("brew") else None
    if system == "Linux":
        if shutil.which("apt-get"):
            return "apt"
        return "brew" if shutil.which("brew") else None
    return None


def _default_runner(argv: Sequence[str]) -> tuple[int, str]:
    """Run an installer argv, returning ``(returncode, combined_output)``.

    Args:
        argv (Sequence[str]): Installer command.

    Returns:
        tuple[int, str]: Exit code and captured stdout+stderr (never raises).

    Examples:
        >>> _default_runner(["true"])[0]
        0
    """
    try:
        proc = subprocess.run(  # nosec B603 - argv built from the trusted registry only
            list(argv),
            capture_output=True,
            text=True,
            timeout=_INSTALL_TIMEOUT_S,
            check=False,
        )
    except FileNotFoundError:
        return 127, f"{argv[0]}: not found"
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, f"{type(exc).__name__}: {exc}"
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def provision_host_deps(
    selected: Iterable[str],
    *,
    deps: dict[str, HostDep] | None = None,
    dry_run: bool = False,
    runner: Runner | None = None,
    system: str | None = None,
    pkg_manager: str | None = None,
    apt_privileged: bool | None = None,
) -> ProvisionReport:
    """Install selected-and-missing host dependencies (idempotent, never raises).

    For each selected id: probe it; if present, record ``already_present``. Otherwise resolve
    the platform installer and (unless ``dry_run``) run it, re-probe, and record
    ``installed``/``failed``. When no automated installer exists for the platform, record
    ``manual`` with an actionable hint. Unknown ids are recorded ``unsupported``.

    On Linux, ``apt-get install`` runs only when the process is root or passwordless sudo
    is available; otherwise the outcome is ``manual`` with a privilege hint.

    Args:
        selected (Iterable[str]): Dependency ids the operator opted into.
        deps (dict[str, HostDep] | None): Registry override (tests inject fakes).
        dry_run (bool): Plan installs without running them.
        runner (Runner | None): Installer executor override (tests inject fakes).
        system (str | None): ``platform.system()`` override (tests).
        pkg_manager (str | None): Package-manager override (tests); auto-detected otherwise.
        apt_privileged (bool | None): Linux sudo/root override (tests); auto-detected otherwise.

    Returns:
        ProvisionReport: One outcome per selected dependency.

    Examples:
        >>> present = HostDep("x", "X", probe=lambda: True, fallback_note="", manual_hint="")
        >>> rep = provision_host_deps(["x"], deps={"x": present})
        >>> rep.outcomes[0].status
        'already_present'
        >>> missing = HostDep(
        ...     "y", "Y", probe=lambda: False, fallback_note="", manual_hint="do it by hand"
        ... )
        >>> provision_host_deps(["y"], deps={"y": missing}, system="Windows").outcomes[0].status
        'manual'
    """
    registry = deps if deps is not None else HOST_DEPS
    sys_name = system if system is not None else _platform.system()
    mgr = pkg_manager if pkg_manager is not None else _detect_pkg_manager(sys_name)
    run = runner if runner is not None else _default_runner
    report = ProvisionReport()

    for dep_id in dict.fromkeys(selected):  # de-dupe, preserve order
        dep = registry.get(dep_id)
        if dep is None:
            report.add(
                ProvisionOutcome(dep_id, "unsupported", f"unknown host dependency {dep_id!r}"),
            )
            continue
        if _safe_probe(dep):
            report.add(
                ProvisionOutcome(dep_id, "already_present", f"{dep.title} already installed")
            )
            continue
        argv = dep.install_argv(system=sys_name, pkg_manager=mgr)
        if argv is None:
            report.add(ProvisionOutcome(dep_id, "manual", dep.manual_hint))
            continue
        cmd = " ".join(argv)
        if dry_run:
            report.add(ProvisionOutcome(dep_id, "manual", f"dry-run: would run `{cmd}`"))
            continue
        if mgr == "apt" and not _linux_apt_privileged(privileged=apt_privileged):
            report.add(
                ProvisionOutcome(
                    dep_id,
                    "manual",
                    f"{_LINUX_APT_MANUAL_HINT}; packages: {', '.join(dep.apt_packages or ())}; "
                    f"{dep.manual_hint}",
                ),
            )
            continue
        rc, out = run(argv)
        if rc != 0:
            tail = out.strip().splitlines()[-1] if out.strip() else f"exit {rc}"
            report.add(
                ProvisionOutcome(dep_id, "failed", f"`{cmd}` failed: {tail}; {dep.manual_hint}"),
            )
            continue
        if not _safe_probe(dep):
            note = dep.post_install_manual or "installed but not yet detected — a restart may help"
            report.add(ProvisionOutcome(dep_id, "manual", f"ran `{cmd}` — {note}"))
            continue
        report.add(ProvisionOutcome(dep_id, "installed", f"installed via `{cmd}`"))
    return report


def _safe_probe(dep: HostDep) -> bool:
    """Run ``dep.probe`` swallowing any error (a raising probe means "not present").

    Args:
        dep (HostDep): Dependency to probe.

    Returns:
        bool: Probe result, or ``False`` when the probe raised.

    Examples:
        >>> _safe_probe(HostDep("x", "X", probe=lambda: True, fallback_note="", manual_hint=""))
        True
    """
    try:
        return bool(dep.probe())
    except Exception:
        return False


def summarize_report(report: ProvisionReport) -> str:
    """Return a compact one-line summary of a provisioning pass.

    Args:
        report (ProvisionReport): Completed pass.

    Returns:
        str: Human summary (e.g. ``"installed ripgrep; manual: deno"``), or "" when empty.

    Examples:
        >>> summarize_report(ProvisionReport([ProvisionOutcome("ripgrep", "installed", "x")]))
        'host deps: installed ripgrep'
        >>> summarize_report(ProvisionReport())
        ''
    """
    if not report.outcomes:
        return ""
    parts: list[str] = []
    installed = [o.dep_id for o in report.by_status("installed")]
    if installed:
        parts.append("installed " + ", ".join(installed))
    failed = [o.dep_id for o in report.by_status("failed")]
    if failed:
        parts.append("failed: " + ", ".join(failed))
    manual = [o.dep_id for o in report.by_status("manual")]
    if manual:
        parts.append("manual: " + ", ".join(manual))
    present = [o.dep_id for o in report.by_status("already_present")]
    if present and not parts:
        parts.append("already present: " + ", ".join(present))
    if not parts:
        return ""
    return "host deps: " + "; ".join(parts)
