"""Shared Mission Control dashboard schema build + validation helpers.

Module: scripts.mission_control_schema_lib
Depends: json, pathlib, re, sevn.gateway.http_server, sevn.ui.dashboard.dashboard_schema

Exports:
    build_schema_document — merge descriptors, nav, and live routes.
    collect_api_v1_routes — enumerate ``/api/v1`` routes from ``create_app``.
    endpoint_matches_route — match schema endpoint against live route table.
    normalize_schema_for_compare — strip volatile keys for golden diff.
    selector_token_in_app_js — verify a CSS selector token exists in ``app.js``.
    selector_tokens — extract id/class tokens from a CSS selector string.

Examples:
    >>> from pathlib import Path
    >>> isinstance(GOLDEN_PATH, Path)
    True
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sevn.config.workspace_config import (
    DashboardWorkspaceConfig,
    SecurityScannerSubConfig,
    SecurityWorkspaceConfig,
    WorkspaceConfig,
)
from sevn.gateway.http_server import create_app
from sevn.ui.dashboard.dashboard_schema import (
    DASHBOARD_SHELL,
    DASHBOARD_TAB_DESCRIPTORS,
)
from sevn.ui.dashboard.tab_registry import build_nav_payload
from sevn.workspace.layout import WorkspaceLayout

REPO = Path(__file__).resolve().parents[1]
APP_JS_PATH = REPO / "src" / "sevn" / "ui" / "spa" / "dashboard" / "app.js"
GOLDEN_PATH = REPO / "infra" / "mission-control.schema.json"
META_SCHEMA_PATH = REPO / "infra" / "mission-control.schema.meta.json"
SCHEMA_GAP_REPORT = REPO / "reports" / "mission-control-schema-gap.json"

__all__ = [
    "build_schema_document",
    "collect_api_v1_routes",
    "endpoint_matches_route",
    "normalize_schema_for_compare",
    "selector_token_in_app_js",
    "selector_tokens",
]

_SELECTOR_ID_RE = re.compile(r"#([a-zA-Z][\w-]*)")
_SELECTOR_CLASS_RE = re.compile(r"\.([a-zA-Z][\w-]*)")


def _minimal_test_app():
    """Build a gateway app with dashboard routes for route inventory.

    Returns:
        FastAPI: Application with ``/api/v1`` dashboard routes registered.

    Examples:
        >>> app = _minimal_test_app()
        >>> any(getattr(r, "path", "").startswith("/api/v1") for r in app.routes)
        True
    """
    import tempfile

    tmp = Path(tempfile.mkdtemp())
    sevn_json = tmp / "sevn.json"
    sevn_json.write_text(
        '{"schema_version": 1, "workspace_root": ".", "gateway": {"token": "schema-gate"}}',
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
        gateway={"token": "schema-gate"},
    )
    layout = WorkspaceLayout.from_config(sevn_json, cfg)
    return create_app(workspace=cfg, layout=layout)


def collect_api_v1_routes() -> list[dict[str, str]]:
    """Enumerate live ``/api/v1`` HTTP routes from the gateway app factory.

    Returns:
        list[dict[str, str]]: Sorted ``{"method", "path"}`` entries.

    Examples:
        >>> routes = collect_api_v1_routes()
        >>> any(r["path"] == "/api/v1/dashboard/nav" for r in routes)
        True
    """
    app = _minimal_test_app()
    rows: list[dict[str, str]] = []
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if not path or not path.startswith("/api/v1") or not methods:
            continue
        for method in sorted(methods - {"HEAD", "OPTIONS"}):
            rows.append({"method": method, "path": path})
    rows.sort(key=lambda row: (row["path"], row["method"]))
    return rows


def build_schema_document(*, generated_at: str | None = None) -> dict[str, Any]:
    """Merge tab descriptors, nav payload, shell, and live route inventory.

    Args:
        generated_at (str | None): ISO timestamp; defaults to UTC now.

    Returns:
        dict[str, Any]: Full schema document for golden emission.

    Examples:
        >>> doc = build_schema_document(generated_at="2026-01-01T00:00:00+00:00")
        >>> doc["tab_count"] == 45
        True
    """
    nav = build_nav_payload()
    tabs = {
        slug: dict(descriptor) for slug, descriptor in sorted(DASHBOARD_TAB_DESCRIPTORS.items())
    }
    return {
        "schema_version": 1,
        "generated_at": generated_at or datetime.now(tz=UTC).isoformat(),
        "tab_count": nav["tab_count"],
        "nav": nav,
        "shell": dict(DASHBOARD_SHELL),
        "tabs": tabs,
        "routes": collect_api_v1_routes(),
    }


def normalize_schema_for_compare(doc: dict[str, Any]) -> dict[str, Any]:
    """Return a copy suitable for golden diff (drop volatile timestamp).

    Args:
        doc (dict[str, Any]): Full schema document.

    Returns:
        dict[str, Any]: Normalized document without ``generated_at``.

    Examples:
        >>> normalized = normalize_schema_for_compare({"generated_at": "x", "a": 1})
        >>> "generated_at" not in normalized
        True
    """
    out = json.loads(json.dumps(doc, sort_keys=True))
    out.pop("generated_at", None)
    return out


def _split_endpoint(endpoint: str) -> tuple[str, list[str]]:
    """Split an endpoint into bare path and path segments.

    Args:
        endpoint (str): Schema endpoint (may include query string).

    Returns:
        tuple[str, list[str]]: Bare path and non-empty segments.

    Examples:
        >>> _split_endpoint("/api/v1/foo?x=1")
        ('/api/v1/foo', ['api', 'v1', 'foo'])
    """
    bare = endpoint.split("?", 1)[0]
    return bare, [seg for seg in bare.split("/") if seg]


def endpoint_matches_route(*, method: str, endpoint: str, routes: list[dict[str, str]]) -> bool:
    """Return whether ``method`` + ``endpoint`` matches a live route row.

    Path parameters in either side are treated as wildcards.

    Args:
        method (str): HTTP method (uppercase).
        endpoint (str): Schema endpoint (may include query string).
        routes (list[dict[str, str]]): Live route inventory.

    Returns:
        bool: ``True`` when a compatible route exists.

    Examples:
        >>> routes = [{"method": "GET", "path": "/api/v1/sessions/{session_id}/api-calls"}]
        >>> endpoint_matches_route(method="GET", endpoint="/api/v1/sessions/{id}/api-calls", routes=routes)
        True
    """
    _path, endpoint_segments = _split_endpoint(endpoint)
    method_u = method.upper()
    for row in routes:
        if row["method"].upper() != method_u:
            continue
        route_segments = [seg for seg in row["path"].split("/") if seg]
        if len(route_segments) != len(endpoint_segments):
            continue
        if all(
            es == rs or es.startswith("{") or rs.startswith("{")
            for es, rs in zip(endpoint_segments, route_segments, strict=True)
        ):
            return True
    return False


def selector_tokens(selector: str) -> list[str]:
    """Extract id and class tokens referenced by a CSS selector string.

    Args:
        selector (str): CSS selector (may include attribute clauses).

    Returns:
        list[str]: Unique ``#id`` and ``.class`` tokens in document order.

    Examples:
        >>> selector_tokens("#foo.bar[data-x]")
        ['foo', 'bar']
    """
    tokens: list[str] = []
    for match in _SELECTOR_ID_RE.finditer(selector):
        tokens.append(match.group(1))
    for match in _SELECTOR_CLASS_RE.finditer(selector):
        tokens.append(match.group(1))
    seen: set[str] = set()
    ordered: list[str] = []
    for token in tokens:
        if token not in seen:
            seen.add(token)
            ordered.append(token)
    return ordered


def selector_token_in_app_js(token: str, *, app_js_text: str) -> bool:
    """Return whether a selector token appears in the SPA source.

    Args:
        token (str): Id or class name without ``#`` / ``.`` prefix.
        app_js_text (str): Full ``app.js`` contents.

    Returns:
        bool: ``True`` when the token is referenced in source.

    Examples:
        >>> selector_token_in_app_js("login-panel", app_js_text='getElementById("login-panel")')
        True
    """
    patterns = (
        f'"{token}"',
        f"'{token}'",
        f"#{token}",
        f".{token}",
        f'getElementById("{token}")',
        f"getElementById('{token}')",
        f'querySelector("#{token}")',
        f'querySelector(".{token}")',
        f" {token}",
        f"{token} ",
    )
    return any(p in app_js_text for p in patterns) or token in app_js_text
