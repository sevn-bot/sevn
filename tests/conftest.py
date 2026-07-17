"""Pytest configuration for the ``tests/`` tree — process env isolation."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _pin_sevn_repo_to_fixture(
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """Stop *any* test's gateway boot from mirroring the developer's real checkout.

    With no ``my_sevn.repo_path`` set, ``resolve_sevn_checkout_for_workspace`` falls
    through to a ``$HOME`` heuristic scan, finds the real sevn.bot tree, and the boot
    ``sync_source_copy`` mirrors all of it (incl. an 18MB ``reports/`` dir) into each
    test's tmp dir — which accumulated into a 51GB mirror across runs. Pin discovery
    at a 1-file fixture repo via ``SEVN_REPO_ROOT`` (consulted before the home scan).
    Tests that exercise discovery ``delenv`` this first; pinned ``repo_path`` wins anyway.
    """
    fixture_repo = tmp_path_factory.mktemp("sevn_repo_fixture")
    (fixture_repo / ".git").mkdir()
    (fixture_repo / "pyproject.toml").write_text('[project]\nname = "sevn"\n', encoding="utf-8")
    pkg = fixture_repo / "src" / "sevn"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    monkeypatch.setenv("SEVN_REPO_ROOT", str(fixture_repo))
    # Isolate SEVN_HOME so no test (nor the gateway-token H3 content-root fallback) reaches
    # the developer's real ``~/.sevn`` — that would decrypt the real store (passphrase prompt)
    # and make resolution non-deterministic. Tests that need a bound workspace set their own
    # SEVN_HOME (their in-body monkeypatch runs after this autouse fixture and overrides it).
    monkeypatch.setenv("SEVN_HOME", str(tmp_path_factory.mktemp("sevn_home")))
    return fixture_repo


@pytest.fixture(autouse=True)
def _default_gateway_bearer_for_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    """Supply a deterministic bearer so tests need not configure secrets-chain resolution.

    Set unconditionally so a developer with a real ``SEVN_GATEWAY_TOKEN`` exported does
    not leak that live credential into the suite. Tests that assert chain/literal/config
    resolution ``monkeypatch.delenv("SEVN_GATEWAY_TOKEN")`` first (env always wins inside
    ``resolve_gateway_token_ref``).
    """
    monkeypatch.setenv("SEVN_GATEWAY_TOKEN", "a" * 64)


@pytest.fixture(autouse=True)
def _default_secrets_master_key_for_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provide a deterministic encrypted-file master key for secrets-store writes.

    The repo-root ``conftest.py`` disables the macOS Keychain backend (no host prompts)
    and forces the encrypted-file-only chain. That backend needs a key for writes; the
    previous default write target — the keychain — required none. Supply a throwaway key
    so wizard/credential tests can persist secrets. Tests that exercise the missing-key
    error path ``monkeypatch.delenv("SEVN_SECRETS_MASTER_KEY")`` first (and already do).
    """
    monkeypatch.setenv("SEVN_SECRETS_MASTER_KEY", "00" * 32)


def _provider_secret_env_keys() -> tuple[str, ...]:
    """Return per-provider ``SEVN_SECRET_*`` keys primed by onboarding (not unlock vars)."""
    return tuple(
        key
        for key in os.environ
        if key.startswith("SEVN_SECRET_") and not key.startswith("SEVN_SECRETS_")
    )


@pytest.fixture(autouse=True)
def _isolate_wizard_and_proxy_env() -> Iterator[None]:
    """Clear wizard-primed secrets and proxy URL so tests do not leak process env.

    ``store_wizard_credentials`` may prime ``SEVN_TELEGRAM_BOT_TOKEN`` in
    ``os.environ``; ``get_secret_resilient`` prefers env over the secrets chain.
    ``run_fast_onboard`` may ``setdefault`` per-provider ``SEVN_SECRET_*`` aliases
    the same way. Gateway boot tests may leave ``SEVN_PROXY_URL`` in the process env,
    which makes ``probe_llm_reachability`` think a proxy is configured when it is not
    in preview.
    """
    from sevn.config.provider_secrets import LEGACY_PROVIDER_API_KEY
    from sevn.onboarding.wizard_credentials import WIZARD_SECRET_KEYS

    keys_at_start = (
        *WIZARD_SECRET_KEYS,
        "SEVN_PROXY_URL",
        LEGACY_PROVIDER_API_KEY,
        *_provider_secret_env_keys(),
    )
    saved = {k: os.environ[k] for k in keys_at_start if k in os.environ}
    for key in keys_at_start:
        os.environ.pop(key, None)
    yield
    keys_at_end = (
        *WIZARD_SECRET_KEYS,
        "SEVN_PROXY_URL",
        LEGACY_PROVIDER_API_KEY,
        *_provider_secret_env_keys(),
    )
    for key in keys_at_end:
        os.environ.pop(key, None)
    for key, value in saved.items():
        os.environ[key] = value


@pytest.fixture(autouse=True)
def _reset_trace_subscribers_after_test() -> Iterator[None]:
    """Clear mission-control trace fan-out hooks so gateway tests do not leak subscribers."""
    yield
    from sevn.agent.tracing.emit import reset_trace_subscribers_for_tests

    reset_trace_subscribers_for_tests()


@pytest.fixture(autouse=True)
def _reset_tool_approval_bridge_after_test() -> Iterator[None]:
    """Clear process-wide tool-approval bridge so dashboard installs do not leak across tests."""
    from sevn.agent.adapters.tool_approval_bridge import reset_tool_approval_bridge_for_tests

    reset_tool_approval_bridge_for_tests()
    yield
    reset_tool_approval_bridge_for_tests()


@pytest.fixture(autouse=True)
def _reset_tool_readiness_overrides() -> Iterator[None]:
    """Clear module-level readiness overrides so gated-tool tests stay isolated."""
    from sevn.tools import readiness

    readiness._OVERRIDES.clear()
    yield
    readiness._OVERRIDES.clear()
