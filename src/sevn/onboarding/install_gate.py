"""Interactive install reuse / wipe gate (`specs/22-onboarding.md` §4.1).

Module: sevn.onboarding.install_gate
Depends: os, shutil, sys, pathlib, typer, sevn.cli.install_discovery, sevn.cli.operator_lock,
    sevn.cli.service_manager, sevn.cli.workspace

Exports:
    InstallResolution — bound home + reuse flag after gate resolution.
    InstallGateState — whether the gate should run and discovered candidates.
    install_gate_state — compute gate visibility for CLI/web/TUI.
    bind_operator_home — set ``SEVN_HOME`` for the session.
    wipe_operator_home — destructive fresh-start teardown.
    apply_install_resolution — bind env after reuse or wipe.
    prompt_install_gate_tty — interactive CLI picker.
    replace_keystore — delete ``store.enc`` so operator re-enters credentials.
    resolve_install_action — apply reuse or wipe for web/API callers.
    prompt_keystore_passphrase_tty — ask for passphrase when reusing encrypted store.
"""

from __future__ import annotations

import contextlib
import errno
import getpass
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import typer

if TYPE_CHECKING:
    from sevn.cli.install_discovery import InstallCandidate


@dataclass(frozen=True, slots=True)
class InstallResolution:
    """Result of resolving the install gate."""

    home: Path
    reuse: bool


@dataclass(frozen=True, slots=True)
class InstallGateState:
    """Inputs for rendering the install gate."""

    show_gate: bool
    candidates: tuple[InstallCandidate, ...]
    active_home: Path
    active_has_config: bool
    active_has_workspace_artifacts: bool
    active_has_keystore: bool


def _active_home_has_config(home: Path) -> bool:
    """Return True when ``home/workspace/sevn.json`` exists.

    Args:
        home (Path): Operator home directory.

    Returns:
        bool: Whether promoted config is present.

    Examples:
        >>> _active_home_has_config(Path("/nonexistent"))
        False
    """
    return (home / "workspace" / "sevn.json").is_file()


def _active_home_has_workspace_artifacts(home: Path) -> bool:
    """Return True when ``home/workspace`` has prior onboarding residue.

    Args:
        home (Path): Operator home directory.

    Returns:
        bool: Whether the workspace directory should trigger the install gate.

    Examples:
        >>> _active_home_has_workspace_artifacts(Path("/nonexistent"))
        False
    """
    from sevn.cli.install_discovery import workspace_has_artifacts

    return workspace_has_artifacts(home / "workspace")


def install_gate_state() -> InstallGateState:
    """Return whether onboarding should show the existing-install gate.

    Returns:
        InstallGateState: Gate visibility and discovered candidates.

    Examples:
        >>> state = install_gate_state()
        >>> isinstance(state.show_gate, bool)
        True
    """
    from sevn.cli.install_discovery import discover_operator_homes, resolve_workspace_keystore_path
    from sevn.cli.workspace import sevn_home_dir

    active = sevn_home_dir()
    candidates = tuple(discover_operator_homes())
    active_has = _active_home_has_config(active)
    active_ws = active / "workspace"
    active_artifacts = _active_home_has_workspace_artifacts(active)
    active_keystore = resolve_workspace_keystore_path(active_ws) is not None
    if (
        os.environ.get("SEVN_ONBOARD_GATE_RESOLVED") == "1"
        or os.environ.get("SEVN_ONBOARD_SKIP_INSTALL_DISCOVERY") == "1"
    ):
        show = False
    else:
        show = bool(candidates) or active_has or active_artifacts
    return InstallGateState(
        show_gate=show,
        candidates=candidates,
        active_home=active,
        active_has_config=active_has,
        active_has_workspace_artifacts=active_artifacts,
        active_has_keystore=active_keystore,
    )


def _robust_rmtree(target: Path) -> None:
    """Remove a directory tree, retrying on macOS Finder ``.DS_Store`` races.

    macOS Finder transparently re-creates ``.DS_Store`` files inside any
    directory it's currently viewing — including a directory ``shutil.rmtree``
    is mid-walk through. The walk then trips on ``ENOTEMPTY`` when it tries
    to ``rmdir`` the parent. The retry loop sweeps the freshly-regenerated
    metadata file(s) and re-attempts the deletion up to three times before
    giving up.

    Args:
        target (Path): Directory to remove. Must exist.

    Raises:
        OSError: When the tree still fails to delete after the retry budget
            is exhausted (real permission / file-busy errors).

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> tmp = Path(tempfile.mkdtemp())
        >>> _robust_rmtree(tmp)
        >>> tmp.exists()
        False
    """
    last_err: OSError | None = None
    for _ in range(3):
        try:
            shutil.rmtree(target)
        except OSError as exc:
            last_err = exc
            if exc.errno not in (errno.ENOTEMPTY, errno.EEXIST):
                raise
            # Walk back over any residue Finder may have re-created (or that
            # a tardy daemon flushed) and try again.
            if target.exists():
                for stragglers in target.rglob(".DS_Store"):
                    with contextlib.suppress(OSError):
                        stragglers.unlink(missing_ok=True)
            continue
        else:
            return
    if last_err is not None:
        raise last_err


def bind_operator_home(home: Path) -> Path:
    """Bind ``SEVN_HOME`` for the current process.

    Args:
        home (Path): Operator home to bind.

    Returns:
        Path: Resolved absolute home path.

    Examples:
        >>> import os
        >>> from pathlib import Path
        >>> from unittest.mock import patch
        >>> with patch.dict(os.environ, {}, clear=True):
        ...     resolved = bind_operator_home(Path("/tmp/.sevn"))
        >>> str(resolved).endswith(".sevn")
        True
    """
    resolved = home.expanduser().resolve()
    os.environ["SEVN_HOME"] = str(resolved)
    return resolved


def wipe_operator_home(home: Path, *, dry_run: bool = False) -> None:
    """Stop units, remove unit files, and delete the operator home tree.

    Args:
        home (Path): Operator home directory (for example ``~/.sevn``).
        dry_run (bool, optional): Plan only. Defaults to False.

    Raises:
        OperatorLockHeld: When another CLI process holds the operator lock.
        ServiceManagerError: When unit stop/remove fails on this platform.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> op = Path(tempfile.mkdtemp())
        >>> wipe_operator_home(op, dry_run=True) is None
        True
    """
    operator_home = home.expanduser().resolve()
    unit_home = Path.home()
    from sevn.cli.operator_lock import operator_lock
    from sevn.cli.service_manager import remove_paired_unit_files, stop_paired_units

    if dry_run:
        stop_paired_units(home=unit_home, dry_run=True)
        remove_paired_unit_files(home=unit_home, dry_run=True)
        return
    with operator_lock(operator_home):
        stop_paired_units(home=unit_home)
        remove_paired_unit_files(home=unit_home)
        if operator_home.is_dir():
            _robust_rmtree(operator_home)


def apply_install_resolution(resolution: InstallResolution) -> Path:
    """Bind ``SEVN_HOME`` and export reuse intent for daemon install gate.

    Args:
        resolution (InstallResolution): Reuse or fresh-start outcome.

    Returns:
        Path: Bound operator home.

    Examples:
        >>> import os
        >>> from pathlib import Path
        >>> from unittest.mock import patch
        >>> with patch.dict(os.environ, {}, clear=True):
        ...     home = apply_install_resolution(
        ...         InstallResolution(home=Path("/tmp/.sevn"), reuse=True)
        ...     )
        ...     os.environ["SEVN_ONBOARD_REUSE"] == "1"
        True
    """
    bound = bind_operator_home(resolution.home)
    os.environ["SEVN_ONBOARD_REUSE"] = "1" if resolution.reuse else "0"
    os.environ["SEVN_ONBOARD_GATE_RESOLVED"] = "1"
    if not resolution.reuse:
        from sevn.onboarding.github_oauth import clear_wizard_oauth_credentials

        clear_wizard_oauth_credentials()
    return bound


def _pick_candidate_tty(candidates: tuple[InstallCandidate, ...]) -> InstallCandidate:
    """Prompt for one candidate when multiple homes match.

    Args:
        candidates (tuple[InstallCandidate, ...]): Non-empty candidate list.

    Returns:
        InstallCandidate: Operator selection.

    Examples:
        >>> from pathlib import Path
        >>> from sevn.cli.install_discovery import InstallCandidate
        >>> row = InstallCandidate(
        ...     home=Path("/h"),
        ...     sevn_json=Path("/h/workspace/sevn.json"),
        ...     has_keystore=False,
        ...     keystore_path=None,
        ...     gateway_unit_active=False,
        ...     proxy_unit_active=False,
        ... )
        >>> _pick_candidate_tty((row,)).home == Path("/h")
        True
    """
    if len(candidates) == 1:
        return candidates[0]
    typer.echo("Multiple operator homes found:")
    for idx, candidate in enumerate(candidates, start=1):
        typer.echo(f"  {idx}. {candidate.home}")
    choice = int(typer.prompt("Select home", type=int))
    if 1 <= choice <= len(candidates):
        return candidates[choice - 1]
    typer.secho("invalid selection", err=True)
    raise typer.Exit(2)


def _confirm_wipe_tty(home: Path) -> None:
    """Require typed ``DELETE`` before wiping ``home``.

    Args:
        home (Path): Operator home slated for removal.

    Raises:
        typer.Exit: Exit code ``0`` when the operator cancels.

    Examples:
        >>> _confirm_wipe_tty(Path("/tmp/.sevn")) is None  # doctest: +SKIP
        True
    """
    typer.echo(f"This will permanently delete {home} and stop gateway/proxy units.")
    typed = typer.prompt("Type DELETE to confirm", default="")
    if typed.strip() != "DELETE":
        typer.echo("Cancelled.")
        raise typer.Exit(0)


def prompt_install_gate_tty(state: InstallGateState) -> InstallResolution | None:
    """Run the install gate on an interactive TTY before web/TUI onboarding.

    Args:
        state (InstallGateState): Precomputed gate inputs.

    Returns:
        InstallResolution | None: Selected outcome, or ``None`` when gate skipped.

    Raises:
        typer.Exit: On invalid selection or operator cancel during wipe confirm.

    Examples:
        >>> prompt_install_gate_tty(
        ...     InstallGateState(False, (), Path("/tmp/.sevn"), False, False, False)
        ... ) is None
        True
    """
    if not state.show_gate:
        return None
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return None

    candidates = state.candidates
    # The discovered candidate is the right *reuse* target — but never the
    # right *fresh-install* target if it sits at a non-default path. Option 2
    # always writes to the operator's resolved ``SEVN_HOME`` (default
    # ``~/.sevn``) so a one-off sibling ``~/.sevn_old`` never gets clobbered
    # by a wizard the user thought was reinstalling at the default location.
    reuse_target = (
        state.active_home
        if (state.active_has_config or state.active_has_workspace_artifacts)
        else None
    )
    if reuse_target is None and len(candidates) == 1:
        reuse_target = candidates[0].home
    fresh_target = state.active_home

    typer.echo("Existing sevn install detected.")
    if reuse_target is not None and reuse_target == fresh_target:
        typer.echo(f"Active home: {fresh_target}")
    else:
        if reuse_target is not None:
            typer.echo(f"Existing install: {reuse_target} (reuse target)")
        typer.echo(f"Default home: {fresh_target} (fresh-install target)")
    typer.echo("  1. Use existing install (reuse config)")
    typer.echo("  2. Start fresh (wipe and reinstall at default home)")
    if len(candidates) > 1 or (reuse_target is not None and reuse_target != fresh_target):
        typer.echo("  3. Pick another home")
    choice = typer.prompt("Choice", type=int, default=1)

    if choice == 3 and (
        len(candidates) > 1 or (reuse_target is not None and reuse_target != fresh_target)
    ):
        picked = _pick_candidate_tty(candidates)
        sub = typer.prompt("Reuse (1) or wipe (2)", type=int, default=1)
        if sub == 2:
            _confirm_wipe_tty(picked.home)
            wipe_operator_home(picked.home)
            return InstallResolution(home=picked.home, reuse=False)
        return InstallResolution(home=picked.home, reuse=True)

    if choice == 1:
        if reuse_target is None:
            if not candidates:
                return None
            reuse_target = _pick_candidate_tty(candidates).home
        return InstallResolution(home=reuse_target, reuse=True)
    if choice == 2:
        _confirm_wipe_tty(fresh_target)
        wipe_operator_home(fresh_target)
        return InstallResolution(home=fresh_target, reuse=False)

    typer.secho("invalid selection", err=True)
    raise typer.Exit(2)


def resolve_install_action(
    *,
    action: str,
    home: Path,
    confirm: str | None = None,
) -> InstallResolution:
    """Apply reuse or wipe for web/API callers.

    Args:
        action (str): ``reuse`` or ``wipe``.
        home (Path): Target operator home.
        confirm (str | None, optional): Must be ``DELETE`` for wipe.

    Returns:
        InstallResolution: Bound outcome.

    Raises:
        ValueError: On invalid action or missing wipe confirmation.

    Examples:
        >>> isinstance(
        ...     resolve_install_action.__name__,
        ...     str,
        ... )
        True
    """
    normalized = action.strip().lower()
    resolved_home = home.expanduser().resolve()
    if normalized == "reuse":
        has_config = _active_home_has_config(resolved_home)
        has_artifacts = _active_home_has_workspace_artifacts(resolved_home)
        if not has_config and not has_artifacts:
            msg = f"operator home has no reusable workspace data: {resolved_home / 'workspace'}"
            raise ValueError(msg)
        return InstallResolution(home=resolved_home, reuse=True)
    if normalized == "wipe":
        if (confirm or "").strip() != "DELETE":
            msg = "wipe requires confirm=DELETE"
            raise ValueError(msg)
        wipe_operator_home(resolved_home)
        return InstallResolution(home=resolved_home, reuse=False)
    msg = f"unsupported install action: {action!r}"
    raise ValueError(msg)


def replace_keystore(*, sevn_json: Path) -> Path | None:
    """Delete the encrypted keystore so the wizard can collect fresh credentials.

    Args:
        sevn_json (Path): Promoted config path under the bound workspace.

    Returns:
        Path | None: Removed keystore path, or ``None`` when none existed.

    Raises:
        OSError: When deletion fails.

    Examples:
        >>> replace_keystore(sevn_json=Path("/nonexistent/sevn.json")) is None
        True
    """
    from sevn.cli.install_discovery import resolve_keystore_path

    store = resolve_keystore_path(sevn_json=sevn_json)
    if store is None:
        return None
    store.unlink(missing_ok=True)
    return store


def prompt_keystore_passphrase_tty(*, sevn_json: Path) -> None:
    """Prompt for the encrypted keystore passphrase when reusing an existing install.

    Verifies the passphrase decrypts the store before proceeding. Up to three attempts.

    Args:
        sevn_json (Path): Promoted config path under the bound operator home.

    Returns:
        None: Sets ``SEVN_SECRETS_PASSPHRASE`` in ``os.environ`` when verified.

    Raises:
        typer.Exit: When verification fails after three attempts.

    Examples:
        >>> prompt_keystore_passphrase_tty(sevn_json=Path("/nonexistent/sevn.json"))
    """
    import asyncio

    import typer

    from sevn.cli.install_gate import parse_reuse_from_env
    from sevn.config.loader import load_workspace
    from sevn.onboarding.wizard_credentials import (
        secrets_section_from_sevn_json,
        verify_wizard_passphrase,
    )

    if not parse_reuse_from_env():
        return
    _, layout = load_workspace(sevn_json=sevn_json)
    section = secrets_section_from_sevn_json(sevn_json)
    content_root = layout.content_root
    existing = os.environ.get("SEVN_SECRETS_PASSPHRASE", "").strip()
    if existing:
        verified = asyncio.run(verify_wizard_passphrase(content_root, existing, section=section))
        if verified.get("ok"):
            return
        os.environ.pop("SEVN_SECRETS_PASSPHRASE", None)
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return
    from sevn.cli.install_discovery import resolve_keystore_path

    store = resolve_keystore_path(sevn_json=sevn_json)
    if store is None:
        return
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        phrase = getpass.getpass("Encrypted keystore passphrase: ")
        if not phrase.strip():
            typer.secho("Passphrase is required.", err=True)
            continue
        result = asyncio.run(
            verify_wizard_passphrase(content_root, phrase.strip(), section=section)
        )
        if result.get("ok"):
            os.environ["SEVN_SECRETS_PASSPHRASE"] = phrase.strip()
            return
        remaining = max_attempts - attempt
        if remaining <= 0:
            typer.secho("Incorrect passphrase — no attempts remaining.", err=True)
            raise typer.Exit(1)
        typer.secho(
            f"Incorrect passphrase ({remaining} attempt{'s' if remaining != 1 else ''} left).",
            err=True,
        )


__all__ = [
    "InstallGateState",
    "InstallResolution",
    "apply_install_resolution",
    "bind_operator_home",
    "install_gate_state",
    "prompt_install_gate_tty",
    "prompt_keystore_passphrase_tty",
    "replace_keystore",
    "resolve_install_action",
    "wipe_operator_home",
]
