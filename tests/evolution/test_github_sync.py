"""GitHub inbound issue sync tests (`plan/full-loop-evolution-wave-plan.md` FL-1.6)."""

from __future__ import annotations

from pathlib import Path

import pytest

from sevn.config.workspace_config import (
    MySevnIssuesWorkspaceConfig,
    MySevnWorkspaceConfig,
    WorkspaceConfig,
)
from sevn.evolution.github_sync import (
    import_github_issue,
    sync_github_issues,
)
from sevn.evolution.issues import list_issues
from sevn.integrations.github_skill.hooks import GithubSkillHooks, integration_call_from_mapping
from sevn.workspace.layout import WorkspaceLayout


def _layout(tmp_path: Path) -> tuple[WorkspaceLayout, WorkspaceConfig]:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "workspace_root": ".", "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    cfg = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    return WorkspaceLayout.from_config(sevn_json, cfg), cfg


def _hooks(responses: dict[str, object]) -> tuple[GithubSkillHooks, dict[str, object]]:
    client: dict[str, object] = {"calls": [], "responses": responses}
    return GithubSkillHooks(integration_call=integration_call_from_mapping(client)), client


@pytest.mark.asyncio
async def test_import_github_issue_creates_github_source(tmp_path: Path) -> None:
    lay, cfg = _layout(tmp_path)
    hooks, _client = _hooks(
        {"issues.get": {"number": 42, "title": "Crash on boot", "labels": [{"name": "bug"}]}},
    )
    issue = await import_github_issue(lay, hooks, repo="o/r", number=42, ws=cfg)
    assert issue.source == "github"
    assert issue.github == {"number": 42, "url": ""}
    assert issue.kind == "bug"


@pytest.mark.asyncio
async def test_import_github_issue_is_idempotent(tmp_path: Path) -> None:
    lay, cfg = _layout(tmp_path)
    hooks, _client = _hooks(
        {"issues.get": {"number": 42, "title": "First", "labels": []}},
    )
    first = await import_github_issue(lay, hooks, repo="o/r", number=42, ws=cfg)
    hooks2, _client2 = _hooks(
        {"issues.get": {"number": 42, "title": "Updated title", "labels": []}},
    )
    second = await import_github_issue(lay, hooks2, repo="o/r", number=42, ws=cfg)
    assert second.id == first.id
    assert second.title == "Updated title"
    rows = [row for row in list_issues(lay, limit=50) if row.github]
    assert len([row for row in rows if row.github == {"number": 42, "url": ""}]) == 1


@pytest.mark.asyncio
async def test_label_to_kind_mapping(tmp_path: Path) -> None:
    lay, cfg = _layout(tmp_path)
    cfg = cfg.model_copy(
        update={
            "my_sevn": MySevnWorkspaceConfig(
                issues=MySevnIssuesWorkspaceConfig(
                    label_map={"bug": "bug", "enhancement": "feature"},
                ),
            ),
        },
    )
    hooks, _client = _hooks(
        {
            "issues.get": {
                "number": 7,
                "title": "Add dark mode",
                "labels": [{"name": "enhancement"}],
            }
        },
    )
    issue = await import_github_issue(lay, hooks, repo="o/r", number=7, ws=cfg)
    assert issue.kind == "feature"


@pytest.mark.asyncio
async def test_sync_skips_closed_unless_state_all(tmp_path: Path) -> None:
    lay, cfg = _layout(tmp_path)
    rows = [
        {"number": 1, "title": "Open one", "state": "open", "labels": []},
        {"number": 2, "title": "Closed one", "state": "closed", "labels": []},
    ]
    hooks, _client = _hooks({"issues.list_for_repo": {"items": rows}})
    result = await sync_github_issues(lay, hooks, repo="o/r", ws=cfg, state="open")
    assert result.imported == 1
    assert result.skipped == 1

    hooks_all, _client_all = _hooks({"issues.list_for_repo": {"items": rows}})
    result_all = await sync_github_issues(lay, hooks_all, repo="o/r", ws=cfg, state="all")
    # Issue 1 already exists (updated), issue 2 newly imported; none skipped.
    assert result_all.skipped == 0
    assert result_all.imported + result_all.updated == 2


@pytest.mark.asyncio
async def test_sync_is_idempotent_on_github_number(tmp_path: Path) -> None:
    lay, cfg = _layout(tmp_path)
    rows = [{"number": 5, "title": "Repeatable", "state": "open", "labels": []}]
    hooks, _client = _hooks({"issues.list_for_repo": {"items": rows}})
    await sync_github_issues(lay, hooks, repo="o/r", ws=cfg)
    hooks2, _client2 = _hooks({"issues.list_for_repo": {"items": rows}})
    second = await sync_github_issues(lay, hooks2, repo="o/r", ws=cfg)
    assert second.updated == 1
    assert second.imported == 0
    matching = [row for row in list_issues(lay, limit=50) if row.github == {"number": 5, "url": ""}]
    assert len(matching) == 1
