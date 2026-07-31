"""W23 — webhook subprocess env minimization (#81)."""

from __future__ import annotations

from sevn.security.trigger_spawn_env import (
    bind_webhook_minimal_host_env,
    host_env_base_for_subprocess,
    is_webhook_trigger_scope,
    minimal_webhook_host_env,
)


def test_minimal_webhook_host_env_blocks_vault_session_keys() -> None:
    env = minimal_webhook_host_env(
        base={
            "PATH": "/usr/bin",
            "BW_SESSION": "unlock-token",
            "OPENAI_API_KEY": "sk-test",
            "AWS_SECRET_ACCESS_KEY": "aws-secret",
        },
    )
    assert env == {"PATH": "/usr/bin"}
    assert "BW_SESSION" not in env
    assert "OPENAI_API_KEY" not in env


def test_host_env_base_for_subprocess_uses_scope_key_for_triggers() -> None:
    full = host_env_base_for_subprocess(
        base={"PATH": "/bin", "GITHUB_TOKEN": "gh"},
        scope_key="trigger:webhook:abc",
    )
    assert full == {"PATH": "/bin"}
    assert is_webhook_trigger_scope("trigger:webhook:abc")


def test_bind_webhook_minimal_host_env_applies_during_context() -> None:
    with bind_webhook_minimal_host_env():
        env = host_env_base_for_subprocess(base={"PATH": "/x", "ANTHROPIC_API_KEY": "k"})
    assert env == {"PATH": "/x"}
    outside = host_env_base_for_subprocess(base={"PATH": "/x", "ANTHROPIC_API_KEY": "k"})
    assert "ANTHROPIC_API_KEY" in outside
