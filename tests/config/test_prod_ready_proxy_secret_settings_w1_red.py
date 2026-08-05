"""Prod-ready Batch A W1.1 RED — proxy secret in ProcessSettings (C3.1; D41 adjacent).

Contracts (``about-sevn.bot/specs/02-config-and-workspace.md`` §2.5):
``SEVN_PROXY_SHARED_SECRET`` is a member of ``PROCESS_SETTINGS_ENV_VAR_NAMES`` and
parses into ``ProcessSettings``. Green after W2.
"""

from __future__ import annotations

import pytest

from sevn.config.settings import PROCESS_SETTINGS_ENV_VAR_NAMES, ProcessSettings

_XFAIL_W2 = pytest.mark.xfail(strict=True, reason="prod-ready W2")


@_XFAIL_W2
def test_proxy_shared_secret_in_process_settings_allowlist() -> None:
    """W1.1 / C3.1: audited allowlist must name the proxy shared secret."""
    assert "SEVN_PROXY_SHARED_SECRET" in PROCESS_SETTINGS_ENV_VAR_NAMES


@_XFAIL_W2
def test_process_settings_parses_proxy_shared_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W1.1: ProcessSettings exposes the env value as a first-class field."""
    monkeypatch.setenv("SEVN_PROXY_SHARED_SECRET", "  settings-secret-value  ")
    settings = ProcessSettings()
    value = getattr(settings, "proxy_shared_secret", None)
    assert value is not None
    assert str(value).strip() == "settings-secret-value"


@_XFAIL_W2
def test_process_settings_proxy_shared_secret_unset_is_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W1.1 edge: unset env maps to None (not empty string)."""
    monkeypatch.delenv("SEVN_PROXY_SHARED_SECRET", raising=False)
    settings = ProcessSettings()
    assert getattr(settings, "proxy_shared_secret", "missing") is None
