"""Export/import tests for provider registry pairing (W1 contracts 11-12; green after W4)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from sevn.config.workspace_config import WorkspaceConfig, effective_encrypted_file_key_source
from sevn.onboarding.export_bundle import build_export_text, parse_export_text
from sevn.onboarding.fast_onboard import run_fast_onboard
from sevn.onboarding.live_validate import ValidationReport
from sevn.secrets.migrate import encrypted_file_backend_for_workspace


def _dual_provider_config_doc() -> dict[str, object]:
    return {
        "schema_version": 1,
        "gateway": {
            "host": "127.0.0.1",
            "port": 3001,
            "queue_mode": "cancel",
            "token": "${SECRET:keychain:sevn.gateway.token}",
        },
        "secrets_backend": {
            "chain": [{"type": "encrypted_file", "key_source": "passphrase"}],
        },
        "providers": {
            "tier_default": {
                "triager": "minimax/MiniMax-M2",
                "B": "openai/gpt-4o",
            },
            "minimax": {
                "api_key": "${SECRET:SEVN_SECRET_MINIMAX}",
                "base_url": "https://api.minimax.io/anthropic/v1",
            },
            "openai": {
                "api_key": "${SECRET:SEVN_SECRET_OPENAI}",
            },
        },
    }


def test_build_export_text_emits_providers_pairing_section() -> None:
    """Contract 11 (D6): export emits ``# --- providers (name → key alias) ---``."""
    secrets_map = {
        "SEVN_SECRET_MINIMAX": "sk-mm",
        "SEVN_SECRET_OPENAI": "sk-oai",
    }
    text = build_export_text(
        bot_name="DualBot",
        config_doc=_dual_provider_config_doc(),
        secrets=secrets_map,
        generated_at="2026-06-20T00:00:00Z",
    )
    assert "# --- providers (name → key alias) ---" in text
    assert "providers.minimax.api_key=${SECRET:SEVN_SECRET_MINIMAX}" in text
    assert "providers.openai.api_key=${SECRET:SEVN_SECRET_OPENAI}" in text
    secrets_pos = text.index("# --- secrets")
    providers_pos = text.index("# --- providers (name → key alias) ---")
    config_pos = text.index("# --- workspace config")
    assert secrets_pos < providers_pos < config_pos


def test_parse_export_text_roundtrips_provider_bindings() -> None:
    """Contract 11: ``parse_export_text`` preserves provider→alias pairing."""
    export_text = """\
SEVN_EXPORT_VERSION=1
SEVN_BOT_NAME=DualBot

# --- secrets (logical alias = plaintext) ---
SEVN_SECRET_MINIMAX=sk-mm
SEVN_SECRET_OPENAI=sk-oai

# --- providers (name → key alias) ---
# minimax → providers.minimax.api_key → SEVN_SECRET_MINIMAX
providers.minimax.api_key=${SECRET:SEVN_SECRET_MINIMAX}
# openai → providers.openai.api_key → SEVN_SECRET_OPENAI
providers.openai.api_key=${SECRET:SEVN_SECRET_OPENAI}

# --- workspace config (flattened sevn.json) ---
config.schema_version=1
config.gateway.token=${SECRET:keychain:sevn.gateway.token}
config.providers.tier_default.triager=minimax/MiniMax-M2
config.providers.tier_default.B=openai/gpt-4o
config.providers.minimax.api_key=${SECRET:SEVN_SECRET_MINIMAX}
config.providers.openai.api_key=${SECRET:SEVN_SECRET_OPENAI}
"""
    bundle = parse_export_text(export_text)
    provider_bindings = getattr(bundle, "provider_bindings", None)
    assert isinstance(provider_bindings, dict)
    assert provider_bindings["minimax"] == "${SECRET:SEVN_SECRET_MINIMAX}"
    assert provider_bindings["openai"] == "${SECRET:SEVN_SECRET_OPENAI}"


@pytest.mark.asyncio
async def test_onboard_fast_reseeds_provider_api_key_aliases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Contract 12: import re-seeds ``providers.<name>.api_key`` store aliases (W4)."""
    home = tmp_path / "home"
    (home / "workspace").mkdir(parents=True)
    monkeypatch.setenv("SEVN_HOME", str(home))

    config_doc = _dual_provider_config_doc()
    seed_secrets = {
        "SEVN_SECRETS_PASSPHRASE": "hunter2",
        "SEVN_SECRET_MINIMAX": "sk-mm",
        "SEVN_SECRET_OPENAI": "sk-oai",
        "providers.minimax.api_key": "${SECRET:SEVN_SECRET_MINIMAX}",
        "providers.openai.api_key": "${SECRET:SEVN_SECRET_OPENAI}",
    }
    ok_report = ValidationReport()

    with (
        patch(
            "sevn.onboarding.fast_onboard.run_live_validation",
            new_callable=AsyncMock,
            return_value=ok_report,
        ),
        patch(
            "sevn.onboarding.fast_onboard.credentials_status",
            new_callable=AsyncMock,
            return_value={
                "present": {
                    "SEVN_SECRET_MINIMAX": True,
                    "SEVN_SECRET_OPENAI": True,
                    "providers.minimax.api_key": True,
                    "providers.openai.api_key": True,
                },
                "ready_for_handoff": True,
                "needs_passphrase": False,
            },
        ),
        patch("sevn.cli.install_gate.maybe_install_daemon_after_promote", return_value=None),
    ):
        await run_fast_onboard(
            config_doc=config_doc,
            profile_id=None,
            bot_name="DualBot",
            prompt_for_bot_name=False,
            install_daemon=False,
            start_services=False,
            seed_secrets=seed_secrets,
        )

    promoted = json.loads((home / "workspace" / "sevn.json").read_text(encoding="utf-8"))
    cfg = WorkspaceConfig.model_validate(promoted)
    backend = encrypted_file_backend_for_workspace(
        content_root=(home / "workspace").resolve(),
        workspace_config=cfg,
    )
    key_source = effective_encrypted_file_key_source(cfg.secrets_backend)
    unlock_var = (
        "SEVN_SECRETS_PASSPHRASE" if key_source == "passphrase" else "SEVN_SECRETS_MASTER_KEY"
    )
    os.environ[unlock_var] = seed_secrets.get(unlock_var, "hunter2")
    try:
        minimax_alias = await backend.get("providers.minimax.api_key")
        openai_alias = await backend.get("providers.openai.api_key")
    finally:
        os.environ.pop(unlock_var, None)

    assert minimax_alias == "${SECRET:SEVN_SECRET_MINIMAX}"
    assert openai_alias == "${SECRET:SEVN_SECRET_OPENAI}"
