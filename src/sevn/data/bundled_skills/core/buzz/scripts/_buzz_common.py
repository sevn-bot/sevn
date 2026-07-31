"""Shared Buzz skill helpers (#72, W31.4).

Module: sevn.data.bundled_skills.core.buzz.scripts._buzz_common
Depends: json, os, sevn.acp.buzz_config, sevn.cli.workspace

Exports:
    emit_json — print one JSON envelope line.
    load_identity — resolve Buzz relay credentials.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from sevn.acp.buzz_config import BuzzIdentity, resolve_buzz_identity_sync


def emit_json(payload: dict[str, Any]) -> None:
    """Write one JSON object to stdout."""
    sys.stdout.write(json.dumps(payload, sort_keys=True) + "\n")


def load_identity() -> BuzzIdentity | None:
    """Resolve Buzz identity from the bound workspace or process env."""
    try:
        from sevn.cli.workspace import load_bound_workspace

        bound = load_bound_workspace()
        return resolve_buzz_identity_sync(
            bound.config,
            content_root=str(bound.layout.content_root),
        )
    except Exception:
        return resolve_buzz_identity_sync(
            __import__(
                "sevn.config.workspace_config", fromlist=["WorkspaceConfig"]
            ).WorkspaceConfig.minimal()
        )


__all__ = ["emit_json", "load_identity"]
