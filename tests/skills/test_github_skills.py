"""Bundled GitHub skill tests with mock integration proxy."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from sevn.integrations.github_skill import (
    GithubSkillHooks,
    gh_issues,
    gh_pr,
    github_manager,
    integration_call_from_mapping,
    parse_github_repo,
    resolve_github_skill_hooks,
)
from sevn.tools.integration_gh_repo import legacy_gh_repo_integration_kwargs

_GH_MANAGER_ROOT = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "sevn"
    / "data"
    / "bundled_skills"
    / "core"
    / "github-manager"
)
_GH_PR_ROOT = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "sevn"
    / "data"
    / "bundled_skills"
    / "core"
    / "gh-pr"
)
_GH_ISSUES_ROOT = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "sevn"
    / "data"
    / "bundled_skills"
    / "core"
    / "gh-issues"
)


def _mock_client(responses: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Build a recording mock integration client."""
    return {"calls": [], "responses": responses or {}}


def _hooks(client: dict[str, Any]) -> GithubSkillHooks:
    return GithubSkillHooks(integration_call=integration_call_from_mapping(client))


def _run_script(
    skill_root: Path,
    script_name: str,
    workspace: Path,
    cli_args: list[str] | None = None,
) -> tuple[int, dict[str, object]]:
    script = skill_root / "scripts" / script_name
    env = os.environ.copy()
    env["SEVN_WORKSPACE"] = str(workspace)
    proc = subprocess.run(
        [sys.executable, str(script), *(cli_args or [])],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    payload = json.loads(proc.stdout.strip() or "{}")
    return proc.returncode, payload


def test_parse_github_repo_accepts_slug_and_url() -> None:
    """``parse_github_repo`` normalises slug and HTTPS URLs."""
    assert parse_github_repo("octocat/Hello-World") == ("octocat", "Hello-World")
    assert parse_github_repo("https://github.com/acme/widgets") == ("acme", "widgets")


def test_legacy_gh_repo_maps_to_integration_call() -> None:
    """Legacy aliases still map to GitHub integration kwargs."""
    mapped = legacy_gh_repo_integration_kwargs(
        "gh_repo_list_issues",
        args={"owner": "o", "repo": "r"},
    )
    assert mapped is not None
    assert mapped["service"] == "github"
    assert mapped["method"] == "issues.list_for_repo"


@pytest.mark.asyncio
async def test_list_pull_requests_records_integration_call() -> None:
    """``list_pull_requests`` posts ``pulls.list`` via injectable hook."""
    client = _mock_client({"pulls.list": {"items": [{"number": 12}]}})
    out = await gh_pr.list_pull_requests(_hooks(client), repo="acme/app", state="open")
    assert out["count"] == 1
    assert client["calls"][0]["method"] == "pulls.list"
    assert client["calls"][0]["args"]["owner"] == "acme"


@pytest.mark.asyncio
async def test_create_issue_uses_legacy_alias_mapping() -> None:
    """``create_issue`` routes through ``gh_repo_create_issue`` legacy alias."""
    client = _mock_client({"issues.create": {"number": 3}})
    out = await gh_issues.create_issue(
        _hooks(client),
        repo="acme/app",
        title="Bug",
        body="details",
    )
    assert out["issue"]["number"] == 3
    assert client["calls"][0]["method"] == "issues.create"


@pytest.mark.asyncio
async def test_dispatch_workflow_passes_inputs() -> None:
    """``dispatch_workflow`` forwards workflow dispatch args."""
    client = _mock_client({"actions.create_workflow_dispatch": {"ok": True}})
    out = await github_manager.dispatch_workflow(
        _hooks(client),
        repo="acme/app",
        workflow_id="ci.yml",
        ref="main",
        inputs={"env": "staging"},
    )
    assert out["workflow_id"] == "ci.yml"
    assert client["calls"][0]["args"]["inputs"] == {"env": "staging"}


def test_pr_list_script_subprocess_without_proxy(tmp_path: Path) -> None:
    """``pr_list.py`` subprocess fails cleanly when proxy is not configured."""
    out = asyncio.run(
        gh_pr.list_pull_requests(
            _hooks(_mock_client({"pulls.list": {"items": [{"number": 5}]}})), repo="acme/app"
        ),
    )
    assert out["count"] == 1

    code, payload = _run_script(_GH_PR_ROOT, "pr_list.py", tmp_path, ["acme/app"])
    assert code == 1
    assert payload.get("ok") is False


def test_issue_create_script_without_proxy_returns_error(tmp_path: Path) -> None:
    """``issue_create.py`` returns a failure envelope when proxy is not configured."""
    env = os.environ.copy()
    env.pop("SEVN_PROXY_URL", None)
    env["SEVN_WORKSPACE"] = str(tmp_path)
    script = _GH_ISSUES_ROOT / "scripts" / "issue_create.py"
    proc = subprocess.run(
        [sys.executable, str(script), "acme/app", "--title", "T", "--body", "B"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    payload = json.loads(proc.stdout.strip() or "{}")
    assert proc.returncode == 1
    assert payload.get("ok") is False


def test_branch_list_script_without_proxy_returns_error(tmp_path: Path) -> None:
    """``branch_list.py`` returns a failure envelope when proxy is not configured."""
    env = os.environ.copy()
    env.pop("SEVN_PROXY_URL", None)
    env["SEVN_WORKSPACE"] = str(tmp_path)
    script = _GH_MANAGER_ROOT / "scripts" / "branch_list.py"
    proc = subprocess.run(
        [sys.executable, str(script), "acme/app"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    payload = json.loads(proc.stdout.strip() or "{}")
    assert proc.returncode == 1
    assert payload.get("ok") is False


def test_resolve_hooks_default_without_proxy() -> None:
    """Default hook resolution wires proxy integration caller."""
    hooks = resolve_github_skill_hooks()
    assert hooks.integration_call is not None
