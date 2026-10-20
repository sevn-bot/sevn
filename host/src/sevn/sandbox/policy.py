"""Sandbox levels, command risk, and the host allow_all switch (spec §9, D13-D15)."""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path
from typing import Literal

from sevn.contracts.errors import ProtocolError
from sevn.contracts.methods import SandboxModeParams, SandboxModeResult
from sevn.domain.errors import DomainError
from sevn.log import logger
from sevn.paths import Paths
from sevn.protocol.registry import Ctx, method
from sevn.sandbox.bubblewrap import argv as bwrap_argv
from sevn.sandbox.isolated import argv as isolated_argv
from sevn.sandbox.seatbelt import argv as seatbelt_argv

type Risk = Literal["low", "medium", "high", "destructive"]

_CONFIRM = "I understand"
_MODE_NAME = "sandbox.mode"
_RM_RF = re.compile(r"(?:^|\s)-[A-Za-z]*r[A-Za-z]*f|(?:^|\s)-[A-Za-z]*f[A-Za-z]*r")
_ROOT = re.compile(r"(?:^|\s)/(?:\s|$|\*)")
_SUDO = re.compile(r"(?:^|\s)sudo(?:\s|$)")
_PIPE_SHELL = re.compile(r"\b(?:curl|wget)\b[^|]*\|\s*(?:sh|bash|zsh)\b")
_REDIRECT = re.compile(r"(?:>>|>)\s*([^\s;|&]+)")
_HIGH = ("curl", "wget", "ssh", "nc ", "ncat")
_MEDIUM = re.compile(r"\b(?:rm|chmod|chown|mv)\b")


def risk_of(command: str) -> Risk:
    """Score one shell command. The listed overrides are always destructive (D15)."""
    if _destructive(command):
        return "destructive"
    folded = command.lower()
    if any(token in folded for token in _HIGH):
        return "high"
    if _MEDIUM.search(folded):
        return "medium"
    return "low"


def approval_required(*, access: str, policy: str, risk: Risk, host_allow_all: bool) -> bool:
    """``full`` asks unless the command is low and the policy is ``auto`` (D15)."""
    if host_allow_all or access != "full" or policy == "allow_all":
        return False
    if policy == "auto":
        return risk != "low"
    return True


def allow_all_enabled() -> bool:
    """True only when the host file says ``allow_all``. Missing means enforced."""
    path = _mode_path()
    if not path.is_file():
        return False
    return path.read_text(encoding="utf-8").strip() == "allow_all"


def shared_dir() -> Path:
    """The directory file tools already treat as shared with the workspace."""
    return (Paths.from_env().workspaces.parent / "Shared").resolve()


def workspace_argv(command: str, *, root: Path, network: bool) -> list[str]:
    """Seatbelt on macOS, bubblewrap on Linux. Other platforms do not run the command."""
    workspace = root.resolve()
    shared = shared_dir()
    shared.mkdir(parents=True, exist_ok=True)
    if sys.platform == "darwin":
        return seatbelt_argv(command, workspace=workspace, shared=shared, network=network)
    if sys.platform == "linux":
        return bwrap_argv(command, workspace=workspace, shared=shared, network=network)
    raise DomainError("invalid_params", "sandbox is unavailable")


def direct_argv(command: str) -> list[str]:
    """Run a command with no confinement. Used for ``full`` and ``allow_all``."""
    return ["/bin/sh", "-c", command]


def isolated_command(command: str, *, root: Path, network: bool) -> list[str]:
    """Prepare the isolated docker argv and the shared mount."""
    workspace = root.resolve()
    shared = shared_dir()
    shared.mkdir(parents=True, exist_ok=True)
    return isolated_argv(command, workspace=workspace, shared=shared, network=network)


@method(
    "host.set_sandbox_mode",
    params=SandboxModeParams,
    result=SandboxModeResult,
    mutating=True,
    scope="owner",
)
async def set_sandbox_mode(ctx: Ctx, params: SandboxModeParams) -> SandboxModeResult:
    """Switch the host between enforced and allow_all. The confirm phrase is exact."""
    if params.confirm != _CONFIRM:
        raise ProtocolError("confirm_required", 'confirm with "I understand"')
    await asyncio.to_thread(_write_mode, params.mode)
    await ctx.hub.emit("audit", "host", {"mode": params.mode, "setting": "sandbox.mode"})
    logger.info("sandbox mode set to {}", params.mode)
    return SandboxModeResult(mode=params.mode)


def _mode_path() -> Path:
    return Paths.from_env().home / _MODE_NAME


def _write_mode(mode: str) -> None:
    path = _mode_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(mode + "\n", encoding="utf-8")


def _destructive(command: str) -> bool:
    if _SUDO.search(command) or _PIPE_SHELL.search(command) or _dotfile(command):
        return True
    return _RM_RF.search(command) is not None and _ROOT.search(command) is not None


def _dotfile(command: str) -> bool:
    for match in _REDIRECT.finditer(command):
        leaf = match.group(1).rstrip("/").rsplit("/", 1)[-1]
        if leaf.startswith("."):
            return True
    return False
