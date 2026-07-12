"""Secrets backend section config tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from sevn.config.workspace_config import effective_encrypted_file_key_source, parse_workspace_config


def test_secrets_backend_rejects_commercial_vault_key() -> None:
    """``hashicorp_vault`` subtree keys are rejected at parse (``specs/06-secrets.md`` §10.3)."""
    with pytest.raises(ValidationError, match="unsupported secrets_backend key"):
        parse_workspace_config(
            {
                "schema_version": 1,
                "secrets_backend": {"hashicorp_vault": {}},
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            }
        )


def test_secrets_chain_rejects_vault_type() -> None:
    """Commercial vault types are rejected in ``chain`` entries."""
    raw = {
        "schema_version": 1,
        "secrets_backend": {"chain": [{"type": "hashicorp_vault"}]},
        "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
    }
    with pytest.raises(ValidationError, match="unsupported secrets backend type"):
        parse_workspace_config(raw)


def test_encrypted_file_key_source_parses_and_resolves() -> None:
    """``key_source`` parses on entry + defaults and resolves with the right precedence."""
    cfg = parse_workspace_config(
        {
            "schema_version": 1,
            "secrets_backend": {
                "chain": [{"type": "encrypted_file", "key_source": "master_key"}],
            },
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        }
    )
    assert effective_encrypted_file_key_source(cfg.secrets_backend) == "master_key"

    cfg_default = parse_workspace_config(
        {
            "schema_version": 1,
            "secrets_backend": {"chain": [{"type": "encrypted_file"}]},
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        }
    )
    assert effective_encrypted_file_key_source(cfg_default.secrets_backend) == "passphrase"
    assert effective_encrypted_file_key_source(None) == "passphrase"


def test_encrypted_file_key_source_rejects_os_keychain() -> None:
    """The reserved ``os_keychain`` value is rejected with an actionable message."""
    with pytest.raises(ValidationError, match="os_keychain' is reserved"):
        parse_workspace_config(
            {
                "schema_version": 1,
                "secrets_backend": {
                    "chain": [{"type": "encrypted_file", "key_source": "os_keychain"}]
                },
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            }
        )
