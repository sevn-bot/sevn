"""Wizard gateway token promotion and secrets storage."""

from __future__ import annotations

import asyncio
from pathlib import Path

from sevn.config.workspace_config import (
    EncryptedFileBackendEntry,
    SecretsBackendSectionConfig,
    parse_workspace_config,
)
from sevn.gateway.runtime.gateway_token import GATEWAY_TOKEN_CONFIG_REF, GATEWAY_TOKEN_LOGICAL_KEY
from sevn.onboarding.validate import validate_workspace_document
from sevn.onboarding.web_app import _merge_wizard_payload, _wizard_gateway_token_plaintext
from sevn.onboarding.wizard_credentials import credentials_status, store_wizard_credentials


def test_merge_wizard_payload_stamps_gateway_token_ref() -> None:
    doc = _merge_wizard_payload({"fields": {"gateway.port": 3002}}, profile_id=None)
    assert doc["gateway"]["token"] == GATEWAY_TOKEN_CONFIG_REF


def test_wizard_gateway_token_auto_generate_min_length() -> None:
    tok = _wizard_gateway_token_plaintext({})
    assert len(tok) >= 32


def test_store_wizard_credentials_writes_logical_key(tmp_path: Path) -> None:
    section = SecretsBackendSectionConfig(
        chain=[EncryptedFileBackendEntry(path=".sevn/secrets/store.enc")]
    )
    plain = "b" * 64
    asyncio.run(
        store_wizard_credentials(
            tmp_path,
            gateway_token=plain,
            bot_token="123:abc",
            provider_api_keys={"openai": "sk-test"},
            secrets_passphrase="doctest-passphrase",
            section=section,
        )
    )
    status = asyncio.run(credentials_status(tmp_path, section=section))
    assert status["present"][GATEWAY_TOKEN_LOGICAL_KEY] is True
    assert status["ready_for_handoff"] is True


def test_validate_workspace_document_requires_gateway_token() -> None:
    import pytest

    with pytest.raises(ValueError, match=r"gateway\.token"):
        validate_workspace_document({"schema_version": 1})


def test_merged_preview_validates_with_gateway_ref() -> None:
    merged = _merge_wizard_payload({}, profile_id=None)
    validate_workspace_document(merged)
    cfg = parse_workspace_config(merged)
    assert cfg.gateway is not None
    assert cfg.gateway.token == GATEWAY_TOKEN_CONFIG_REF
