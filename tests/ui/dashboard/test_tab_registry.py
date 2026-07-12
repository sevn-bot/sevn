"""Tests for Mission Control tab registry (`specs/24-dashboard.md` Wave MC-0B)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from starlette.testclient import TestClient

from sevn.config.workspace_config import (
    DashboardWorkspaceConfig,
    SecurityScannerSubConfig,
    SecurityWorkspaceConfig,
    WorkspaceConfig,
)
from sevn.gateway.http_server import create_app
from sevn.ui.dashboard.tab_registry import (
    DASHBOARD_GROUPS,
    POST_V1_PLACEHOLDER_SLUGS,
    TAB_SLUGS,
    WIRED_SLUGS,
    build_nav_payload,
    tab_slug,
)
from sevn.workspace.layout import WorkspaceLayout


def test_tab_slug_matches_spa_rules() -> None:
    assert tab_slug("Providers & LLMs") == "providers-llms"
    assert tab_slug("Canvas (OpenUI)") == "canvas-openui"
    assert tab_slug("Budget & Cost") == "budget-cost"


def test_registry_has_forty_five_tabs_in_eight_groups() -> None:
    group_count = len(DASHBOARD_GROUPS)
    tab_count = sum(len(names) for _group, names in DASHBOARD_GROUPS)
    assert group_count == 8
    assert tab_count == 45
    assert len(TAB_SLUGS) == 45


def test_wired_and_post_v1_sets_are_subsets() -> None:
    assert WIRED_SLUGS <= TAB_SLUGS
    assert POST_V1_PLACEHOLDER_SLUGS <= TAB_SLUGS
    assert frozenset() == POST_V1_PLACEHOLDER_SLUGS
    assert "coding-agents" in WIRED_SLUGS
    assert len(WIRED_SLUGS) >= 14
    assert {"overview", "canvas-openui", "sessions"} <= WIRED_SLUGS


def test_mc15_all_tabs_wired_or_post_v1_no_stubs() -> None:
    """Wave MC-15: every tab is wired or post-v1 placeholder (no registry stubs)."""
    assert TAB_SLUGS == WIRED_SLUGS | POST_V1_PLACEHOLDER_SLUGS
    assert len(WIRED_SLUGS) == 45
    assert len(POST_V1_PLACEHOLDER_SLUGS) == 0
    payload = build_nav_payload()
    kinds = {
        str(tab["kind"])
        for group in payload["groups"]
        for tab in group["tabs"]  # type: ignore[union-attr]
    }
    assert kinds == {"wired"}


def test_build_nav_payload_shape() -> None:
    payload = build_nav_payload()
    assert payload["tab_count"] == 45
    assert len(payload["groups"]) == 8
    assert len(payload["tabs"]) == 45
    assert set(payload["wired_slugs"]) == set(WIRED_SLUGS)
    assert set(payload["post_v1_placeholder_slugs"]) == set(POST_V1_PLACEHOLDER_SLUGS)
    first_tab = payload["groups"][0]["tabs"][0]
    assert first_tab["name"] == "Overview"
    assert first_tab["slug"] == "overview"
    assert first_tab["path"] == "/mission/overview"
    assert first_tab["kind"] == "wired"


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
        ),
        security=SecurityWorkspaceConfig(
            scanner=SecurityScannerSubConfig(heuristic_only=True),
        ),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    layout = WorkspaceLayout.from_config(sevn_json, cfg)
    app = create_app(workspace=cfg, layout=layout)
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client


def test_dashboard_nav_requires_auth(tmp_path: Path) -> None:
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
        ),
        security=SecurityWorkspaceConfig(
            scanner=SecurityScannerSubConfig(heuristic_only=True),
        ),
        gateway={"token": "${SECRET:keychain:sevn.gateway.token}"},
    )
    layout = WorkspaceLayout.from_config(sevn_json, cfg)
    app = create_app(workspace=cfg, layout=layout)
    with TestClient(app, client=("203.0.113.1", 40000), raise_server_exceptions=True) as client:
        assert client.get("/api/v1/dashboard/nav").status_code == 401


def test_dashboard_nav_returns_registry_after_login(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        login = client.post("/api/v1/auth/login", json={"password": "pw", "totp": "000000"})
        assert login.status_code == 200
        resp = client.get("/api/v1/dashboard/nav")
        assert resp.status_code == 200
        body = resp.json()
        assert body["tab_count"] == 45
        assert len(body["groups"]) == 8
        assert body["wired_slugs"] == sorted(WIRED_SLUGS)
