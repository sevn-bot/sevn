"""Install orchestrator tests (`plan/onboarding-comprehensive-setup` W6)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from sevn.onboarding.capabilities_manifest import InstallAction, load_manifest
from sevn.onboarding.install_orchestrator import (
    InstallPlan,
    InstallPlanStep,
    build_install_plan,
    collect_install_run,
    selected_capability_ids,
)
from sevn.onboarding.seed import opt_in_skill_ids_from_capabilities, seed_bundled_skills
from sevn.onboarding.web_app import create_onboarding_app


def test_selected_capability_ids_from_merged_config() -> None:
    """Enabled extras map to manifest capability ids."""
    merged = {
        "skills": {"browser": {"enabled": True}, "graphify": {"enabled": False}},
        "tools": {"browser": {"enabled": True}},
    }
    ids = selected_capability_ids(merged)
    assert "extra.browser" in ids
    assert "extra.browser_cdp" in ids
    assert "extra.graphify" not in ids


def test_build_install_plan_orders_browser_before_playwright() -> None:
    """``extra.browser.uv`` precedes ``extra.browser.cmd`` in the plan."""
    plan = build_install_plan({"skills": {"browser": {"enabled": True}}})
    action_ids = [step.action.id for step in plan.steps]
    assert action_ids.index("extra.browser.uv") < action_ids.index("extra.browser.cmd")


def test_build_install_plan_expands_graphify_dependency() -> None:
    """Code-understanding graphify pulls in ``extra.graphify`` uv step."""
    plan = build_install_plan(
        {"code_understanding": {"graphify": {"enabled": True}}},
    )
    selected = set(plan.selected_capability_ids)
    assert "extra.graphify" in selected
    assert "code_understanding.graphify" in selected
    assert any(step.action.id == "extra.graphify.uv" for step in plan.steps)


@pytest.mark.asyncio
async def test_collect_install_run_skips_when_idempotent_check_passes() -> None:
    """Playwright install is skipped when ``playwright --version`` succeeds."""
    browser_cmd = InstallAction(
        id="extra.browser.cmd",
        kind="subprocess",
        argv=["playwright", "install", "chromium"],
        fatal=True,
        idempotent_check="playwright --version",
    )
    plan = InstallPlan(
        (InstallPlanStep("extra.browser", browser_cmd),),
        1,
        0,
        ("extra.browser",),
    )
    with patch(
        "sevn.onboarding.install_actions.executors.idempotent_check_satisfied",
        new=AsyncMock(return_value=True),
    ):
        summary = await collect_install_run(plan, install_root=Path("."))
    assert "extra.browser.cmd" in summary.skipped_action_ids


@pytest.mark.asyncio
async def test_collect_install_run_mocked_subprocess() -> None:
    """Subprocess actions yield ok end events when mocked."""
    action = InstallAction(
        id="cli.roam_code.cmd",
        kind="subprocess",
        argv=["uv", "tool", "install", "roam-code"],
        fatal=True,
    )
    plan = InstallPlan(
        (InstallPlanStep("cli.roam_code", action),),
        1,
        0,
        ("cli.roam_code",),
    )

    async def _fake_stream(action, *, capability_id, argv, cwd):
        _ = (action, capability_id, argv, cwd)
        yield {"type": "log", "action_id": "cli.roam_code.cmd", "line": "installed"}
        yield {
            "type": "end",
            "action_id": "cli.roam_code.cmd",
            "status": "ok",
            "exit_code": 0,
            "fatal": True,
        }

    with patch(
        "sevn.onboarding.install_actions.executors._run_subprocess_stream",
        side_effect=_fake_stream,
    ):
        summary = await collect_install_run(plan, install_root=Path("."))
    assert summary.ok is True
    assert summary.fatal_failed is False


def test_opt_in_skills_seeded_when_capability_enabled(tmp_path: Path) -> None:
    """computer-use core package is copied only when capability is selected."""
    seed_bundled_skills(tmp_path)
    assert not (tmp_path / "skills" / "core" / "computer-use").exists()
    with_opt_in = seed_bundled_skills(
        tmp_path,
        enabled_opt_in_skill_ids=opt_in_skill_ids_from_capabilities({"skill.computer_use"}),
    )
    assert (tmp_path / "skills" / "core" / "computer-use" / "SKILL.md").is_file()
    assert any("computer-use" in str(p) for p in with_opt_in)


def test_api_install_plan_dry_run() -> None:
    """``POST /api/install-plan`` returns steps without executing subprocesses."""
    client = TestClient(create_onboarding_app("test-token"))
    body = {
        "fields": {"skills.browser.enabled": True},
    }
    res = client.post(
        "/api/install-plan",
        headers={"X-Onboard-Token": "test-token"},
        json=body,
    )
    assert res.status_code == 200
    payload = res.json()
    assert payload["ok"] is True
    assert payload["fatal_count"] >= 1
    ids = [step["action"]["id"] for step in payload["steps"]]
    assert "extra.browser.uv" in ids


def test_api_install_run_streams_ndjson() -> None:
    """``POST /api/install-run`` returns NDJSON progress lines."""
    client = TestClient(create_onboarding_app("test-token"))
    noop_plan = InstallPlan(
        (InstallPlanStep("t", InstallAction(id="t.n", kind="noop", argv=[], fatal=False)),),
        0,
        1,
        ("t",),
    )
    with patch("sevn.onboarding.install_orchestrator.build_install_plan", return_value=noop_plan):
        res = client.post(
            "/api/install-run",
            headers={"X-Onboard-Token": "test-token"},
            json={"fields": {}},
        )
    assert res.status_code == 200
    lines = [ln for ln in res.text.strip().splitlines() if ln.strip()]
    events = [json.loads(ln) for ln in lines]
    assert events[0]["type"] == "start"
    assert events[-1]["type"] == "end"


def test_every_fatal_capability_has_install_actions() -> None:
    """Manifest fatal rows are executable kinds (not missing argv)."""
    manifest = load_manifest()
    for cap in manifest.capabilities:
        for action in cap.install_actions:
            if not action.fatal:
                continue
            if action.kind == "noop":
                continue
            assert action.argv or action.kind == "secret_required", (
                f"{cap.capability_id} action {action.id} missing argv"
            )
