"""Deterministic patch author (`plan/full-tracing-eval-wave-plan.md` Wave E-4)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from sevn.self_improve.proposer.patch_author import (
    author_patch_from_shortlist,
    paths_in_unified_diff,
    preset_requires_proposer,
    reject_patch_glob_scope,
    reject_patch_policy,
    resolve_patch_author_mode,
    write_patch_artefacts,
)


def test_preset_requires_proposer_b_and_c_only() -> None:
    assert preset_requires_proposer("A") is False
    assert preset_requires_proposer("B") is True
    assert preset_requires_proposer("C") is True


def test_resolve_patch_author_mode_accepts_pydantic_agent() -> None:
    assert resolve_patch_author_mode("pydantic_agent") == "pydantic_agent"


def test_resolve_patch_author_mode_fail_closed() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        resolve_patch_author_mode("claude_sdk")


def test_rejects_path_outside_allowed_globs() -> None:
    diff = "+++ b/src/sevn/secret_hack.py\n@@ -0,0 +1 @@\n+noop\n"
    reason = reject_patch_glob_scope(
        diff,
        allowed_globs=["workspace/prompts/**"],
    )
    assert reason is not None
    assert "outside allowed_globs" in reason


def test_allows_path_under_workspace_prompts() -> None:
    diff = "+++ b/workspace/prompts/note.md\n@@ -0,0 +1 @@\n+# ok\n"
    assert (
        reject_patch_glob_scope(
            diff,
            allowed_globs=["workspace/prompts/**"],
        )
        is None
    )


def test_reject_patch_policy_blocks_config_when_disabled() -> None:
    diff = "+++ b/sevn.json\n@@ -0,0 +1 @@\n+{}\n"
    reason = reject_patch_policy(
        diff,
        allow_config_changes=False,
        allow_dependency_changes=False,
        allow_lcm_memory_changes=False,
    )
    assert reason is not None
    assert "allow_config_changes" in reason


def test_author_patch_from_shortlist_writes_under_allowlist(tmp_path: Path) -> None:
    result = asyncio.run(
        author_patch_from_shortlist(
            job_id="job-test-001",
            shortlist={"candidates": [{"turn_id": "t1", "intent": "chat"}]},
            allowed_globs=["workspace/prompts/**"],
        )
    )
    assert result.ok
    assert result.target_path is not None
    assert result.target_path.startswith("workspace/prompts/")
    assert paths_in_unified_diff(result.diff) == [result.target_path]
    assert result.author == "deterministic_stub"

    diff_path = write_patch_artefacts(tmp_path, result)
    assert diff_path.is_file()
    meta = json.loads((tmp_path / "patch" / "meta.json").read_text(encoding="utf-8"))
    assert meta["target_path"] == result.target_path
    assert meta["author"] == "deterministic_stub"


def test_author_rejects_when_no_allowed_target() -> None:
    result = asyncio.run(
        author_patch_from_shortlist(
            job_id="job-x",
            shortlist={"candidates": []},
            allowed_globs=["contrib/**"],
        )
    )
    assert not result.ok
    assert result.rejection is not None
    assert "allowed_globs" in result.rejection
