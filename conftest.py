"""Pytest configuration (repo root) — doctest collection hooks + daemon-install safety.

A previous test (`tests/onboarding/test_fresh_machine.py::
test_onboard_config_fresh_machine_writes_valid_sevn_json`) ran the real
`sevn onboard --config` flow without mocking the launchd/systemd install path,
which wrote real plists to the host operator's ``~/Library/LaunchAgents``
pointing at a now-deleted ``pytest`` tmp dir. The ``SEVN_DISABLE_DAEMON_INSTALL``
env (honoured by ``sevn.cli.service_manager.install_paired_units`` and
``control_unit``) hard-stops every accidental host install during test runs.
Individual tests that need to exercise the install path may opt out by
``monkeypatch.delenv("SEVN_DISABLE_DAEMON_INSTALL")`` AND patching
``Path.home`` to a temp directory.

The gateway-token change resolves ``${SECRET:keychain:…}`` refs through the
secrets chain; on macOS the default chain includes the real ``MacOSKeychain``
backend, which pops a host Keychain-access prompt during ``make test`` /
``make doctest``. Forcing ``CI=1`` selects the encrypted-file-only chain
(``secrets.factory._ci_encrypted_file_only``) and ``SEVN_DISABLE_KEYCHAIN=1``
makes the keychain backend a no-op, so no local test/doctest ever touches the
operator's real Keychain (this matches how CI already runs on Linux). A
deterministic ``SEVN_SECRETS_MASTER_KEY`` lets the encrypted-file backend that
now serves the whole chain perform writes without a per-test passphrase (the
previous default write target — the keychain — is gone).
"""

from __future__ import annotations

import os

os.environ.setdefault("SEVN_DISABLE_DAEMON_INSTALL", "1")
os.environ.setdefault("CI", "1")
os.environ.setdefault("SEVN_DISABLE_KEYCHAIN", "1")
# A live ``SEVN_PROXY_URL`` in the developer shell leaks into ``--doctest-modules`` runs
# (which do not get the ``tests/`` isolation fixtures) and makes proxy-probe doctests in
# ``onboarding/live_validate.py`` attempt a real connection. Clear it for collection.
os.environ.pop("SEVN_PROXY_URL", None)

collect_ignore = [
    "src/sevn/agent/adapters/tier_b_model.py",
    "src/sevn/agent/adapters/tier_b_tools.py",
]
