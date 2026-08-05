"""Prod-ready Batch A W1.1 — proxy secret in ProcessSettings (C3.1; D41 adjacent).

Contracts (``about-sevn.bot/specs/02-config-and-workspace.md`` §2.5):
``SEVN_PROXY_SHARED_SECRET`` is a member of ``PROCESS_SETTINGS_ENV_VAR_NAMES`` and
parses into ``ProcessSettings``. Green after W2.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sevn.config.settings import PROCESS_SETTINGS_ENV_VAR_NAMES, ProcessSettings

if TYPE_CHECKING:
    import pytest


def test_proxy_shared_secret_in_process_settings_allowlist() -> None:
    """W1.1 / C3.1: audited allowlist must name the proxy shared secret."""
    assert "SEVN_PROXY_SHARED_SECRET" in PROCESS_SETTINGS_ENV_VAR_NAMES


def test_process_settings_parses_proxy_shared_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W1.1: ProcessSettings exposes the env value as a first-class field."""
    monkeypatch.setenv("SEVN_PROXY_SHARED_SECRET", "  settings-secret-value  ")
    settings = ProcessSettings()
    value = getattr(settings, "proxy_shared_secret", None)
    assert value is not None
    assert str(value).strip() == "settings-secret-value"


def test_process_settings_proxy_shared_secret_unset_is_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W1.1 edge: unset env maps to None (not empty string)."""
    monkeypatch.delenv("SEVN_PROXY_SHARED_SECRET", raising=False)
    settings = ProcessSettings()
    assert getattr(settings, "proxy_shared_secret", "missing") is None
