"""Evolution issue registry tests (`plan/bot-evolution-wave-plan.md` EV-G4)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sevn.config.workspace_config import (
    MySevnIssuesWorkspaceConfig,
    MySevnWorkspaceConfig,
    WorkspaceConfig,
)
from sevn.evolution.issues import (
    EvolutionIssue,
    create_issue,
    get_issue,
    issues_dir,
    list_issues,
    maybe_mirror_issue_to_github,
    my_sevn_repo_slug,
    save_issue,
)
from sevn.gateway.commands.evolution_issue_commands import _parse_file_issue_args
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


def test_create_issue_bug_and_feature_kinds(tmp_path: Path) -> None:
    lay, cfg = _layout(tmp_path)
    bug = create_issue(lay, kind="bug", title="Crash on boot", ws=cfg)
    feature = create_issue(lay, kind="feature", title="Dark mode", ws=cfg)
    assert bug.kind == "bug"
    assert feature.kind == "feature"
    assert (issues_dir(lay) / f"{bug.id}.json").is_file()
    assert (issues_dir(lay) / f"{feature.id}.json").is_file()


def test_get_issue_and_list_issues_crud(tmp_path: Path) -> None:
    lay, _cfg = _layout(tmp_path)
    first = create_issue(lay, kind="bug", title="First")
    second = create_issue(lay, kind="feature", title="Second")
    loaded = get_issue(lay, first.id)
    assert loaded is not None
    assert loaded.title == "First"
    assert get_issue(lay, "missing-id") is None
    rows = list_issues(lay, limit=10)
    assert {row.id for row in rows} == {first.id, second.id}
    first.state = "done"
    first.updated_at = "2026-05-23T12:00:00+00:00"
    save_issue(lay, first)
    updated = get_issue(lay, first.id)
    assert updated is not None
    assert updated.state == "done"


def test_my_sevn_repo_slug_defaults() -> None:
    assert (
        my_sevn_repo_slug(
            WorkspaceConfig(
                schema_version=1, gateway={"token": "${SECRET:keychain:sevn.gateway.token}"}
            )
        )
        == "sevn-bot/sevn"
    )


@pytest.mark.asyncio
async def test_maybe_mirror_issue_to_github_uses_integration_call(tmp_path: Path) -> None:
    lay, cfg = _layout(tmp_path)
    cfg = cfg.model_copy(
        update={
            "my_sevn": MySevnWorkspaceConfig(
                repo_url="https://github.com/acme/widgets",
                issues=MySevnIssuesWorkspaceConfig(prefer_github=True),
            ),
        },
    )
    client: dict[str, object] = {
        "calls": [],
        "responses": {
            "issues.create": {
                "number": 42,
                "html_url": "https://github.com/acme/widgets/issues/42",
            },
        },
    }
    hooks = GithubSkillHooks(integration_call=integration_call_from_mapping(client))
    issue = create_issue(lay, kind="bug", title="Mirror me", ws=cfg)
    mirrored = await maybe_mirror_issue_to_github(lay, issue, cfg, hooks=hooks)
    assert mirrored.github == {
        "number": 42,
        "url": "https://github.com/acme/widgets/issues/42",
    }
    calls = client["calls"]
    assert isinstance(calls, list)
    assert len(calls) == 1
    assert calls[0]["method"] == "issues.create"
    assert calls[0]["args"]["owner"] == "acme"
    assert calls[0]["args"]["repo"] == "widgets"
    on_disk = json.loads((issues_dir(lay) / f"{issue.id}.json").read_text(encoding="utf-8"))
    assert on_disk["github"]["number"] == 42


@pytest.mark.asyncio
async def test_maybe_mirror_skips_when_prefer_github_false(tmp_path: Path) -> None:
    lay, cfg = _layout(tmp_path)
    cfg = cfg.model_copy(
        update={
            "my_sevn": MySevnWorkspaceConfig(
                issues=MySevnIssuesWorkspaceConfig(prefer_github=False),
            ),
        },
    )
    client: dict[str, object] = {"calls": [], "responses": {}}
    hooks = GithubSkillHooks(integration_call=integration_call_from_mapping(client))
    issue = create_issue(lay, kind="feature", title="Local only", ws=cfg)
    mirrored = await maybe_mirror_issue_to_github(lay, issue, cfg, hooks=hooks)
    assert mirrored.github is None
    assert client["calls"] == []


def test_parse_file_issue_args() -> None:
    assert _parse_file_issue_args("/file_issue bug Login fails") == (
        "bug",
        "Login fails",
        "",
    )
    assert _parse_file_issue_args("/file_issue feature") == ("feature", "", "")
    assert _parse_file_issue_args("/file_issue") == (None, "", "")


def test_evolution_issue_roundtrip_dict() -> None:
    row = EvolutionIssue(
        id="abc",
        kind="feature",
        title="T",
        body="body",
        state="open",
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
        source="manual",
        github={"number": 1, "url": "https://example.com/1"},
    )
    restored = EvolutionIssue.from_dict(row.to_dict())
    assert restored.kind == "feature"
    assert restored.github == {"number": 1, "url": "https://example.com/1"}
