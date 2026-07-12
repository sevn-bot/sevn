"""Environment for onboarding handoff child processes.

Module: sevn.onboarding.spawn_env
Depends: os, pathlib, sevn.cli.workspace

Exports:
    handoff_child_env — ``SEVN_HOME`` and service log markers for uvicorn spawn.
"""

from __future__ import annotations

import os
from pathlib import Path

from sevn.cli.workspace import operator_home_from_sevn_json


def handoff_child_env(
    *,
    sevn_json_path: Path,
    service: str,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build env for detached gateway/proxy uvicorn children.

    Binds ``SEVN_HOME`` from the promoted ``sevn.json`` path (not only the
    wizard parent's default) and sets ``SEVN_SERVICE_LOG`` so factory boot
    rotates the canonical log file once.

    Args:
        sevn_json_path (Path): Promoted ``sevn.json``.
        service (str): ``gateway`` or ``proxy``.
        extra (dict[str, str] | None): Additional env entries (e.g. ``SEVN_PROXY_URL``).

    Returns:
        dict[str, str]: Environment for ``subprocess.Popen``.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> home = Path(tempfile.mkdtemp())
        >>> ws = home / "workspace"
        >>> _ = ws.mkdir()
        >>> sj = ws / "sevn.json"
        >>> env = handoff_child_env(sevn_json_path=sj, service="proxy")
        >>> env["SEVN_HOME"] == str(home.resolve())
        True
        >>> env["SEVN_SERVICE_LOG"]
        'proxy'
    """
    env = os.environ.copy()
    env["SEVN_HOME"] = str(operator_home_from_sevn_json(sevn_json_path))
    env["SEVN_SERVICE_LOG"] = service
    if extra:
        env.update(extra)
    return env


__all__ = ["handoff_child_env"]
