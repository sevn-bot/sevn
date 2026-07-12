"""Agent context manifest golden and fixture alignment."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.agent_context_manifest_lib import (
    GOLDEN_PATH,
    build_schema_document,
    normalize_for_compare,
)

from sevn.agent.context_manifest import build_agent_context_manifest, collect_manifest_slot_ids

REPO = Path(__file__).resolve().parents[2]
FIXTURE_PATH = REPO / "tests" / "fixtures" / "agent_context" / "example_turn.json"


def test_golden_manifest_matches_live_builder() -> None:
    assert GOLDEN_PATH.is_file(), "run make agent-context-manifest-generate"
    committed = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    live = build_schema_document()
    assert normalize_for_compare(committed) == normalize_for_compare(live)


def test_example_turn_slot_ids_in_manifest() -> None:
    manifest = build_agent_context_manifest(git_commit="test")
    slot_ids = collect_manifest_slot_ids(manifest)
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    for span in fixture.get("spans", {}).values():
        if not isinstance(span, dict):
            continue
        slots = span.get("slots", {})
        if not isinstance(slots, dict):
            continue
        for slot_id in slots:
            assert slot_id in slot_ids, f"fixture slot {slot_id!r} missing from manifest"


def test_manifest_agents_include_core_tiers() -> None:
    manifest = build_schema_document()
    ids = {a["id"] for a in manifest["agents"]}
    assert {"triager", "tier_a", "tier_b", "tier_c_dspy", "tier_c_lambda"} <= ids
