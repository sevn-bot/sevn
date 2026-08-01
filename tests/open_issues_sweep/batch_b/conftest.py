"""Shared fixtures for open-issues sweep Batch B (model & routing) RED suite."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from sevn.config.workspace_config import WorkspaceConfig

_GATEWAY_TOKEN = {"token": "${SECRET:keychain:sevn.gateway.token}"}


def baseline_minimal_workspace(*, tier_b: str = "minimax/MiniMax-M2.7") -> WorkspaceConfig:
    """Workspace with no Batch-B routing keys — today's default shape (D9)."""
    return WorkspaceConfig(
        schema_version=1,
        providers={
            "use_main_model_for_all": True,
            "tier_default": {"triager": tier_b, "B": tier_b},
        },
        gateway=_GATEWAY_TOKEN,
    )


def baseline_split_workspace() -> WorkspaceConfig:
    """Non-unified model workspace for precedence fall-through cases."""
    return WorkspaceConfig(
        schema_version=1,
        providers={
            "use_main_model_for_all": False,
            "tier_default": {
                "triager": "minimax/MiniMax-M2.7",
                "B": "anthropic/claude-sonnet-4-20250514",
            },
        },
        gateway=_GATEWAY_TOKEN,
    )


def prompt_parts_digest(content_root: Path, workspace: WorkspaceConfig) -> str:
    """Stable hash of tier-B system prompt parts for default-off parity (W8.3)."""
    from sevn.agent.context_manifest import tier_b_system_prompt_builders

    parts = tier_b_system_prompt_builders(content_root, workspace=workspace)
    payload = json.dumps(parts, ensure_ascii=False, sort_keys=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@pytest.fixture
def batch_b_content_root(tmp_path: Path) -> Path:
    """Minimal workspace content root for prompt assembly tests."""
    for name in ("AGENTS.md", "MEMORY.md", "SOUL.md", "TOOLS.md", "USER.md"):
        (tmp_path / name).write_text(f"# {name}\n", encoding="utf-8")
    return tmp_path
