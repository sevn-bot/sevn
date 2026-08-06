"""A-V3 behavioral coverage — create_app loads bootstrap secret without workspace.

Stock-stack path that A-V1 missed: ``SEVN_HOME`` bound, no ``sevn.json``, env
``SEVN_PROXY_SHARED_SECRET`` blank, generate-once file present under
``{SEVN_HOME}/.sevn/proxy-shared-secret``. ``create_app()`` must present as
configured (guarded probe is not 503 ``PROXY_UNCONFIGURED``).

D40 remains: file absent + env blank → fail-closed 503.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from sevn.proxy.app import create_app
from sevn.proxy.auth import PROXY_UNCONFIGURED_DETAIL
from sevn.proxy.bootstrap_secret import (
    PROXY_SHARED_SECRET_RELPATH,
    ensure_proxy_shared_secret_file,
)

_BOOTSTRAP_SECRET = "a-v3-bootstrap-file-secret-value-32ch"


def _stock_home_without_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Pin ``SEVN_HOME`` to an empty operator root (no ``sevn.json`` / no env secret)."""
    home = tmp_path / "operator"
    home.mkdir()
    monkeypatch.setenv("SEVN_HOME", str(home))
    monkeypatch.delenv("SEVN_PROXY_SHARED_SECRET", raising=False)
    monkeypatch.delenv("SEVN_PROXY_ALLOW_UNAUTHENTICATED", raising=False)
    # Avoid cwd walk-up finding a developer ``sevn.json`` (bound path is absent).
    monkeypatch.chdir(home)
    assert not (home / "workspace" / "sevn.json").is_file()
    return home


@pytest.mark.anyio
async def test_create_app_fail_closed_503_without_bootstrap_file_or_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D40: blank env + absent bootstrap file must still 503 on guarded routes."""
    _stock_home_without_workspace(tmp_path, monkeypatch)
    assert not (tmp_path / "operator" / PROXY_SHARED_SECRET_RELPATH).is_file()

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/web/auth-check")

    assert resp.status_code == 503
    assert resp.json()["detail"] == PROXY_UNCONFIGURED_DETAIL


@pytest.mark.anyio
async def test_create_app_loads_bootstrap_secret_file_without_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A-V3: bootstrap file + blank env + no sevn.json → configured (not 503)."""
    home = _stock_home_without_workspace(tmp_path, monkeypatch)
    path = ensure_proxy_shared_secret_file(home, secret=_BOOTSTRAP_SECRET)
    assert path.is_file()
    assert path.read_text(encoding="utf-8").strip() == _BOOTSTRAP_SECRET

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        unauth = await client.get("/web/auth-check")
        ok = await client.get(
            "/web/auth-check",
            headers={"X-Sevn-Proxy-Token": _BOOTSTRAP_SECRET},
        )

    # Present as configured: auth challenge (401), never PROXY_UNCONFIGURED 503.
    assert unauth.status_code != 503, (
        "create_app() ignored bootstrap secret file on env-only boot (A-V1); "
        f"got {unauth.status_code} {unauth.text}"
    )
    assert unauth.status_code == 401
    assert unauth.json().get("detail") != PROXY_UNCONFIGURED_DETAIL

    assert ok.status_code == 200
    assert ok.json() == {"status": "ok", "probe": "auth-check"}
