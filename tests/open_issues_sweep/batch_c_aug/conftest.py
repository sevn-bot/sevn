"""Shared helpers for open-issues sweep Aug 2026 Batch C RED tests."""

from __future__ import annotations

import importlib.util
import sys
from typing import Any

import pytest

from sevn.data.bundled_skills import BUNDLED_SKILLS_ROOT

SKILL_ID = "social_media_manager"
SCRIPTS_DIR = BUNDLED_SKILLS_ROOT / "core" / SKILL_ID / "scripts"

BUNDLED_SCRIPT_NAMES: tuple[str, ...] = (
    "_common.py",
    "capabilities.py",
    "session_status.py",
    "x_ops.py",
    "x_timeline.py",
    "x_tweet_actions.py",
    "twexapi_call.py",
    "twexapi_search.py",
    "twexapi_users.py",
)


def load_smm_script(script_name: str) -> Any:
    """Load one bundled ``social_media_manager`` script module by file path."""
    path = SCRIPTS_DIR / script_name
    if not path.is_file():
        pytest.fail(f"missing bundled script {path}")
    mod_name = f"smm_aug_{script_name.replace('.py', '')}"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    assert spec is not None
    assert spec.loader is not None
    for stale in ("_common", "x_ops"):
        sys.modules.pop(stale, None)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
