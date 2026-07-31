"""Shared helpers for the hermes-model-eval bundled skill (#91, W32).

Module: sevn.data.bundled_skills.core.hermes-model-eval.scripts._common
Depends: json, sys, pathlib, sevn.cli.workspace

Exports:
    emit_json — print one JSON envelope line.
    load_workspace_config — bind workspace from env / cwd.
    ensure_repo_root_on_path — expose repo ``tests/`` package to skill scripts.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from sevn.config.workspace_config import WorkspaceConfig


def ensure_repo_root_on_path() -> Path:
    """Add repository root to ``sys.path`` for golden_llm test fixtures.

    Returns:
        Path: Repository root inferred from this file location.

    Examples:
        >>> root = ensure_repo_root_on_path()
        >>> root.name
        'sevn-issues-f-integrations'
    """
    root = Path(__file__).resolve().parents[7]
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    return root


def emit_json(payload: dict[str, Any]) -> None:
    """Write one JSON object to stdout."""
    sys.stdout.write(json.dumps(payload, sort_keys=True) + "\n")


def load_workspace_config() -> WorkspaceConfig:
    """Load workspace config from the bound checkout or minimal fallback."""
    try:
        from sevn.cli.workspace import load_bound_workspace

        return load_bound_workspace().config
    except Exception:
        return WorkspaceConfig.minimal()


__all__ = ["emit_json", "ensure_repo_root_on_path", "load_workspace_config"]
