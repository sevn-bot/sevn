"""Human-verification webview helper runner."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


class HVUnavailableError(Exception):
    """The HV helper could not run on this machine."""


class HVCancelledError(Exception):
    """The user cancelled human verification."""


def resolve_with_helper(challenge: str) -> str:
    """Run ``proton-cli-hv`` (or ``PROTON_HV_HELPER``) and return the HV token."""
    if not challenge:
        raise ValueError("hv: empty challenge token")
    helper = _helper_path()
    if not helper:
        raise HVUnavailableError("proton-cli-hv helper not found on PATH")
    proc = subprocess.run(
        [helper, challenge],
        capture_output=True,
        text=True,
        check=False,
    )
    detail = (proc.stderr or "").strip().split("\n", 1)[0]
    if proc.returncode == 0:
        token = (proc.stdout or "").strip()
        if not token:
            raise HVUnavailableError("helper exited 0 but printed no token")
        return token
    if proc.returncode in (3, 126, 127):
        raise HVUnavailableError(detail or "webview unavailable")
    if proc.returncode == 4:
        raise HVCancelledError(detail or "verification cancelled")
    if proc.returncode == 5:
        raise RuntimeError(f"hv: server error: {detail}")
    raise RuntimeError(f"hv: helper exit {proc.returncode}: {detail}")


def _helper_path() -> str | None:
    env = os.environ.get("PROTON_HV_HELPER", "").strip()
    if env and Path(env).is_file():
        return env
    found = shutil.which("proton-cli-hv")
    if found:
        return found
    cache = Path.home() / ".cache" / "proton-cli" / "proton-cli-hv"
    if cache.is_file():
        return str(cache)
    return None
