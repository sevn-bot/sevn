"""Validate/doctor probes for OpenAI OAuth credentials (W1.8)."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from sevn.cli.app import app
from sevn.onboarding.validate import validate_workspace_document


def _oauth_openai_doc(**extra: object) -> dict[str, object]:
    base: dict[str, object] = {
        "schema_version": 1,
        "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        "providers": {
            "tier_default": {"triager": "openai/gpt-4o"},
            "openai": {"auth_mode": "oauth"},
        },
    }
    base.update(extra)
    return base


def test_validate_warns_when_oauth_mode_missing_credential() -> None:
    """OAuth-mode OpenAI slot with no ``oauth.openai`` blob emits a non-fatal warning."""
    from sevn.onboarding.live_validate import probe_openai_oauth_credential

    doc = _oauth_openai_doc()
    check = probe_openai_oauth_credential(doc, secrets_chain=None)
    assert check.ok is False
    assert "oauth.openai" in check.detail.lower() or "oauth" in check.detail.lower()


def test_validate_warns_when_oauth_credential_expired() -> None:
    """Expired ``oauth.openai`` for an assigned slot is flagged (non-fatal)."""
    from sevn.onboarding.live_validate import probe_openai_oauth_credential
    from sevn.security.oauth.credential import CodexOAuthCredential

    doc = _oauth_openai_doc()
    expired = CodexOAuthCredential(
        access="jwt-expired",
        refresh="rt",
        expires=1,
        account_id="acct-old",
    )
    check = probe_openai_oauth_credential(doc, credential=expired)
    assert check.ok is False
    assert "expir" in check.detail.lower()


def test_config_validate_cli_reports_oauth_credential_gap(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """``sevn config validate`` prints oauth credential guidance without failing hard."""
    home = tmp_path / "home"
    workspace = home / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "sevn.json").write_text(json.dumps(_oauth_openai_doc()), encoding="utf-8")
    monkeypatch.setenv("SEVN_HOME", str(home))

    runner = CliRunner()
    result = runner.invoke(app, ["config", "validate"], env={"NO_COLOR": "1"})
    assert result.exit_code == 0
    output = (result.output + (result.stderr or "")).lower()
    assert "oauth" in output
    assert "openai" in output


def test_api_key_mode_validate_unchanged() -> None:
    """Default ``api_key`` mode does not require ``oauth.openai`` (D4)."""
    doc = _oauth_openai_doc(
        providers={
            "tier_default": {"triager": "openai/gpt-4o"},
            "openai": {"api_key": "${SECRET:SEVN_SECRET_OPENAI}"},
        },
    )
    validate_workspace_document(doc)


class _DecryptFailedChain:
    async def get(self, key: str) -> str | None:
        from sevn.security.secrets.errors import SecretsStoreCorruptError

        raise SecretsStoreCorruptError("AEAD decrypt failed (corrupt or wrong key)")


def test_probe_openai_oauth_reports_store_decrypt_failure() -> None:
    """Wrong-key encrypted store surfaces as error instead of crashing doctor/validate."""
    from sevn.onboarding.live_validate import probe_openai_oauth_credential

    check = probe_openai_oauth_credential(_oauth_openai_doc(), secrets_chain=_DecryptFailedChain())
    assert check.ok is False
    assert check.severity == "error"
    assert "fails to decrypt" in check.detail
    assert check.hint is not None
    assert "SEVN_SECRETS_PASSPHRASE" in check.hint
