"""Dashboard login cookie Secure flag (`specs/24-dashboard.md` §3)."""

from __future__ import annotations

from pathlib import Path

from tests.ui.dashboard.test_local_open_auth import _client, _workspace


def test_login_http_cookies_omit_secure(tmp_path: Path) -> None:
    ws = _workspace(local_open=False)
    with _client(tmp_path, workspace=ws, remote=True) as client:
        resp = client.post("/api/v1/auth/login", json={"password": "pw"})
    assert resp.status_code == 200
    for header in resp.headers.get_list("set-cookie"):
        assert "Secure" not in header


def test_login_forwarded_https_cookies_include_secure(tmp_path: Path) -> None:
    ws = _workspace(local_open=False)
    with _client(tmp_path, workspace=ws, remote=True) as client:
        resp = client.post(
            "/api/v1/auth/login",
            json={"password": "pw"},
            headers={"x-forwarded-proto": "https"},
        )
    assert resp.status_code == 200
    cookies = resp.headers.get_list("set-cookie")
    assert len(cookies) >= 2
    for header in cookies:
        assert "Secure" in header
