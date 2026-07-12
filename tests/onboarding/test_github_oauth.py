"""GitHub OAuth, backup repo, and My Sevn.bot wizard routes (W4)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from sevn.onboarding.github_oauth import (
    build_authorize_url,
    callback_redirect_uri,
    clear_oauth_states,
    clear_wizard_oauth_credentials,
    mint_oauth_state,
    oauth_configured,
    set_wizard_oauth_credentials,
    validate_oauth_state,
)
from sevn.onboarding.web_app import create_onboarding_app
from sevn.onboarding.workspace_backup import (
    default_backup_repo_name,
    repo_url_from_api_response,
    sanitize_repo_name,
)


@pytest.fixture(autouse=True)
def _clear_oauth_state() -> None:
    clear_oauth_states()
    clear_wizard_oauth_credentials()


def test_wizard_oauth_credentials_enable_start_without_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OAuth credentials posted to the wizard API enable OAuth start without env vars."""
    monkeypatch.delenv("SEVN_GITHUB_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("SEVN_GITHUB_OAUTH_CLIENT_SECRET", raising=False)
    client = TestClient(create_onboarding_app("tok", onboard_port=9999))
    assert (
        client.get("/api/github/oauth/start", headers={"X-Onboard-Token": "tok"}).status_code == 503
    )
    saved = client.post(
        "/api/github/oauth/credentials",
        headers={"X-Onboard-Token": "tok"},
        json={"client_id": "cid", "client_secret": "sec"},
    )
    assert saved.status_code == 200
    assert saved.json()["oauth_configured"] is True
    res = client.get("/api/github/oauth/start", headers={"X-Onboard-Token": "tok"})
    assert res.status_code == 200
    assert "github.com/login/oauth/authorize" in res.json()["authorize_url"]


def test_set_wizard_oauth_credentials_memory_only() -> None:
    set_wizard_oauth_credentials("cid", "sec")
    assert oauth_configured() is True
    clear_wizard_oauth_credentials()
    assert oauth_configured() is False


def test_github_status_ignores_host_keychain_without_workspace_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Clean workspace must not show connected when only the host Keychain has a token."""
    sj = tmp_path / "sevn.json"
    client = TestClient(create_onboarding_app("tok", sevn_json_path=sj))
    with (
        patch(
            "sevn.onboarding.web_app.get_wizard_credential",
            new_callable=AsyncMock,
            return_value=None,
        ) as workspace_get,
        patch(
            "sevn.onboarding.web_app.probe_host_github_token",
            new_callable=AsyncMock,
            return_value=("ghp_host_only", "keychain"),
        ),
        patch(
            "sevn.onboarding.web_app.fetch_github_user",
            new_callable=AsyncMock,
            return_value={"login": "alexhawat"},
        ),
    ):
        status = client.get("/api/github/status", headers={"X-Onboard-Token": "tok"})
        host = client.get("/api/github/host-status", headers={"X-Onboard-Token": "tok"})
    assert status.status_code == 200
    assert status.json()["connected"] is False
    workspace_get.assert_awaited()
    assert workspace_get.await_args.kwargs.get("workspace_only") is True
    assert host.status_code == 200
    assert host.json()["available"] is True
    assert host.json()["login"] == "alexhawat"


def test_github_use_host_copies_token_into_workspace(tmp_path: Path) -> None:
    """Explicit host import stores GitHub token in the workspace chain."""
    sj = tmp_path / "sevn.json"
    client = TestClient(create_onboarding_app("tok", sevn_json_path=sj))
    with (
        patch(
            "sevn.onboarding.web_app.get_wizard_credential",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "sevn.onboarding.web_app.probe_host_github_token",
            new_callable=AsyncMock,
            return_value=("ghp_host", "gh_cli"),
        ),
        patch(
            "sevn.onboarding.web_app.fetch_github_user",
            new_callable=AsyncMock,
            return_value={"login": "octocat"},
        ),
        patch(
            "sevn.onboarding.web_app.store_wizard_credentials",
            new_callable=AsyncMock,
            return_value={"integration.github.token": True},
        ) as store_mock,
    ):
        res = client.post("/api/github/use-host", headers={"X-Onboard-Token": "tok"})
    assert res.status_code == 200
    assert res.json()["login"] == "octocat"
    store_mock.assert_awaited_once()
    assert store_mock.await_args.kwargs["github_token"] == "ghp_host"


def test_oauth_state_csrf_single_use() -> None:
    """State is valid once then rejected (CSRF)."""
    state = mint_oauth_state()
    assert validate_oauth_state(state) is True
    assert validate_oauth_state(state) is False
    assert validate_oauth_state("not-issued") is False


def test_build_authorize_url_includes_scopes() -> None:
    """Authorize URL carries repo + read:user scopes."""
    url = build_authorize_url(
        state="s",
        client_id="cid",
        redirect_uri=callback_redirect_uri(port=8844),
    )
    assert "scope=repo+read%3Auser" in url or "scope=repo%20read%3Auser" in url
    assert "state=s" in url


def test_sanitize_repo_name_strips_invalid_chars() -> None:
    """Backup repo names are GitHub-safe slugs."""
    assert sanitize_repo_name("Octo.Cat Backup!!") == "octo.cat-backup"
    with pytest.raises(ValueError, match="empty"):
        sanitize_repo_name("!!!")


def test_default_backup_repo_name_uses_login() -> None:
    """Default backup slug is ``{login}.mysevnbackup``."""
    assert default_backup_repo_name("octocat") == "octocat.mysevnbackup"


def test_repo_url_from_api_response_prefers_html_url() -> None:
    """Create-repo helper returns canonical html_url."""
    url = repo_url_from_api_response({"html_url": "https://github.com/octocat/demo.mysevnbackup"})
    assert url == "https://github.com/octocat/demo.mysevnbackup"


def test_github_oauth_start_requires_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """OAuth start returns 503 when client env vars are unset."""
    monkeypatch.delenv("SEVN_GITHUB_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("SEVN_GITHUB_OAUTH_CLIENT_SECRET", raising=False)
    client = TestClient(create_onboarding_app("tok", onboard_port=9999))
    res = client.get("/api/github/oauth/start", headers={"X-Onboard-Token": "tok"})
    assert res.status_code == 503


def test_github_oauth_start_returns_authorize_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """OAuth start returns authorize URL when configured."""
    monkeypatch.setenv("SEVN_GITHUB_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("SEVN_GITHUB_OAUTH_CLIENT_SECRET", "sec")
    client = TestClient(create_onboarding_app("tok", onboard_port=9999))
    res = client.get("/api/github/oauth/start", headers={"X-Onboard-Token": "tok"})
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert "github.com/login/oauth/authorize" in body["authorize_url"]


def test_github_oauth_callback_rejects_bad_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Callback rejects missing/invalid CSRF state."""
    monkeypatch.setenv("SEVN_GITHUB_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("SEVN_GITHUB_OAUTH_CLIENT_SECRET", "sec")
    client = TestClient(create_onboarding_app("tok", onboard_port=9999))
    res = client.get(
        "/api/github/oauth/callback",
        params={"code": "abc", "state": "bad"},
        follow_redirects=False,
    )
    assert res.status_code == 302
    assert "github_error=invalid_state" in res.headers["location"]


def test_github_token_stored_not_in_draft_json(tmp_path: Path) -> None:
    """PAT is stored in secrets chain, not draft JSON."""
    sj = tmp_path / "sevn.json"
    with (
        patch(
            "sevn.onboarding.web_app.fetch_github_user",
            new_callable=AsyncMock,
            return_value={"login": "octocat"},
        ),
        patch(
            "sevn.onboarding.web_app.store_wizard_credentials",
            new_callable=AsyncMock,
            return_value={"integration.github.token": True},
        ) as store_mock,
    ):
        client = TestClient(create_onboarding_app("tok", sevn_json_path=sj))
        res = client.post(
            "/api/github/token",
            headers={"X-Onboard-Token": "tok"},
            json={"token": "ghp_test_token_value"},
        )
    assert res.status_code == 200
    assert res.json()["ok"] is True
    store_mock.assert_awaited_once()
    assert store_mock.await_args.kwargs["github_token"] == "ghp_test_token_value"
    draft = tmp_path / ".sevn.json.draft"
    if draft.is_file():
        raw = json.loads(draft.read_text(encoding="utf-8"))
        assert "ghp_test" not in json.dumps(raw)


def test_workspace_backup_create_sanitizes_name(tmp_path: Path) -> None:
    """Create backup endpoint sanitizes repo names."""
    sj = tmp_path / "sevn.json"
    client = TestClient(create_onboarding_app("tok", sevn_json_path=sj))
    with (
        patch(
            "sevn.onboarding.web_app.get_wizard_credential",
            new_callable=AsyncMock,
            return_value="ghp_test",
        ),
        patch(
            "sevn.onboarding.web_app.create_workspace_backup_repo",
            new_callable=AsyncMock,
            return_value="https://github.com/octocat/octo.mysevnbackup",
        ) as create_mock,
    ):
        res = client.post(
            "/api/workspace-backup/create",
            headers={"X-Onboard-Token": "tok"},
            json={"name": "Octo!!! Backup"},
        )
    assert res.status_code == 200
    create_mock.assert_awaited_once()
    assert create_mock.await_args.args[1] == sanitize_repo_name("Octo!!! Backup")
    assert res.json()["repo_url"].startswith("https://github.com/")


def test_probe_github_hub_skipped_when_local_only(tmp_path: Path) -> None:
    """Live validation skips GitHub probe when hub.use_github is false."""
    from sevn.onboarding.live_validate import github_hub_enabled, run_live_validation

    assert (
        github_hub_enabled({"self_improve": {"enabled": True, "hub": {"use_github": False}}})
        is False
    )

    async def _run() -> bool:
        report = await run_live_validation(
            workspace_root=tmp_path,
            merged_preview={
                "schema_version": 1,
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
                "self_improve": {"enabled": True, "hub": {"use_github": False}},
            },
            profile_id=None,
        )
        row = next(c for c in report.checks if c.check_id == "github_hub_user")
        return "skipped" in row.detail

    import asyncio

    assert asyncio.run(_run()) is True
