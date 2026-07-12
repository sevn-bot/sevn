"""Diagnostic agent runtime tests (W4 — no live model calls)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from sevn.agent.diagnostics.runtime import (
    DiagnosticPlan,
    DiagnosticStep,
    is_apply_sevn_command,
    is_readonly_sevn_command,
    load_sevn_diagnostics_skill_body,
    run_diagnostics_agent,
)
from sevn.config.workspace_config import WorkspaceConfig
from sevn.workspace.layout import WorkspaceLayout


@dataclass
class _ListTraceSink:
    events: list = field(default_factory=list)

    async def emit(self, event: object) -> None:
        self.events.append(event)

    async def flush(self) -> None:
        return None

    async def close(self) -> None:
        return None


def test_readonly_allowlist_rejects_mutating_commands() -> None:
    assert is_readonly_sevn_command("sevn gateway status") is True
    assert is_readonly_sevn_command("sevn doctor --fix --yes") is False
    assert is_apply_sevn_command("sevn doctor --fix --yes") is True
    assert is_apply_sevn_command("sevn rm -rf /") is False


def test_skill_body_loads() -> None:
    body = load_sevn_diagnostics_skill_body()
    assert "sevn-diagnostics" in body.lower()
    assert "doctor --with-agent" in body


@pytest.mark.asyncio
async def test_run_diagnostics_agent_plan_override_emits_trace(tmp_path: Path) -> None:
    layout = WorkspaceLayout(
        sevn_json_path=tmp_path / "sevn.json",
        content_root=tmp_path,
    )
    (tmp_path / "sevn.json").write_text('{"schema_version":1}', encoding="utf-8")
    workspace = WorkspaceConfig.minimal()
    plan = DiagnosticPlan(
        summary="fix llmignore",
        steps=[
            DiagnosticStep(
                check_ids=["llmignore"],
                title="Ensure .llmignore layout",
                action_type="auto_fix",
                explanation="catalog auto_fixable",
            ),
        ],
    )
    sink = _ListTraceSink()
    out = await run_diagnostics_agent(
        workspace=workspace,
        layout=layout,
        doctor_report={"checks": [], "warnings": []},
        catalog_json="{}",
        plan_override=plan,
        trace=sink,
    )
    assert out.summary == "fix llmignore"
    assert len(sink.events) == 1
    assert sink.events[0].kind == "diagnostics.agent"
