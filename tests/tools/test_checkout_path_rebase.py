"""Mode B fix: absolute checkout paths rebase onto the ``source_code/`` mirror.

Tier-B models (notably MiniMax-M3) echo the absolute sevn checkout path from the
transcript instead of the prompt-mandated ``source_code/…`` workspace path. The file-tool
sandbox is jailed to the workspace root, so such paths were rejected as ``escapes
workspace root``. These tests cover the deterministic rebase + the ``did_you_mean``
fallback for workspace-only artefacts (e.g. ``logs/gateway.log``).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sevn.tools.base import ToolCall, ToolExecutor
from sevn.tools.context import ToolContext
from sevn.tools.paths import rebase_checkout_absolute_path
from sevn.tools.permissions import AllowAllPermissionPolicy
from sevn.tools.registry import build_session_registry


def test_rebase_maps_absolute_checkout_path() -> None:
    checkout = Path("/repo")
    assert rebase_checkout_absolute_path("/repo/src/x.py", checkout) == "source_code/src/x.py"
    assert rebase_checkout_absolute_path("/repo", checkout) == "source_code"


def test_rebase_ignores_relative_outside_and_no_checkout() -> None:
    checkout = Path("/repo")
    assert rebase_checkout_absolute_path("src/x.py", checkout) is None
    assert rebase_checkout_absolute_path("/elsewhere/x.py", checkout) is None
    assert rebase_checkout_absolute_path("/repo/x.py", None) is None


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    root = tmp_path / "checkout"
    root.mkdir()
    return root


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    (root / "source_code" / "src" / "sevn").mkdir(parents=True)
    (root / "source_code" / "src" / "sevn" / "x.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "logs").mkdir()
    (root / "logs" / "gateway.log").write_text("line one\n", encoding="utf-8")
    return root


@pytest.fixture
def ctx(workspace: Path, checkout: Path) -> ToolContext:
    return ToolContext(
        session_id="rebase-sess",
        workspace_path=workspace,
        workspace_id="rebase-wid",
        registry_version=1,
        trace=None,
        permissions=AllowAllPermissionPolicy(),
        checkout_path=checkout,
    )


@pytest.fixture
def executor() -> ToolExecutor:
    exe, _tool_set = build_session_registry(registry_version=1)
    return exe


@pytest.mark.asyncio
async def test_read_absolute_checkout_path_resolves_to_mirror(
    ctx: ToolContext,
    executor: ToolExecutor,
    checkout: Path,
) -> None:
    abs_path = str(checkout / "src" / "sevn" / "x.py")
    raw = await executor.dispatch(ctx, ToolCall(name="read", arguments={"path": abs_path}))
    payload = json.loads(raw)
    assert payload["ok"] is True, payload
    assert "VALUE = 1" in json.dumps(payload["data"])


@pytest.mark.asyncio
async def test_list_dir_absolute_checkout_root_lists_mirror(
    ctx: ToolContext,
    executor: ToolExecutor,
    checkout: Path,
) -> None:
    raw = await executor.dispatch(
        ctx,
        ToolCall(name="list_dir", arguments={"path": str(checkout)}),
    )
    payload = json.loads(raw)
    assert payload["ok"] is True, payload
    assert "src" in json.dumps(payload["data"])


@pytest.mark.asyncio
async def test_read_workspace_artifact_via_checkout_path_suggests_bare_tail(
    ctx: ToolContext,
    executor: ToolExecutor,
    checkout: Path,
) -> None:
    # `<checkout>/logs/gateway.log` rebases to `source_code/logs/gateway.log`, which the
    # mirror lacks (logs are a runtime workspace artefact) — the did_you_mean fallback
    # should surface the bare workspace-relative `logs/gateway.log`.
    abs_path = str(checkout / "logs" / "gateway.log")
    raw = await executor.dispatch(ctx, ToolCall(name="read", arguments={"path": abs_path}))
    payload = json.loads(raw)
    assert payload["ok"] is False, payload
    assert "logs/gateway.log" in payload.get("did_you_mean", [])
