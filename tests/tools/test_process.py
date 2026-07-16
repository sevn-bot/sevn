"""RED suite for ``process`` self-correction + slug orientation (D8/D9; green after W3)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from sevn.config.my_sevn import effective_my_sevn
from sevn.config.workspace_config import WorkspaceConfig
from sevn.integrations.github_skill import parse_github_repo
from sevn.tools.base import ToolCall
from sevn.tools.context import ToolContext
from sevn.tools.permissions import AllowAllPermissionPolicy
from sevn.tools.process import reset_process_store_for_tests
from sevn.tools.registry import build_session_registry

_XFAIL_W3 = pytest.mark.xfail(
    reason="green after W3: process read alias + job status (D8/D9)", strict=False
)


@pytest.fixture(autouse=True)
def _clean_stores() -> None:
    reset_process_store_for_tests()
    yield
    reset_process_store_for_tests()


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    root.mkdir()
    return root


@pytest.fixture
def ctx(workspace: Path) -> ToolContext:
    return ToolContext(
        session_id="proc-d8-sess",
        workspace_path=workspace,
        workspace_id="proc-d8-wid",
        registry_version=1,
        trace=None,
        permissions=AllowAllPermissionPolicy(),
    )


async def _start_echo_job(ctx: ToolContext) -> str:
    exe, _ = build_session_registry(registry_version=1)
    raw = await exe.dispatch(
        ctx,
        ToolCall(
            name="process",
            arguments={
                "action": "start",
                "argv": [sys.executable, "-u", "-c", "print('d8-hello', flush=True)"],
            },
        ),
    )
    env = json.loads(raw)
    assert env["ok"] is True
    return str(env["data"]["job_id"])


@_XFAIL_W3
@pytest.mark.asyncio
async def test_d8_action_read_aliases_output(ctx: ToolContext) -> None:
    """D8: ``action='read'`` returns the same payload shape as ``action='output'``."""
    job_id = await _start_echo_job(ctx)
    exe, _ = build_session_registry(registry_version=1)

    out_raw = await exe.dispatch(
        ctx,
        ToolCall(name="process", arguments={"action": "output", "job_id": job_id}),
    )
    read_raw = await exe.dispatch(
        ctx,
        ToolCall(name="process", arguments={"action": "read", "job_id": job_id}),
    )
    out_env = json.loads(out_raw)
    read_env = json.loads(read_raw)
    assert read_env["ok"] is True
    assert out_env["ok"] is True
    assert read_env["data"]["job_id"] == out_env["data"]["job_id"] == job_id
    assert "stdout" in read_env["data"]
    assert read_env["data"]["stdout"] == out_env["data"]["stdout"]


@_XFAIL_W3
@pytest.mark.asyncio
async def test_d8_action_run_still_returns_did_you_mean(ctx: ToolContext) -> None:
    """D8: ``action='run'`` stays ambiguous and returns ``did_you_mean`` (not an alias)."""
    exe, _ = build_session_registry(registry_version=1)
    raw = await exe.dispatch(
        ctx,
        ToolCall(name="process", arguments={"action": "run", "command": "echo hi"}),
    )
    env = json.loads(raw)
    assert env["ok"] is False
    assert "did_you_mean" in env
    suggestions = env["did_you_mean"]
    assert isinstance(suggestions, list)
    assert "start" in suggestions or "output" in suggestions


@_XFAIL_W3
@pytest.mark.asyncio
async def test_d8_wrong_action_error_includes_job_status(ctx: ToolContext) -> None:
    """D8: wrong-action errors include the referenced job's current status."""
    job_id = await _start_echo_job(ctx)
    exe, _ = build_session_registry(registry_version=1)
    raw = await exe.dispatch(
        ctx,
        ToolCall(
            name="process",
            arguments={"action": "explode", "job_id": job_id},
        ),
    )
    env = json.loads(raw)
    assert env["ok"] is False
    blob = json.dumps(env).lower()
    assert job_id in json.dumps(env)
    assert any(status in blob for status in ("running", "completed", "stopped", "failed"))


@_XFAIL_W3
def test_d9_slug_defaults_from_my_sevn_repo_url_without_git_remote() -> None:
    """D9: GitHub slug resolves from ``my_sevn.repo_url`` — never via ``git remote``."""
    ws = WorkspaceConfig.minimal()
    url = effective_my_sevn(ws).repo_url
    owner, name = parse_github_repo(url)
    assert f"{owner}/{name}" == "sevn-bot/sevn"

    # W3 surfaces a helper / orientation field the tools share.
    from sevn.config import my_sevn as my_sevn_mod

    resolver = getattr(my_sevn_mod, "default_github_repo_slug", None) or getattr(
        my_sevn_mod, "github_repo_slug_from_config", None
    )
    assert callable(resolver), "slug helper must exist so tools never shell out to git remote"
    assert resolver(ws) == "sevn-bot/sevn"
