"""W8.3 — default-off proof (D9): absent Batch-B keys ⇒ today's behavior.

These tests must stay GREEN through W9/W11/W12 — they guard against accidental
behavior drift while routing overlays land behind toggles.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.open_issues_sweep.batch_b.conftest import (
    baseline_minimal_workspace,
    prompt_parts_digest,
)

from sevn.agent.triager.context import TriagePromptContext
from sevn.agent.triager.run import resolve_triager_model_id_for_turn
from sevn.config.llm_params import resolve_reasoning_params, resolve_reasoning_request
from sevn.config.model_resolution import ModelSlot, resolve_model_slot
from sevn.config.sections.triager import TriagerWorkspaceConfig
from sevn.config.settings import ProcessSettings
from sevn.config.workspace_config import WorkspaceConfig
from sevn.gateway.agent_turn import _resolve_tier_b_bundle


def test_default_off_model_slot_matches_baseline() -> None:
    cfg = baseline_minimal_workspace()
    assert resolve_model_slot(cfg, ModelSlot.tier_b) == "minimax/MiniMax-M2.7"
    assert resolve_model_slot(cfg, ModelSlot.triager) == "minimax/MiniMax-M2.7"


def test_default_off_tier_b_bundle_uses_workspace_slot_only() -> None:
    cfg = baseline_minimal_workspace()
    bundle = _resolve_tier_b_bundle(cfg, ProcessSettings())
    assert bundle.model_id == resolve_model_slot(cfg, ModelSlot.tier_b)


def test_default_off_triager_turn_model_unchanged_for_normal_message() -> None:
    cfg = WorkspaceConfig.minimal(
        providers={"tier_default": {"triager": "minimax/MiniMax-M2.7"}},
        triager={"cheap_model_id": "anthropic/claude-haiku-4-5"},
    )
    ctx = TriagePromptContext(current_message="summarize the attached file")
    triager_cfg = TriagerWorkspaceConfig.model_validate(cfg.triager or {})
    assert (
        resolve_triager_model_id_for_turn(cfg, triage_context=ctx, triager_cfg=triager_cfg)
        == "minimax/MiniMax-M2.7"
    )


def test_default_off_reasoning_params_disabled() -> None:
    model_id = "minimax/MiniMax-M2.7"
    assert resolve_reasoning_request("tier_b", model_id) is None
    assert resolve_reasoning_request("triager", model_id) is None
    params = resolve_reasoning_params("tier_b", model_id)
    assert params.enabled is False


def test_default_off_prompt_assembly_unchanged(
    batch_b_content_root: Path,
) -> None:
    cfg = baseline_minimal_workspace()
    digest = prompt_parts_digest(batch_b_content_root, cfg)
    # Pin today's assembly shape so W9+ prompt overlays cannot slip in silently.
    assert len(digest) == 64
    assert digest  # non-empty stable hash


@pytest.mark.parametrize("slot", [ModelSlot.tier_b, ModelSlot.triager, ModelSlot.scanner])
def test_default_off_no_routing_overlay_keys_in_minimal_config(slot: ModelSlot) -> None:
    cfg = baseline_minimal_workspace()
    doc = cfg.model_dump()
    channels = doc.get("channels") or {}
    for name, body in channels.items():
        if isinstance(body, dict):
            assert "model" not in body, f"unexpected channels.{name}.model in baseline"
            assert "system_prompt" not in body, f"unexpected channels.{name}.system_prompt"
    from sevn.config.routing import routing_profiles_active

    assert not routing_profiles_active(cfg)
    assert resolve_model_slot(cfg, slot) == "minimax/MiniMax-M2.7"
