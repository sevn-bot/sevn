"""Memory section config tests."""

from __future__ import annotations

from sevn.config.workspace_config import parse_workspace_config


def test_memory_user_model_defaults() -> None:
    cfg = parse_workspace_config(
        {
            "schema_version": 1,
            "memory": {
                "user_model": {
                    "enabled": True,
                    "max_facts": 32,
                    "deny_topics": ["foo"],
                },
            },
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        },
    )
    assert cfg.memory is not None
    assert cfg.memory.user_model is not None
    assert cfg.memory.user_model.enabled is True
    assert cfg.memory.user_model.max_facts == 32
    assert cfg.memory.user_model.deny_topics == ["foo"]
