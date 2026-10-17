"""Health and the static SPA (D13, D19)."""

from __future__ import annotations

from pathlib import Path

from support.http_app import CSP, INDEX_HTML


def test_health(host_app: tuple[object, str, object]) -> None:
    _app, _token, client = host_app
    response = client.get("/health")  # type: ignore[attr-defined]
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert isinstance(body["version"], str) and body["version"]
    assert isinstance(body["host_id"], str)
    assert body["host_id"].startswith("host_")


def test_spa_served_with_csp(host_app: tuple[object, str, object], tmp_path: Path) -> None:
    _app, _token, client = host_app
    response = client.get("/")  # type: ignore[attr-defined]
    assert response.status_code == 200
    assert response.text == INDEX_HTML
    assert (tmp_path / "webdist" / "index.html").read_text(encoding="utf-8") == INDEX_HTML
    assert response.headers["content-security-policy"] == CSP
