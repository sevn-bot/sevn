"""The environment a sandboxed or host-run command inherits (spec §9).

Secrets reach the host through environment variables (``TYPESAFE_API_KEY``,
provider keys, the ``SEVN_SECRET_*`` env backend). A child process gets only
the variables it needs to find programs and render text.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_KEEP = frozenset(
    {
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "SHELL",
        "TMPDIR",
        "TERM",
        "LANG",
        "LANGUAGE",
        "TZ",
    }
)
_DOCKER = frozenset({"DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG", "DOCKER_CERT_PATH"})


def child_env(*, docker: bool = False) -> dict[str, str]:
    """Locale and lookup variables from the host. ``docker`` also keeps the client's."""
    keep = _KEEP | _DOCKER if docker else _KEEP
    env = {key: value for key, value in os.environ.items() if key in keep or key.startswith("LC_")}
    if "PATH" in env:
        env["PATH"] = _without_host_venv(env["PATH"])
    return env


def _without_host_venv(path: str) -> str:
    """Drop the host's own virtualenv from ``PATH``.

    ``python3`` would otherwise resolve to the host interpreter, which can import
    the host's packages and is not a tool the command asked for.
    """
    if sys.prefix == sys.base_prefix:
        return path
    venv_bin = str(Path(sys.prefix) / ("Scripts" if os.name == "nt" else "bin"))
    return os.pathsep.join(item for item in path.split(os.pathsep) if item != venv_bin)
