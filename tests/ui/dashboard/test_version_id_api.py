"""Mission Control exposes ``version_id`` (plan D4 / W3 / #30)."""

from __future__ import annotations

import json
import sqlite3
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from starlette.testclient import TestClient

if TYPE_CHECKING:
    import pytest

from sevn.config.workspace_config import (
    DashboardWorkspaceConfig,
    SecurityScannerSubConfig,
    SecurityWorkspaceConfig,
    WorkspaceConfig,
)
from sevn.gateway.http_server import create_app
from sevn.storage.migrate import apply_migrations
from sevn.ui.dashboard.services.auth import DASHBOARD_CSRF_COOKIE_NAME
from sevn.workspace.layout import WorkspaceLayout


@contextmanager
def _client(tmp_path: Path, *, version_id: str | None = "mc-build-7") -> Iterator[TestClient]:
    sevn_json = tmp_path / "sevn.json"
    doc: dict[str, object] = {
        "schema_version": 1,
        "workspace_root": ".",
        "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
    }
    if version_id is not None:
        doc["version_id"] = version_id
    sevn_json.write_text(json.dumps(doc), encoding="utf-8")
    cfg = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        dashboard=DashboardWorkspaceConfig(
            enabled=True,
            login_password="pw",
            jwt_secret="dashboard-secret",
        ),
        security=SecurityWorkspaceConfig(
            scanner=SecurityScannerSubConfig(heuristic_only=True),
        ),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    layout = WorkspaceLayout.from_config(sevn_json, cfg)

    def factory() -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        apply_migrations(conn)
        return conn

    app = create_app(workspace=cfg, layout=layout, sqlite_connection_factory=factory)
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client


def _login(client: TestClient) -> None:
    login = client.post("/api/v1/auth/login", json={"password": "pw", "totp": "000000"})
    assert login.status_code == 200
    assert client.cookies.get(DASHBOARD_CSRF_COOKIE_NAME)


def test_config_payload_includes_top_level_version_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D4: system/config metadata JSON exposes ``version_id`` for System menu."""
    monkeypatch.setenv("SEVN_VERSION_ID", "mc-build-7")
    with _client(tmp_path, version_id="mc-build-7") as client:
        _login(client)
        resp = client.get("/api/v1/config")
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("version_id") == "mc-build-7"
        # Still present in the document after W2 persist (orthogonal check).
        assert body["document"].get("version_id") == "mc-build-7"


def test_config_payload_version_id_when_missing_from_doc(tmp_path: Path) -> None:
    """When ``sevn.json`` lacks the key, payload still exposes a string (may be unknown)."""
    with _client(tmp_path, version_id=None) as client:
        _login(client)
        resp = client.get("/api/v1/config")
        assert resp.status_code == 200
        body = resp.json()
        assert "version_id" in body
        assert isinstance(body["version_id"], str)
        assert body["version_id"].strip() != ""


def _run_git(cwd: Path, *args: str) -> None:
    """Run a fixed ``git`` argv in *cwd* (test helper; no shell)."""
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def test_boot_resolves_version_id_from_code_checkout_not_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Boot wiring resolves ``version_id`` from the code checkout, not the workspace.

    Regression guard for the ``0.0.1`` fallback (#30): ``create_app`` boot must
    resolve the real checkout via ``resolve_sevn_checkout_for_workspace`` and
    persist its ``<branch>_<short-sha>`` build id, even though ``content_root``
    (the operator workspace) is not a git tree. A future refactor that resolved
    from ``ly.content_root`` again would fail this by yielding the package version.
    """
    checkout = tmp_path / "checkout"
    pkg = checkout / "src" / "sevn"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (checkout / "pyproject.toml").write_text('[project]\nname = "sevn"\n', encoding="utf-8")
    _run_git(checkout, "init")
    _run_git(checkout, "config", "user.email", "t@example.com")
    _run_git(checkout, "config", "user.name", "t")
    _run_git(checkout, "add", "-A")
    _run_git(checkout, "commit", "-m", "init")
    _run_git(checkout, "branch", "-M", "release-x")
    short = subprocess.run(
        ["git", "rev-parse", "--short=8", "HEAD"],
        cwd=checkout,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    expected = f"release-x_{short}"

    # Point checkout resolution at the real repo (overrides the autouse fake repo),
    # and make sure no env override masks git resolution.
    monkeypatch.setenv("SEVN_REPO_ROOT", str(checkout))
    monkeypatch.delenv("SEVN_VERSION_ID", raising=False)

    ws = tmp_path / "ws"  # operator workspace — deliberately NOT a git tree.
    ws.mkdir()
    with _client(ws, version_id=None) as client:
        _login(client)
        body = client.get("/api/v1/config").json()
    assert body["version_id"] == expected, body["version_id"]
