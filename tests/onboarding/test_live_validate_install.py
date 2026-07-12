"""Live validation install-status probes (onboarding comprehensive setup W9)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from sevn.onboarding.live_validate import (
    InstallStatusRow,
    install_status_to_dict,
    probe_capability_install_status,
    run_live_validation,
)


@pytest.mark.asyncio
async def test_probe_openwiki_validate_receives_content_root(tmp_path: Path) -> None:
    """OpenWiki dry-run validation resolves secrets against the wizard workspace."""
    merged = {"skills": {"openwiki": {"enabled": True}}}
    content_root = tmp_path / "workspace"
    content_root.mkdir()
    with patch(
        "sevn.onboarding.install_actions.special.run_openwiki_validate",
        return_value=(0, "openwiki CLI and credentials ready"),
    ) as validate:
        rows = await probe_capability_install_status(
            merged,
            install_root=Path("."),
            content_root=content_root,
        )
    validate.assert_called_once()
    assert validate.call_args.kwargs["content_root"] == content_root
    noop_rows = [r for r in rows if r.action_id == "skill.openwiki.noop"]
    assert noop_rows
    assert noop_rows[0].satisfied is True


@pytest.mark.asyncio
async def test_probe_capability_install_status_browser_playwright() -> None:
    """Browser capability reports playwright idempotent check row."""
    merged = {"skills": {"browser": {"enabled": True}}}
    with patch(
        "sevn.onboarding.install_actions.executors.idempotent_check_satisfied",
        new=AsyncMock(return_value=False),
    ):
        rows = await probe_capability_install_status(merged, install_root=Path("."))
    cmd_rows = [r for r in rows if r.action_id == "extra.browser.cmd"]
    assert cmd_rows
    row = cmd_rows[0]
    assert row.capability_id == "extra.browser"
    assert row.fatal is True
    assert row.satisfied is False
    assert row.severity == "warn"


@pytest.mark.asyncio
async def test_probe_capability_install_status_optional_cli_warn_only() -> None:
    """Optional CLI noop rows stay warn-only when binary is missing."""
    merged = {"self_improve": {"enabled": True, "hub": {"use_github": True}}}
    with patch(
        "sevn.onboarding.live_validate._run_probe_command",
        new=AsyncMock(return_value=(False, "gh not found on PATH")),
    ):
        rows = await probe_capability_install_status(merged, install_root=Path("."))
    gh_rows = [r for r in rows if r.capability_id == "cli.gh"]
    assert gh_rows
    assert gh_rows[0].ok is True
    assert gh_rows[0].severity == "warn"


def test_install_status_to_dict_shape() -> None:
    """Install status rows serialize for validate-all JSON."""
    row = InstallStatusRow(
        capability_id="extra.browser",
        action_id="extra.browser.cmd",
        ok=False,
        severity="warn",
        detail="pending",
        satisfied=False,
        fatal=True,
        hint="Run installs",
    )
    payload = install_status_to_dict(row)
    assert payload["capability_id"] == "extra.browser"
    assert payload["fatal"] is True
    assert payload["satisfied"] is False


@pytest.mark.asyncio
async def test_run_live_validation_includes_capability_checks() -> None:
    """Capability install rows are appended to live validation checks."""
    import tempfile

    td = Path(tempfile.mkdtemp())
    merged = {
        "schema_version": 1,
        "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
    }
    with patch(
        "sevn.onboarding.live_validate.probe_capability_install_status",
        new=AsyncMock(
            return_value=[
                InstallStatusRow(
                    "extra.graphify",
                    "extra.graphify.uv",
                    False,
                    "warn",
                    "pending",
                    False,
                    True,
                )
            ]
        ),
    ):
        report = await run_live_validation(
            workspace_root=td,
            merged_preview=merged,
            profile_id=None,
        )
    cap_checks = [c for c in report.checks if c.check_id == "capability.extra.graphify"]
    assert cap_checks
    assert report.install_status


def test_validate_all_includes_install_status(tmp_path: Path) -> None:
    """``POST /api/validate-all`` returns ``install_status[]``."""
    from tests.onboarding.test_onboarding import (
        _store_test_credentials,
        _valid_wizard_payload,
        _wizard_client,
    )

    client = _wizard_client(tmp_path)
    _store_test_credentials(client)
    res = client.post(
        "/api/validate-all",
        params={"onboard_token": "tok"},
        json=_valid_wizard_payload(),
    )
    assert res.status_code == 200
    body = res.json()
    assert isinstance(body.get("install_status"), list)


@pytest.mark.asyncio
async def test_run_live_validation_proxy_unreachable_warns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unreachable proxy /healthz is a warn check, not an uncaught httpx error."""

    async def _creds(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {"present": {}, "ready_for_handoff": True}

    monkeypatch.setattr("sevn.onboarding.live_validate.credentials_status", _creds)

    class _BrokenClient:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            return None

        async def __aenter__(self) -> _BrokenClient:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def get(self, _url: str) -> httpx.Response:
            msg = "connection refused"
            raise httpx.ConnectError(msg)

    monkeypatch.setattr("httpx.AsyncClient", _BrokenClient)
    report = await run_live_validation(
        workspace_root=tmp_path,
        merged_preview={
            "schema_version": 1,
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            "proxy": {"url": "http://127.0.0.1:59999"},
        },
        profile_id=None,
    )
    proxy = next(c for c in report.checks if c.check_id == "egress_proxy")
    assert proxy.ok is False
    assert proxy.severity == "warn"
    assert report.has_error() is False


def test_validate_step_install_ui_present() -> None:
    """Packaged HTML exposes install plan panel on Validate step."""
    from importlib.resources import files

    html = files("sevn.onboarding.web_wizard").joinpath("index.html").read_text(encoding="utf-8")
    assert 'id="install-plan-panel"' in html
    assert 'id="btn-run-installs"' in html
    assert 'id="install-progress-log"' in html
