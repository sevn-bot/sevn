"""Prod-ready Batch A W1.7 RED — authenticated proxy healthcheck (C1.4; D39).

Proxy healthcheck presents the resolved service secret against a guarded prefix and
treats 503/401 as unhealthy. ``/healthz`` stays as liveness. Parses
``docker/docker-compose.yml`` directly — no Docker daemon. Green after W5.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BASE_COMPOSE = _REPO_ROOT / "docker" / "docker-compose.yml"

_GUARDED_PREFIX_RE = re.compile(r"/(?:llm|web|integration)(?:/|\b|['\"])")
_SECRET_HEADER_RE = re.compile(
    r"X-Sevn-Proxy-Token|SEVN_PROXY_SHARED_SECRET|proxy.shared.secret",
    re.IGNORECASE,
)
_UNHEALTHY_STATUS_RE = re.compile(r"503|401|unhealthy|raise|sys\.exit|HTTPError")

_XFAIL_W5 = pytest.mark.xfail(strict=True, reason="prod-ready W5")


def _load_proxy_service() -> dict[str, Any]:
    data = yaml.safe_load(_BASE_COMPOSE.read_text(encoding="utf-8")) or {}
    services = data.get("services") or {}
    proxy = services.get("sevn-proxy")
    assert isinstance(proxy, dict), "sevn-proxy service missing"
    return proxy


def _healthcheck_blob(proxy: dict[str, Any]) -> str:
    hc = proxy.get("healthcheck") or {}
    test = hc.get("test")
    if isinstance(test, list):
        return " ".join(str(part) for part in test)
    if isinstance(test, str):
        return test
    return str(hc)


def test_healthz_liveness_probe_still_present() -> None:
    """W1.7 / D39 baseline: ``/healthz`` remains (added probe must not replace it)."""
    blob = _healthcheck_blob(_load_proxy_service())
    corpus = _BASE_COMPOSE.read_text(encoding="utf-8")
    assert "/healthz" in blob or "/healthz" in corpus


@_XFAIL_W5
def test_proxy_healthcheck_probes_guarded_prefix_with_secret() -> None:
    """W1.7 / C1.4: authenticated probe hits a guarded family with the service secret."""
    blob = _healthcheck_blob(_load_proxy_service())
    assert _GUARDED_PREFIX_RE.search(blob), (
        f"healthcheck must probe a guarded prefix (/llm, /web, or /integration); got: {blob!r}"
    )
    assert _SECRET_HEADER_RE.search(blob), (
        f"healthcheck must present the resolved service secret; got: {blob!r}"
    )


@_XFAIL_W5
def test_proxy_healthcheck_treats_503_or_401_as_unhealthy() -> None:
    """W1.7 / D39: 503 (unconfigured) and 401 (bad secret) fail the healthcheck."""
    blob = _healthcheck_blob(_load_proxy_service())
    assert _UNHEALTHY_STATUS_RE.search(blob), (
        f"healthcheck must treat 503/401 as unhealthy (non-zero exit); got: {blob!r}"
    )


@_XFAIL_W5
def test_authenticated_probe_does_not_target_provider_spend_path() -> None:
    """W1.7: probe must not consume provider quota (no chat/completions spend path)."""
    blob = _healthcheck_blob(_load_proxy_service())
    assert _GUARDED_PREFIX_RE.search(blob), "authenticated guarded probe missing from healthcheck"
    lowered = blob.lower()
    forbidden = ("chat/completions", "messages", "completions", "responses")
    # Allow a dedicated no-op / auth-check path under /llm if present.
    if any(token in lowered for token in forbidden):
        assert (
            "auth" in lowered or "health" in lowered or "noop" in lowered or "ready" in lowered
        ), "guarded probe appears to call a spend path without a no-op marker"
