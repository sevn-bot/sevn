"""Mission Control MC-8 Knowledge tabs (`specs/24-dashboard.md` §10.13)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from sevn.config.workspace_config import (
    DashboardWorkspaceConfig,
    MemoryWorkspaceSectionConfig,
    SecurityScannerSubConfig,
    SecurityWorkspaceConfig,
    UserModelWorkspaceConfig,
    WorkspaceConfig,
)
from sevn.gateway.http_server import MISSION_CONTROL_SPA_ROOT, create_app
from sevn.storage.migrate import apply_migrations
from sevn.tools.memory_tools import store_memory_row
from sevn.ui.dashboard.services.auth import DASHBOARD_CSRF_COOKIE_NAME, DASHBOARD_CSRF_HEADER
from sevn.ui.dashboard.tab_registry import WIRED_SLUGS
from sevn.workspace.layout import WorkspaceLayout


@contextmanager
def _client(tmp_path: Path) -> Iterator[TestClient]:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "workspace_root": ".", "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
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


def _login(client: TestClient) -> dict[str, str]:
    login = client.post("/api/v1/auth/login", json={"password": "pw", "totp": "000000"})
    assert login.status_code == 200
    token = client.cookies.get(DASHBOARD_CSRF_COOKIE_NAME)
    assert token
    return {DASHBOARD_CSRF_HEADER: token}


def test_mc8_wired_slugs_include_knowledge_tabs() -> None:
    assert {"memory", "second-brain", "workspace-files", "code-understanding"} <= WIRED_SLUGS


def test_knowledge_memory_lists_sqlite_rows(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        _login(client)
        conn: sqlite3.Connection = client.app.state.sqlite_conn
        store_memory_row(conn, session_id="s1", key="note", content="deploy plan")
        (tmp_path / "MEMORY.md").write_text("# long\nline two\n", encoding="utf-8")
        resp = client.get("/api/v1/knowledge/memory?limit=10")
        assert resp.status_code == 200
        body = resp.json()
        assert body["sqlite_count"] == 1
        assert body["sqlite_rows"][0]["key"] == "note"
        assert body["memory_md"]["present"] is True
        assert body["memory_md"]["line_count"] == 2


def test_knowledge_memory_redacts_sensitive_keys(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        _login(client)
        conn: sqlite3.Connection = client.app.state.sqlite_conn
        store_memory_row(conn, session_id="s1", key="api_key", content="should-not-show")
        resp = client.get("/api/v1/knowledge/memory")
        assert resp.status_code == 200
        assert resp.json()["sqlite_rows"][0]["content_preview"] == "<redacted>"


def test_knowledge_second_brain_vault_layout(tmp_path: Path) -> None:
    vault = tmp_path / "second_brain" / "users" / "owner" / "wiki"
    vault.mkdir(parents=True)
    (vault / "index.md").write_text("# Index\n- [[a.md]]\n", encoding="utf-8")
    (vault / "a.md").write_text("body\n", encoding="utf-8")
    with _client(tmp_path) as client:
        _login(client)
        resp = client.get("/api/v1/knowledge/second-brain")
        assert resp.status_code == 200
        body = resp.json()
        assert body["scope"] == "owner"
        assert body["wiki_page_count"] >= 1
        assert body["gateway_fetch"] == "/api/second_brain/fetch"
        paths = {p["path"] for p in body["wiki_pages"]}
        assert "a.md" in paths


def test_knowledge_workspace_files_lists_with_redaction(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("hi", encoding="utf-8")
    (tmp_path / ".env").write_text("SECRET=1", encoding="utf-8")
    sub = tmp_path / "pkg"
    sub.mkdir()
    with _client(tmp_path) as client:
        _login(client)
        resp = client.get("/api/v1/knowledge/workspace-files?path=.")
        assert resp.status_code == 200
        body = resp.json()
        names = {e["name"] for e in body["entries"]}
        assert "notes.txt" in names
        env_row = next(e for e in body["entries"] if e["name"] == ".env")
        assert env_row["redacted"] is True


def test_knowledge_workspace_files_rejects_invalid_path(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        _login(client)
        resp = client.get("/api/v1/knowledge/workspace-files?path=../etc")
        assert resp.status_code == 422


def test_knowledge_code_understanding_index(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        _login(client)
        resp = client.get("/api/v1/knowledge/code-understanding")
        assert resp.status_code == 200
        body = resp.json()
        assert "warnings" in body
        assert "mycode" in body
        assert "graphify" in body


def test_app_js_knowledge_panel_wiring() -> None:
    js = (MISSION_CONTROL_SPA_ROOT / "app.js").read_text(encoding="utf-8")
    assert "/api/v1/knowledge/memory" in js
    assert "/api/v1/knowledge/second-brain" in js
    assert "/api/v1/knowledge/workspace-files" in js
    assert "/api/v1/knowledge/code-understanding" in js
    assert "renderMemory" in js
    assert "renderSecondBrain" in js
    assert "renderWorkspaceFiles" in js
    assert "renderCodeUnderstanding" in js


def test_knowledge_routes_require_auth(tmp_path: Path) -> None:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "workspace_root": ".", "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
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
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    layout = WorkspaceLayout.from_config(sevn_json, cfg)
    app = create_app(workspace=cfg, layout=layout)
    with TestClient(app, client=("203.0.113.1", 40000), raise_server_exceptions=True) as client:
        assert client.get("/api/v1/knowledge/memory").status_code == 401


@pytest.mark.asyncio
async def test_knowledge_memory_user_model_after_turn_hook(tmp_path: Path) -> None:
    """Post-turn extraction populates ``user_model.json`` surfaced by the Memory tab API."""
    import asyncio
    import json
    from unittest.mock import patch

    from sevn.gateway.post_turn_hooks import PostTurnContext
    from sevn.gateway.turn_metadata import record_turn_start
    from sevn.gateway.user_model_turn import maybe_schedule_user_model_extraction_after_turn

    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "workspace_root": ".", "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        encoding="utf-8",
    )
    cfg = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        providers={
            "use_main_model_for_all": True,
            "tier_default": {"triager": "openai/gpt-4o-mini"},
        },
        memory=MemoryWorkspaceSectionConfig(
            user_model=UserModelWorkspaceConfig(enabled=True, trigger_tiers=["B", "C", "D"]),
        ),
        dashboard=DashboardWorkspaceConfig(
            enabled=True,
            login_password="pw",
            jwt_secret="dashboard-secret",
            local_open=False,
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
        conn.execute(
            """
            INSERT INTO gateway_sessions (
                session_id, scope_key, channel, user_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("s1", "telegram:1", "telegram", "1", "now", "now"),
        )
        conn.commit()
        return conn

    app = create_app(workspace=cfg, layout=layout, sqlite_connection_factory=factory)
    with TestClient(app, raise_server_exceptions=True) as client:
        conn: sqlite3.Connection = client.app.state.sqlite_conn
        record_turn_start(
            conn,
            turn_id="turn-mc8",
            session_id="s1",
            intent="NEW_REQUEST",
            tier="B",
            confidence=0.9,
        )
        conn.execute(
            """
            INSERT INTO gateway_messages (
                session_id, turn_id, role, kind, content, status, created_at
            ) VALUES (?, ?, 'user', 'message', ?, 'sent', ?)
            """,
            ("s1", "turn-mc8", "I prefer dark mode UI", "now"),
        )
        conn.commit()
        router = client.app.state.gateway_router
        ctx = PostTurnContext(
            router=router,
            conn=conn,
            trace=client.app.state.gateway_trace,
            session_id="s1",
            correlation_id="turn-mc8",
            terminal_status="ok",
            turn_wall_ns=1,
        )

        class _FakeTransport:
            name = "chat_completions"

            async def complete(self, request: dict[str, object]) -> dict[str, object]:
                return {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "facts": [
                                            {
                                                "topic": "ui_theme",
                                                "value": "Prefers dark mode",
                                                "confidence": "high",
                                            }
                                        ]
                                    }
                                )
                            }
                        }
                    ]
                }

            async def stream(self, request: dict[str, object]):
                if False:
                    yield {}

            def auth_header(self, model_id: str) -> dict[str, str]:
                return {}

            def tokens_used(self, response: dict[str, object]) -> tuple[int, int]:
                return (1, 2)

            def cache_breakpoints(
                self, prompt_segments: list[dict[str, object]]
            ) -> list[dict[str, object]]:
                return list(prompt_segments)

        with patch(
            "sevn.gateway.user_model_turn.resolve_model",
            return_value=("openai/gpt-4o-mini", _FakeTransport()),
        ):
            await maybe_schedule_user_model_extraction_after_turn(ctx)
            await asyncio.sleep(0.08)

        headers = _login(client)
        resp = client.get("/api/v1/knowledge/memory", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["user_model"]["fact_count"] > 0
