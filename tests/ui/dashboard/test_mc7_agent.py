"""Mission Control MC-7 Agent tabs (`specs/24-dashboard.md` §10.13)."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from starlette.testclient import TestClient

from sevn.config.workspace_config import DashboardWorkspaceConfig, WorkspaceConfig
from sevn.gateway.http_server import MISSION_CONTROL_SPA_ROOT, create_app
from sevn.skills.manager import SkillsManager
from sevn.storage.migrate import apply_migrations
from sevn.ui.dashboard.services.auth import DASHBOARD_CSRF_COOKIE_NAME, DASHBOARD_CSRF_HEADER
from sevn.ui.dashboard.tab_registry import WIRED_SLUGS
from sevn.workspace.layout import WorkspaceLayout


def _csrf_headers(client: TestClient) -> dict[str, str]:
    token = client.cookies.get(DASHBOARD_CSRF_COOKIE_NAME)
    assert token
    return {DASHBOARD_CSRF_HEADER: token}


@contextmanager
def _client(tmp_path: Path) -> Iterator[TestClient]:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workspace_root": ".",
                "providers": {
                    "use_main_model_for_all": True,
                    "tier_default": {"triager": "minimax/MiniMax-M2.7"},
                },
                "mcp_servers": {"echo": {"command": "echo", "args": ["hi"]}},
                "mcp_enabled": ["echo"],
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            },
        ),
        encoding="utf-8",
    )
    cfg = WorkspaceConfig(
        schema_version=1,
        workspace_root=".",
        providers={
            "use_main_model_for_all": True,
            "tier_default": {"triager": "minimax/MiniMax-M2.7"},
        },
        mcp_servers={"echo": {"command": "echo", "args": ["hi"]}},
        mcp_enabled=["echo"],
        dashboard=DashboardWorkspaceConfig(
            enabled=True,
            login_password="pw",
            jwt_secret="dashboard-secret",
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


def test_mc7_wired_slugs_include_agent_tabs() -> None:
    expected = {
        "agent-config",
        "model-params",
        "tools-permissions",
        "skills",
        "mcp-servers",
    }
    assert expected <= WIRED_SLUGS
    assert "coding-agents" in WIRED_SLUGS
    assert "claude-agent" not in WIRED_SLUGS


def test_spa_wires_model_params_render_and_save() -> None:
    """The SPA defines + dispatches + binds the Model Params tab and hits the API."""
    app_js = (MISSION_CONTROL_SPA_ROOT / "app.js").read_text(encoding="utf-8")
    assert "async function renderModelParams()" in app_js
    assert "function bindModelParamsHandlers()" in app_js
    assert 'if (tabSlug === "model-params") return renderModelParams();' in app_js
    assert "bindModelParamsHandlers();" in app_js
    assert 'apiGet("/api/v1/agent/llm-params")' in app_js
    assert 'apiPut("/api/v1/agent/llm-params"' in app_js
    assert '"model-params"' in app_js  # inline fallback wired list


def test_tools_health_lists_chronic_skill_row(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        login = client.post("/api/v1/auth/login", json={"password": "pw", "totp": "000000"})
        assert login.status_code == 200
        conn: sqlite3.Connection = client.app.state.sqlite_conn
        conn.execute(
            """
            INSERT INTO skills (
                workspace_id, skill_name, failure_count, chronic_skill_failure,
                failure_timestamps_json, updated_at_ns
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (".", "demo-skill", 4, 1, "[]", 1_700_000_000_000_000_000),
        )
        conn.commit()
        resp = client.get("/api/v1/agent/tools-health")
        assert resp.status_code == 200
        body = resp.json()
        names = {row["name"] for row in body["rows"]}
        assert "demo-skill" in names
        assert body["rows"][0]["layer"] == "skill"


def test_skills_inventory_and_promote_generated(tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    gen = skills_root / "generated" / "promo"
    gen.mkdir(parents=True)
    (gen / "SKILL.md").write_text(
        "---\nname: promo\nversion: 0.0.1\ndescription: test\nquarantine: true\n---\n",
        encoding="utf-8",
    )
    SkillsManager.reset_singletons_for_tests()
    with _client(tmp_path) as client:
        login = client.post("/api/v1/auth/login", json={"password": "pw", "totp": "000000"})
        assert login.status_code == 200
        listed = client.get("/api/v1/agent/skills")
        assert listed.status_code == 200
        skills = listed.json()["skills"]
        promo = next(s for s in skills if s["id"] == "promo")
        assert promo["quarantine"] is True
        assert promo["can_promote"] is True
        headers = _csrf_headers(client)
        promoted = client.post(
            "/api/v1/agent/skills/promo/promote",
            headers=headers,
        )
        assert promoted.status_code == 200
        assert (skills_root / "user" / "promo" / "SKILL.md").is_file()
        assert not (gen / "SKILL.md").exists()


def test_mcp_servers_registry_includes_declared_server(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        login = client.post("/api/v1/auth/login", json={"password": "pw", "totp": "000000"})
        assert login.status_code == 200
        resp = client.get("/api/v1/agent/mcp-servers")
        assert resp.status_code == 200
        body = resp.json()
        ids = {row["server_id"] for row in body["servers"]}
        assert "echo" in ids


def test_agent_config_get_and_put_unified_flag(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        login = client.post("/api/v1/auth/login", json={"password": "pw", "totp": "000000"})
        assert login.status_code == 200
        got = client.get("/api/v1/agent/config")
        assert got.status_code == 200
        assert got.json()["use_main_model_for_all"] is True
        assert got.json()["main_model"] == "minimax/MiniMax-M2.7"
        headers = _csrf_headers(client)
        put = client.put(
            "/api/v1/agent/config",
            json={
                "use_main_model_for_all": False,
                "providers": {"tier_default": {"B": "openai/gpt-4o-mini"}},
            },
            headers=headers,
        )
        assert put.status_code == 200
        on_disk = json.loads((tmp_path / "sevn.json").read_text(encoding="utf-8"))
        assert on_disk["providers"]["use_main_model_for_all"] is False
        assert on_disk["providers"]["tier_default"]["B"] == "openai/gpt-4o-mini"


def test_llm_params_get_returns_default_doc(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        login = client.post("/api/v1/auth/login", json={"password": "pw", "totp": "000000"})
        assert login.status_code == 200
        got = client.get("/api/v1/agent/llm-params")
        assert got.status_code == 200
        body = got.json()
        # Source is "workspace" once the boot seed writes the file, "builtin" otherwise;
        # either way the doc equals the built-in default values.
        assert body["source"] in {"builtin", "workspace"}
        assert body["restart_required"] is True
        # Built-in defaults: lcm tuned to 0.2, MiniMax override top_k=40 (D4).
        assert body["doc"]["lcm"]["temperature"] == 0.2
        assert body["doc"]["tier_b"]["model_overrides"]["minimax/*"]["top_k"] == 40


def test_llm_params_put_validates_and_persists_to_workspace(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        login = client.post("/api/v1/auth/login", json={"password": "pw", "totp": "000000"})
        assert login.status_code == 200
        headers = _csrf_headers(client)
        doc = {
            "schema_version": 1,
            "tier_b": {
                "temperature": 0.3,
                "model_overrides": {"minimax/*": {"temperature": 0.9, "top_k": 50}},
            },
        }
        put = client.put("/api/v1/agent/llm-params", json={"doc": doc}, headers=headers)
        assert put.status_code == 200
        # Persisted to the workspace LLM_params_config.json, not sevn.json.
        params_path = tmp_path / "LLM_params_config.json"
        assert params_path.is_file()
        on_disk = json.loads(params_path.read_text(encoding="utf-8"))
        assert on_disk["tier_b"]["temperature"] == 0.3
        assert on_disk["tier_b"]["model_overrides"]["minimax/*"]["top_k"] == 50
        sevn_doc = json.loads((tmp_path / "sevn.json").read_text(encoding="utf-8"))
        assert "tier_b" not in sevn_doc
        # Subsequent GET now reports the workspace source.
        got = client.get("/api/v1/agent/llm-params")
        assert got.status_code == 200
        assert got.json()["source"] == "workspace"
        assert got.json()["doc"]["tier_b"]["temperature"] == 0.3


def test_llm_params_put_rejects_invalid_document(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        login = client.post("/api/v1/auth/login", json={"password": "pw", "totp": "000000"})
        assert login.status_code == 200
        headers = _csrf_headers(client)
        bad = client.put(
            "/api/v1/agent/llm-params",
            json={"doc": {"tier_b": {"top_p": 2.0}}},
            headers=headers,
        )
        assert bad.status_code == 422
        assert bad.json()["error"]["code"] == "validation_failed"
        # The invalid body is never persisted: GET still returns valid default values.
        got = client.get("/api/v1/agent/llm-params")
        assert got.status_code == 200
        tier_b = got.json()["doc"].get("tier_b", {})
        assert tier_b.get("top_p", 0.0) <= 1.0
