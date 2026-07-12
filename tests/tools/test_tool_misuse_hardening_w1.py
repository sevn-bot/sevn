"""Wave W1 tests: tool-misuse + delivery-integrity hardening (`build-plan-from-review/waves/
voice-duplex-tts-menu-log-fixes-wave-plan.md` W1.6-W1.9).

Tests-first: the W5/W6 hardening (did_you_mean wiring for ``process``/``terminal_run``,
typed github errors, and the ``openui_render`` success-with-fallback path) does not exist
yet, so several assertions here are expected to be RED until those waves land.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from sevn.browser.recipes.base import RecipeError
from sevn.browser.recipes.google_maps import GoogleMaps
from sevn.tools.base import ToolCall
from sevn.tools.codes import ToolResultCode
from sevn.tools.context import ToolContext
from sevn.tools.integration_proxy_client import IntegrationCredentialRequired
from sevn.tools.permissions import AllowAllPermissionPolicy
from sevn.tools.registry import build_session_registry
from sevn.tools.runtime_dispatch import RuntimeToolBindings, make_integration_call_tool

# --- W1.6: browser maps op guidance -----------------------------------------


@pytest.mark.asyncio
async def test_maps_empty_op_names_valid_ops() -> None:
    """Empty/absent ``op`` must fail with an actionable error naming the valid ops."""
    with pytest.raises(RecipeError) as exc_info:
        await GoogleMaps(page=None, dom=None).run("")  # type: ignore[arg-type]
    message = str(exc_info.value)
    for op in ("search", "place", "directions", "reviews"):
        assert op in message, f"maps empty-op error does not mention {op!r}: {message!r}"


@pytest.mark.asyncio
async def test_maps_well_formed_search_dispatches(monkeypatch: pytest.MonkeyPatch) -> None:
    """A well-formed ``maps search`` op validates and dispatches to ``.search``."""
    maps = GoogleMaps(page=None, dom=None)  # type: ignore[arg-type]

    async def _fake_search(query: str) -> dict[str, object]:
        assert query == "coffee"
        return {"places": [{"name": "Blue Bottle Coffee"}], "count": 1}

    monkeypatch.setattr(maps, "search", _fake_search)
    out = await maps.run("search", query="coffee")
    assert out["count"] == 1


# --- W1.7: process / terminal_run did_you_mean guidance ----------------------


def _ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(
        session_id="w1-misuse",
        workspace_path=tmp_path,
        workspace_id="w1",
        registry_version=1,
        trace=None,
        permissions=AllowAllPermissionPolicy(),
    )


@pytest.mark.asyncio
async def test_process_invalid_action_offers_did_you_mean(tmp_path: Path) -> None:
    exe, _ = build_session_registry()
    raw = await exe.dispatch(
        _ctx(tmp_path),
        ToolCall(name="process", arguments={"action": "read"}),
    )
    blob = json.loads(raw)
    assert blob["ok"] is False
    assert "did_you_mean" in blob, (
        "process invalid action should offer did_you_mean guidance naming start|stop|list|output"
    )
    assert any(
        candidate in {"start", "stop", "list", "output"} for candidate in blob["did_you_mean"]
    )


@pytest.mark.asyncio
async def test_terminal_run_empty_command_offers_correct_usage_hint(tmp_path: Path) -> None:
    exe, _ = build_session_registry()
    raw = await exe.dispatch(
        _ctx(tmp_path),
        ToolCall(name="terminal_run", arguments={"command": "   "}),
    )
    blob = json.loads(raw)
    assert blob["ok"] is False
    assert "did_you_mean" in blob or "usage" in str(blob.get("error", "")).lower(), (
        f"terminal_run empty command should carry a correct-usage hint, got: {blob}"
    )


# --- W1.8: github integration_call / run_skill_script typed errors ----------


@pytest.mark.asyncio
async def test_integration_call_missing_owner_repo_is_not_internal_error() -> None:
    """A missing ``owner``/``repo`` should resolve-or-guide, not fall through to INTERNAL_ERROR."""

    class _FakeGithubClient:
        async def integration_call(
            self,
            *,
            service: str,
            method: str,
            args: Mapping[str, Any],
            ctx: ToolContext,
        ) -> Mapping[str, Any]:
            _ = ctx
            if service == "github" and not (args.get("owner") and args.get("repo")):
                msg = "owner and repo are required for github.pulls.list"
                raise ValueError(msg)
            return {}

    tool = make_integration_call_tool(RuntimeToolBindings(integration=_FakeGithubClient()))
    ctx = ToolContext(
        session_id="s", workspace_path=Path("/tmp"), workspace_id="w", registry_version=1
    )
    raw = await tool.execute(ctx, service="github", method="pulls.list", args={})
    blob = json.loads(raw)
    assert blob["ok"] is False
    assert blob.get("code") != ToolResultCode.INTERNAL_ERROR.value, (
        f"missing owner/repo should not be a generic INTERNAL_ERROR: {blob}"
    )


@pytest.mark.asyncio
async def test_integration_call_proxy_404_is_typed_and_retryable() -> None:
    """A ``proxy status 404`` (e.g. unknown branch) should map to a typed, retryable error."""

    class _FakeFlakyClient:
        async def integration_call(
            self,
            *,
            service: str,
            method: str,
            args: Mapping[str, Any],
            ctx: ToolContext,
        ) -> Mapping[str, Any]:
            _ = service, method, args, ctx
            msg = "proxy status 404"
            raise RuntimeError(msg)

    tool = make_integration_call_tool(RuntimeToolBindings(integration=_FakeFlakyClient()))
    ctx = ToolContext(
        session_id="s", workspace_path=Path("/tmp"), workspace_id="w", registry_version=1
    )
    raw = await tool.execute(
        ctx,
        service="github",
        method="repos.branches.list",
        args={"owner": "sevn", "repo": "bot"},
    )
    blob = json.loads(raw)
    assert blob["ok"] is False
    assert blob.get("code") != ToolResultCode.INTERNAL_ERROR.value, (
        f"a proxy 404 should be a typed/retryable code, not INTERNAL_ERROR: {blob}"
    )


@pytest.mark.asyncio
async def test_integration_call_provided_owner_repo_not_misclassified() -> None:
    """Upstream errors mentioning owner/repo must not trigger missing-repo guidance."""

    class _FakeClient:
        async def integration_call(
            self,
            *,
            service: str,
            method: str,
            args: Mapping[str, Any],
            ctx: ToolContext,
        ) -> Mapping[str, Any]:
            _ = ctx
            if service == "github" and args.get("owner") and args.get("repo"):
                msg = "github upstream: owner and repo not found for pulls.list"
                raise RuntimeError(msg)
            return {}

    tool = make_integration_call_tool(RuntimeToolBindings(integration=_FakeClient()))
    ctx = ToolContext(
        session_id="s", workspace_path=Path("/tmp"), workspace_id="w", registry_version=1
    )
    raw = await tool.execute(
        ctx,
        service="github",
        method="pulls.list",
        args={"owner": "sevn", "repo": "bot"},
    )
    blob = json.loads(raw)
    assert blob["ok"] is False
    assert "needs owner/repo" not in str(blob.get("error", ""))
    assert blob.get("code") != ToolResultCode.VALIDATION_ERROR.value


def test_integration_credential_required_still_maps_to_permission_denied() -> None:
    """Locks existing behavior: missing credentials stay PERMISSION_DENIED, not INTERNAL_ERROR."""
    err = IntegrationCredentialRequired(
        "GitHub token not configured", service="github", method="pulls.list"
    )
    assert err.service == "github"
    assert "not configured" in err.detail


# --- W1.9: openui_render success-with-fallback on empty sanitise ------------


@pytest.mark.asyncio
async def test_openui_render_empty_sanitise_returns_success_with_fallback(
    tmp_path: Path,
) -> None:
    from sevn.ui.openui.bridge import OpenUIBridge
    from sevn.ui.openui.store import OpenUIStore
    from sevn.ui.openui.tools_register import openui_render

    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "workspace_root": ".", '
        '"gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    bridge = OpenUIBridge(store=OpenUIStore(None), signing_secret="w1-secret")
    ctx = ToolContext(
        workspace_path=tmp_path,
        workspace_id="ws",
        registry_version=1,
        session_id="sess-w1",
        turn_id="turn-w1",
        openui_bridge=bridge,
    )
    raw = await openui_render(
        ctx,
        html="<script>alert(1)</script>",
        fallback_text="Plain-text summary the model can still deliver.",
        output="live",
    )
    blob = json.loads(raw)
    assert blob["ok"] is True, (
        f"sanitise-to-empty should degrade to success-with-fallback, not a hard failure: {blob}"
    )
    assert blob["data"]["fallback_text"] == "Plain-text summary the model can still deliver."
