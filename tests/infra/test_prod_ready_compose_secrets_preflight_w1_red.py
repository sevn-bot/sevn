"""Prod-ready Batch A W1.6 RED — compose operator-secret preflight (C1.3; D38).

Preflight rejects empty, below-entropy, and placeholder (``change-me``) values for
``SEVN_PROXY_SHARED_SECRET``, ``SEVN_GATEWAY_TOKEN``, and ``SEVN_SECRETS_PASSPHRASE``,
and runs before services start (``make compose-up`` + a ``ci-*`` tier). Green after W5.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MAKEFILE = _REPO_ROOT / "Makefile"
_HELPER_CANDIDATES = (
    _REPO_ROOT / "scripts" / "check_compose_operator_secrets.py",
    _REPO_ROOT / "scripts" / "check-compose-operator-secrets.sh",
    _REPO_ROOT / "scripts" / "check_compose_secrets.py",
)

_VARS = (
    "SEVN_PROXY_SHARED_SECRET",
    "SEVN_GATEWAY_TOKEN",
    "SEVN_SECRETS_PASSPHRASE",
)

_XFAIL_W5 = pytest.mark.xfail(strict=True, reason="prod-ready W5")


def _load_python_preflight() -> Any:
    for path in _HELPER_CANDIDATES:
        if path.suffix != ".py" or not path.is_file():
            continue
        spec = importlib.util.spec_from_file_location("prod_ready_compose_secrets", path)
        assert spec is not None
        assert spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    msg = "W5 must add scripts/check_compose_operator_secrets.py (or sibling)"
    raise FileNotFoundError(msg)


def _validate(env: Mapping[str, str]) -> None:
    module = _load_python_preflight()
    fn = getattr(module, "validate_operator_secrets", None) or getattr(
        module,
        "check_operator_secrets",
        None,
    )
    assert callable(fn), "preflight module must export validate_operator_secrets"
    fn(env)


@_XFAIL_W5
def test_preflight_helper_exists() -> None:
    """W1.6 / D38: dedicated operator-secret preflight artefact must exist."""
    py_helpers = [p for p in _HELPER_CANDIDATES if p.suffix == ".py" and p.is_file()]
    sh_helpers = [p for p in _HELPER_CANDIDATES if p.suffix == ".sh" and p.is_file()]
    assert py_helpers or sh_helpers, (
        "W5 must add scripts/check_compose_operator_secrets.py "
        "(or check-compose-operator-secrets.sh / check_compose_secrets.py)"
    )


@_XFAIL_W5
@pytest.mark.parametrize("var", _VARS)
@pytest.mark.parametrize(
    "bad_value",
    ["", "   ", "change-me", "CHANGE-ME", "short"],
)
def test_preflight_rejects_empty_placeholder_and_low_entropy(
    var: str,
    bad_value: str,
) -> None:
    """W1.6 / D38: empty, change-me, and low-entropy values fail for all three vars."""
    env = {
        "SEVN_PROXY_SHARED_SECRET": "high-entropy-proxy-secret-value-32b",
        "SEVN_GATEWAY_TOKEN": "high-entropy-gateway-token-value-32b",
        "SEVN_SECRETS_PASSPHRASE": "high-entropy-secrets-passphrase-32b",
    }
    env[var] = bad_value
    with pytest.raises((SystemExit, ValueError, RuntimeError)) as caught:
        _validate(env)
    if isinstance(caught.value, SystemExit):
        assert caught.value.code not in (0, None)
    message = str(caught.value)
    assert var in message or bad_value.strip() in message or "secret" in message.lower()


@_XFAIL_W5
def test_preflight_accepts_high_entropy_values() -> None:
    """W1.6 happy path: strong values for all three variables pass."""
    env = {
        "SEVN_PROXY_SHARED_SECRET": "high-entropy-proxy-secret-value-32b",
        "SEVN_GATEWAY_TOKEN": "high-entropy-gateway-token-value-32b",
        "SEVN_SECRETS_PASSPHRASE": "high-entropy-secrets-passphrase-32b",
    }
    _validate(env)


@_XFAIL_W5
def test_compose_up_runs_preflight_before_docker_compose() -> None:
    """W1.6: ``make compose-up`` invokes the preflight before starting services."""
    text = _MAKEFILE.read_text(encoding="utf-8")
    match = re.search(
        r"^compose-up:.*?$(?P<body>(?:\n\t[^\n]*)+)",
        text,
        re.MULTILINE,
    )
    assert match is not None, "compose-up target missing from Makefile"
    body = match.group("body")
    preflight_hit = any(
        needle in body
        for needle in (
            "check_compose_operator_secrets",
            "check-compose-operator-secrets",
            "check_compose_secrets",
            "operator.secret",
            "OPERATOR_SECRET",
            "validate_operator_secrets",
        )
    )
    assert preflight_hit, "compose-up must call the operator-secret preflight"
    # Preflight must appear before docker compose up.
    compose_idx = body.find("docker compose")
    assert compose_idx != -1
    preflight_idxs = [
        body.find(n)
        for n in (
            "check_compose_operator_secrets",
            "check-compose-operator-secrets",
            "check_compose_secrets",
            "validate_operator_secrets",
        )
        if body.find(n) != -1
    ]
    assert preflight_idxs, "preflight invocation not found in compose-up body"
    assert min(preflight_idxs) < compose_idx, "preflight must run before docker compose"


@_XFAIL_W5
def test_preflight_wired_into_ci_tier() -> None:
    """W1.6 / Global convention 9: operator-secret preflight is reachable from a ci-* tier."""
    text = _MAKEFILE.read_text(encoding="utf-8")
    # Must name the *new* secrets preflight — not only the existing check-compose-default.
    assert (
        "check_compose_operator_secrets" in text
        or "check-compose-operator-secrets" in text
        or "check_compose_secrets" in text
        or "validate_operator_secrets" in text
    ), "operator-secret preflight must be wired into Makefile / a ci-* tier"
    assert re.search(
        r"^ci-\w+:[^\n]*(?:check_compose_operator_secrets|check-compose-operator-secrets|"
        r"check_compose_secrets|validate_operator_secrets)",
        text,
        re.MULTILINE,
    ) or re.search(
        r"(?:check_compose_operator_secrets|check-compose-operator-secrets|"
        r"check_compose_secrets).*",
        text,
    ), "ci-* tier (or shared recipe) must invoke the operator-secret preflight"
