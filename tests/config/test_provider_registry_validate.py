"""Validation tests for provider registry coverage (W1 contracts 13-14; green after W5)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from typer.main import get_command

from sevn.cli.app import app
from sevn.onboarding.validate import validate_workspace_document


def _gateway_token_doc(**extra: object) -> dict[str, object]:
    base: dict[str, object] = {
        "schema_version": 1,
        "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
    }
    base.update(extra)
    return base


def test_validate_flags_assigned_model_without_provider_credential() -> None:
    """Contract 13 (D7): assigned slot with no resolvable provider credential is flagged."""
    doc = _gateway_token_doc(
        providers={
            "tier_default": {"triager": "minimax/MiniMax-M2"},
            "minimax": {"base_url": "https://api.minimax.io/anthropic/v1"},
        },
    )
    with pytest.raises(ValueError, match=r"(?i)(triager|minimax).*(credential|api_key|provider)"):
        validate_workspace_document(doc)


def test_validate_warns_on_declared_but_unused_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Contract 14 (D7): declared ``providers.<name>`` with no assigned model emits warning."""
    home = tmp_path / "home"
    workspace = home / "workspace"
    workspace.mkdir(parents=True)
    doc = _gateway_token_doc(
        providers={
            "tier_default": {"triager": "openai/gpt-4o"},
            "openai": {"api_key": "${SECRET:SEVN_SECRET_OPENAI}"},
            "unused_vendor": {"api_key": "${SECRET:SEVN_SECRET_UNUSED}"},
        },
    )
    (workspace / "sevn.json").write_text(json.dumps(doc), encoding="utf-8")
    monkeypatch.setenv("SEVN_HOME", str(home))

    runner = CliRunner()
    result = runner.invoke(get_command(app), ["config", "validate"])
    assert result.exit_code == 0
    output = (result.output + (result.stderr or "")).lower()
    assert "unused" in output
    assert "unused_vendor" in output
