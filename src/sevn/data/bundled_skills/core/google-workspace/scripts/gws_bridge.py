#!/usr/bin/env python3
"""Bundled ``google-workspace`` skill — thin pass-through bridge to ``gws``.

Module: sevn.data.bundled_skills.core.google-workspace.scripts.gws_bridge
Depends: os, subprocess, sys, sevn.lcm.script_cli, sevn.skills.google_workspace

Exports:
    main — CLI entry; forwards argv/stdout/stderr to ``gws``.
"""

from __future__ import annotations

import os
import subprocess
import sys

from loguru import logger

from sevn.lcm.script_cli import workspace_from_env
from sevn.skills.google_workspace import gws_binary, get_valid_token_for_gws, token_path

_GWS_CREDENTIALS_FILE_ENV = "GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE"
_GWS_TOKEN_ENV = "GOOGLE_WORKSPACE_CLI_TOKEN"


def _bridge_env() -> dict[str, str]:
    workspace = workspace_from_env()
    env = dict(os.environ)
    stored_token = token_path(workspace)
    try:
        env[_GWS_TOKEN_ENV] = get_valid_token_for_gws(workspace)
    except (FileNotFoundError, ImportError, ValueError):
        if stored_token.is_file():
            env[_GWS_CREDENTIALS_FILE_ENV] = str(stored_token)
        else:
            raise
    return env


def main(argv: list[str] | None = None) -> int:
    """Run ``gws`` with workspace-scoped auth env and pass-through I/O."""

    binary = gws_binary()
    if binary is None:
        logger.error("google_workspace: gws CLI not found on PATH")
        return 127
    args = list(sys.argv[1:] if argv is None else argv)
    logger.debug("google_workspace: gws bridge {}", " ".join([binary, *args]))
    try:
        completed = subprocess.run(  # nosec B603
            [binary, *args],
            env=_bridge_env(),
            check=False,
        )
    except Exception as exc:
        logger.exception("google_workspace: gws bridge failed: {}", exc)
        return 1
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
