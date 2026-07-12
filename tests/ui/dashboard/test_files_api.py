"""Mission Control workspace file API tests (MC W1)."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from sevn.config.workspace_config import (
    DashboardWorkspaceConfig,
    SecurityScannerSubConfig,
    SecurityWorkspaceConfig,
    WorkspaceConfig,
)
from sevn.gateway.http_server import create_app
from sevn.storage.migrate import apply_migrations
from sevn.ui.dashboard.services.auth import DASHBOARD_CSRF_COOKIE_NAME, DASHBOARD_CSRF_HEADER
from sevn.workspace.layout import WorkspaceLayout


@contextmanager
def _client(tmp_path: Path) -> Iterator[TestClient]:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "workspace_root": ".", "gateway": {"token": "test-gw-token"}}',
        encoding="utf-8",
    )
    cfg = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        dashboard=DashboardWorkspaceConfig(
            enabled=True,
            login_password="pw",
            jwt_secret="dashboard-secret",
            local_open=False,
        ),
        security=SecurityWorkspaceConfig(
            scanner=SecurityScannerSubConfig(heuristic_only=True),
        ),
        gateway={"token": "test-gw-token"},
    )
    layout = WorkspaceLayout.from_config(sevn_json, cfg)

    def factory() -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        apply_migrations(conn)
        return conn

    app = create_app(workspace=cfg, layout=layout, sqlite_connection_factory=factory)
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client


def _login(client: TestClient) -> dict[str, str]:
    login = client.post("/api/v1/auth/login", json={"password": "pw", "totp": "000000"})
    assert login.status_code == 200
    token = client.cookies.get(DASHBOARD_CSRF_COOKIE_NAME)
    assert token
    return {DASHBOARD_CSRF_HEADER: token}


def test_files_write_read_roundtrip(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        headers = _login(client)
        put = client.put(
            "/api/v1/files/content",
            headers=headers,
            json={"path": "notes/hello.md", "content": "# hi\n", "create_parents": True},
        )
        assert put.status_code == 200
        got = client.get("/api/v1/files/content?path=notes/hello.md")
        assert got.status_code == 200
        assert got.json()["content"] == "# hi\n"


def test_files_traversal_rejected(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        headers = _login(client)
        resp = client.put(
            "/api/v1/files/content",
            headers=headers,
            json={"path": "../outside.md", "content": "nope"},
        )
        assert resp.status_code == 403


def test_files_env_path_forbidden(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("X=1", encoding="utf-8")
    with _client(tmp_path) as client:
        _login(client)
        assert client.get("/api/v1/files/content?path=.env").status_code == 403


def test_files_secrets_dir_forbidden(tmp_path: Path) -> None:
    secrets = tmp_path / ".sevn" / "secrets"
    secrets.mkdir(parents=True)
    (secrets / "store.enc").write_bytes(b"\x00\x01")
    with _client(tmp_path) as client:
        _login(client)
        assert client.get("/api/v1/files/content?path=.sevn/secrets/store.enc").status_code == 403


def test_files_skills_core_write_forbidden(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        headers = _login(client)
        resp = client.put(
            "/api/v1/files/content",
            headers=headers,
            json={"path": "skills/core/demo/SKILL.md", "content": "rw", "create_parents": True},
        )
        assert resp.status_code == 403


def test_files_skills_user_write_ok(tmp_path: Path) -> None:
    user = tmp_path / "skills" / "user" / "mine"
    user.mkdir(parents=True)
    with _client(tmp_path) as client:
        headers = _login(client)
        resp = client.put(
            "/api/v1/files/content",
            headers=headers,
            json={"path": "skills/user/mine/SKILL.md", "content": "ok", "create_parents": True},
        )
        assert resp.status_code == 200


def test_files_missing_csrf_rejected(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        _login(client)
        resp = client.put(
            "/api/v1/files/content",
            json={"path": "a.md", "content": "x"},
        )
        assert resp.status_code == 403


def test_files_unauthenticated_rejected(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        resp = client.get(
            "/api/v1/files/tree",
            headers={"X-Forwarded-For": "203.0.113.1"},
        )
        assert resp.status_code == 401


def test_files_symlink_escape_rejected(tmp_path: Path) -> None:
    if os.name == "nt":
        pytest.skip("symlink test unix-only")
    outside_dir = tmp_path.parent / f"outside-{tmp_path.name}"
    outside_dir.mkdir(exist_ok=True)
    outside = outside_dir / "outside.md"
    outside.write_text("secret", encoding="utf-8")
    link = tmp_path / "link.md"
    link.symlink_to(outside)
    with _client(tmp_path) as client:
        _login(client)
        assert client.get("/api/v1/files/content?path=link.md").status_code == 403


def test_files_oversize_rejected(tmp_path: Path) -> None:
    big = tmp_path / "big.md"
    big.write_text("x" * (1_048_576 + 1), encoding="utf-8")
    with _client(tmp_path) as client:
        _login(client)
        assert client.get("/api/v1/files/content?path=big.md").status_code == 413


def test_files_create_new_ok(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        headers = _login(client)
        resp = client.post(
            "/api/v1/files",
            headers=headers,
            json={"path": "notes/new.md", "content": "# created\n"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["path"] == "notes/new.md"
        assert body["size"] == len(b"# created\n")
        on_disk = tmp_path / "notes" / "new.md"
        assert on_disk.is_file()
        assert on_disk.read_text(encoding="utf-8") == "# created\n"


def test_files_create_conflict(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        headers = _login(client)
        first = client.post(
            "/api/v1/files",
            headers=headers,
            json={"path": "dup.md", "content": "first"},
        )
        assert first.status_code == 201
        second = client.post(
            "/api/v1/files",
            headers=headers,
            json={"path": "dup.md", "content": "second"},
        )
        assert second.status_code == 409
        assert second.json()["detail"] == "file already exists"


def test_files_create_confinement_rejected(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        headers = _login(client)
        resp = client.post(
            "/api/v1/files",
            headers=headers,
            json={"path": "skills/core/demo/SKILL.md", "content": "nope"},
        )
        assert resp.status_code == 403


def test_files_rename_ok(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        headers = _login(client)
        created = client.post(
            "/api/v1/files",
            headers=headers,
            json={"path": "notes/old.md", "content": "before\n"},
        )
        assert created.status_code == 201
        resp = client.post(
            "/api/v1/files/rename",
            headers=headers,
            json={"from": "notes/old.md", "to": "notes/new.md"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["from"] == "notes/old.md"
        assert body["to"] == "notes/new.md"
        assert not (tmp_path / "notes" / "old.md").exists()
        renamed = tmp_path / "notes" / "new.md"
        assert renamed.is_file()
        assert renamed.read_text(encoding="utf-8") == "before\n"


def test_files_rename_source_missing(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        headers = _login(client)
        resp = client.post(
            "/api/v1/files/rename",
            headers=headers,
            json={"from": "missing.md", "to": "elsewhere.md"},
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "source missing"


def test_files_rename_destination_exists(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        headers = _login(client)
        first = client.post(
            "/api/v1/files",
            headers=headers,
            json={"path": "a.md", "content": "a"},
        )
        second = client.post(
            "/api/v1/files",
            headers=headers,
            json={"path": "b.md", "content": "b"},
        )
        assert first.status_code == 201
        assert second.status_code == 201
        resp = client.post(
            "/api/v1/files/rename",
            headers=headers,
            json={"from": "a.md", "to": "b.md"},
        )
        assert resp.status_code == 409
        assert resp.json()["detail"] == "destination exists"


def test_files_rename_confinement_rejected(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        headers = _login(client)
        created = client.post(
            "/api/v1/files",
            headers=headers,
            json={"path": "notes/move-me.md", "content": "x"},
        )
        assert created.status_code == 201
        resp = client.post(
            "/api/v1/files/rename",
            headers=headers,
            json={"from": "notes/move-me.md", "to": "skills/core/demo/SKILL.md"},
        )
        assert resp.status_code == 403


def test_files_delete_soft_trash(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        headers = _login(client)
        created = client.post(
            "/api/v1/files",
            headers=headers,
            json={"path": "notes/trash-me.md", "content": "bye\n"},
        )
        assert created.status_code == 201
        original = tmp_path / "notes" / "trash-me.md"
        assert original.is_file()
        resp = client.delete(
            "/api/v1/files",
            headers=headers,
            params={"path": "notes/trash-me.md"},
        )
        assert resp.status_code == 200
        body = resp.json()
        trashed_rel = body["trashed_path"]
        assert ".sevn/trash/" in trashed_rel
        assert not original.exists()
        trashed = tmp_path / Path(trashed_rel)
        assert trashed.is_file()
        assert trashed.read_text(encoding="utf-8") == "bye\n"


def test_files_delete_hard(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        headers = _login(client)
        created = client.post(
            "/api/v1/files",
            headers=headers,
            json={"path": "notes/hard-delete.md", "content": "gone\n"},
        )
        assert created.status_code == 201
        original = tmp_path / "notes" / "hard-delete.md"
        assert original.is_file()
        resp = client.delete(
            "/api/v1/files",
            headers=headers,
            params={"path": "notes/hard-delete.md", "soft": "false"},
        )
        assert resp.status_code == 204
        assert not original.exists()
        trash_root = tmp_path / ".sevn" / "trash"
        if trash_root.exists():
            assert not any(trash_root.rglob("hard-delete.md"))


def test_files_delete_missing(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        headers = _login(client)
        resp = client.delete(
            "/api/v1/files",
            headers=headers,
            params={"path": "missing.md"},
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "not found"


def test_files_delete_confinement_rejected(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        headers = _login(client)
        resp = client.delete(
            "/api/v1/files",
            headers=headers,
            params={"path": "skills/core/demo/SKILL.md"},
        )
        assert resp.status_code == 403
