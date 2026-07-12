from __future__ import annotations

import pytest
from pydantic import ValidationError

from sevn.config.workspace_config import parse_workspace_config
from sevn.security.sandbox_errors import SandboxConfigurationError
from sevn.security.sandbox_runtime import (
    SandboxDriver,
    docker_daemon_reachable,
    resolve_sandbox_driver,
)


def test_production_profile_rejects_subprocess_fallback_parse() -> None:
    raw = {
        "schema_version": 1,
        "deployment": {"profile": "production"},
        "security": {"sandbox": {"allow_subprocess_fallback": True}},
        "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
    }
    with pytest.raises(ValidationError, match="allow_subprocess_fallback"):
        parse_workspace_config(raw)


def test_non_production_does_not_raise_on_subprocess_fallback() -> None:
    raw = {
        "schema_version": 1,
        "security": {"sandbox": {"allow_subprocess_fallback": True}},
        "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
    }
    cfg = parse_workspace_config(raw)
    assert cfg.security is not None
    assert cfg.security.sandbox is not None
    assert cfg.security.sandbox.allow_subprocess_fallback is True


@pytest.mark.parametrize(
    ("reachable", "allow_fb", "enabled", "deployment_profile", "expected"),
    [
        (
            False,
            True,
            False,
            None,
            SandboxDriver.subprocess,
        ),
        (
            True,
            False,
            True,
            None,
            SandboxDriver.docker,
        ),
        (
            True,
            True,
            False,
            None,
            SandboxDriver.subprocess,
        ),
        (
            True,
            True,
            True,
            None,
            SandboxDriver.docker,
        ),
    ],
)
def test_resolve_sandbox_driver_dev_matrix(
    monkeypatch: pytest.MonkeyPatch,
    reachable: bool,
    allow_fb: bool,
    enabled: bool,
    deployment_profile: str | None,
    expected: SandboxDriver,
) -> None:
    monkeypatch.setattr(
        "sevn.security.sandbox_runtime.docker_daemon_reachable",
        lambda timeout_s=5.0: reachable,
        raising=False,
    )
    extras: dict = {"security": {"sandbox": {"allow_subprocess_fallback": allow_fb}}}
    if deployment_profile is not None:
        extras["deployment"] = {"profile": deployment_profile}
    extras["sandbox"] = {"enabled": enabled}
    cfg = parse_workspace_config(
        {
            "schema_version": 1,
            **extras,
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        }
    )
    assert resolve_sandbox_driver(cfg) is expected


def test_resolve_raises_when_no_paths_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sevn.security.sandbox_runtime.docker_daemon_reachable",
        lambda timeout_s=5.0: False,
        raising=False,
    )
    cfg = parse_workspace_config(
        {"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}
    )
    with pytest.raises(SandboxConfigurationError, match="allow_subprocess_fallback"):
        resolve_sandbox_driver(cfg)


def test_resolve_raises_when_docker_but_no_explicit_choice(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sevn.security.sandbox_runtime.docker_daemon_reachable",
        lambda timeout_s=5.0: True,
        raising=False,
    )
    cfg = parse_workspace_config(
        {"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}
    )
    with pytest.raises(SandboxConfigurationError, match="sandbox\\.enabled"):
        resolve_sandbox_driver(cfg)


def test_resolve_production_requires_reachable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sevn.security.sandbox_runtime.docker_daemon_reachable",
        lambda timeout_s=5.0: False,
        raising=False,
    )
    cfg = parse_workspace_config(
        {
            "schema_version": 1,
            "deployment": {"profile": "production"},
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        }
    )
    with pytest.raises(SandboxConfigurationError, match="production"):
        resolve_sandbox_driver(cfg)


def test_resolve_production_uses_docker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sevn.security.sandbox_runtime.docker_daemon_reachable",
        lambda timeout_s=5.0: True,
        raising=False,
    )
    cfg = parse_workspace_config(
        {
            "schema_version": 1,
            "deployment": {"profile": "production"},
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        }
    )
    assert resolve_sandbox_driver(cfg) is SandboxDriver.docker


def test_docker_daemon_probe_smoke(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DOCKER_HOST", raising=False)

    reachable = docker_daemon_reachable(timeout_s=0.1)
    assert isinstance(reachable, bool)
