"""Tests for Mission Control dashboard schema contract (Wave W1)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from scripts.check_mission_control_schema import collect_schema_gaps
from scripts.check_mission_control_schema import main as check_main
from scripts.mission_control_schema_lib import (
    GOLDEN_PATH,
    META_SCHEMA_PATH,
    build_schema_document,
    collect_api_v1_routes,
    endpoint_matches_route,
    normalize_schema_for_compare,
)

from sevn.ui.dashboard.dashboard_schema import (
    DASHBOARD_TAB_DESCRIPTORS,
    missing_descriptor_slugs,
)
from sevn.ui.dashboard.tab_registry import WIRED_SLUGS, build_nav_payload

REPO = Path(__file__).resolve().parents[3]


def test_all_registry_slugs_have_descriptors() -> None:
    assert missing_descriptor_slugs() == []
    assert len(DASHBOARD_TAB_DESCRIPTORS) == 46


def test_wired_slugs_covered_by_descriptors() -> None:
    assert set(DASHBOARD_TAB_DESCRIPTORS) >= WIRED_SLUGS


def test_golden_in_sync_with_live_merge() -> None:
    doc = build_schema_document()
    committed = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    assert normalize_schema_for_compare(committed) == normalize_schema_for_compare(doc)


def test_golden_validates_against_meta_schema() -> None:
    result = subprocess.run(
        [
            "uv",
            "run",
            "check-jsonschema",
            f"--schemafile={META_SCHEMA_PATH}",
            str(GOLDEN_PATH),
        ],
        cwd=REPO,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_collect_schema_gaps_clean_on_tree() -> None:
    hard, _warnings = collect_schema_gaps()
    assert hard == []


def test_endpoint_matcher_handles_path_params() -> None:
    routes = collect_api_v1_routes()
    assert endpoint_matches_route(
        method="GET",
        endpoint="/api/v1/sessions/{id}/api-calls",
        routes=routes,
    )


def test_check_main_exits_nonzero_on_injected_drift(tmp_path: Path, monkeypatch) -> None:
    golden = tmp_path / "mission-control.schema.json"
    doc = build_schema_document()
    doc["tab_count"] = 999
    golden.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    monkeypatch.setattr(
        "scripts.check_mission_control_schema.GOLDEN_PATH",
        golden,
    )
    monkeypatch.setattr(
        "scripts.mission_control_schema_lib.GOLDEN_PATH",
        golden,
    )
    assert check_main([]) == 1


def test_build_schema_document_includes_nav_and_routes() -> None:
    doc = build_schema_document(generated_at="2026-06-14T00:00:00+00:00")
    assert doc["nav"]["tab_count"] == build_nav_payload()["tab_count"]
    assert len(doc["routes"]) >= 100
    assert "overview" in doc["tabs"]
