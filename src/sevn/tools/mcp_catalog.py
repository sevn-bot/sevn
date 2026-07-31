"""Curated MCP catalog presets for minimal safe default toolsets (#90, W29.5).

Module: sevn.tools.mcp_catalog
Depends: sevn.code_understanding.code_review_graph_mcp, sevn.config.defaults

Presets describe synthetic or declared servers with a conservative tool allowlist.
Mission Control surfaces them read-only; operators opt in via ``mcp_enabled``.

Exports:
    list_mcp_catalog_presets — bundled preset metadata rows.
    apply_catalog_preset_to_doc — merge one preset into a config document preview.
"""

from __future__ import annotations

from typing import Any

from sevn.code_understanding.code_review_graph_mcp import (
    code_review_graph_mcp_server_id,
    read_only_tool_names,
)
from sevn.config.defaults import DEFAULT_CODE_REVIEW_GRAPH_TOOL_PRESET


def list_mcp_catalog_presets() -> list[dict[str, Any]]:
    """Return curated MCP catalog preset descriptors (read-only metadata).

    Returns:
        list[dict[str, Any]]: Preset rows for Mission Control / onboarding.

    Examples:
        >>> presets = list_mcp_catalog_presets()
        >>> any(p["id"] == "code_review_read_only" for p in presets)
        True
    """
    crg_id = code_review_graph_mcp_server_id()
    return [
        {
            "id": "code_review_read_only",
            "title": "Code review (read-only)",
            "description": (
                "Minimal safe code-review-graph MCP toolset — query and impact analysis only."
            ),
            "server_id": crg_id,
            "tool_preset": DEFAULT_CODE_REVIEW_GRAPH_TOOL_PRESET,
            "tool_names": read_only_tool_names(),
            "synthetic": True,
            "safe_default": True,
        },
        {
            "id": "graphify_query",
            "title": "Graphify query-only",
            "description": "Graphify MCP with query/path/explain tools only (no write tools).",
            "server_id": "graphify",
            "tool_preset": "query_only",
            "tool_names": ["query", "path", "explain"],
            "synthetic": True,
            "safe_default": True,
        },
    ]


def apply_catalog_preset_to_doc(
    config_doc: dict[str, Any],
    preset_id: str,
) -> bool:
    """Merge one catalog preset's synthetic server row into a config document.

    Does not mutate ``mcp_enabled`` — callers decide opt-in separately.

    Args:
        config_doc (dict[str, Any]): Effective or preview config document (mutated).
        preset_id (str): Preset id from :func:`list_mcp_catalog_presets`.

    Returns:
        bool: ``True`` when a preset was applied.

    Examples:
        >>> doc: dict[str, object] = {"mcp_servers": {}}
        >>> apply_catalog_preset_to_doc(doc, "code_review_read_only")
        True
        >>> "code_review_graph" in doc["mcp_servers"]
        True
    """
    preset = next((row for row in list_mcp_catalog_presets() if row["id"] == preset_id), None)
    if preset is None:
        return False
    from pathlib import Path

    from sevn.code_understanding.code_review_graph_mcp import merge_code_review_graph_mcp_server
    from sevn.code_understanding.graphify_mcp import merge_gateway_mcp_servers
    from sevn.config.workspace_config import WorkspaceConfig

    servers = config_doc.setdefault("mcp_servers", {})
    if not isinstance(servers, dict):
        return False
    server_id = str(preset["server_id"])
    if preset_id == "code_review_read_only":
        cu = config_doc.setdefault("code_understanding", {})
        if isinstance(cu, dict):
            crg = cu.setdefault("code_review_graph", {})
            if isinstance(crg, dict):
                crg.setdefault("enabled", True)
                mcp = crg.setdefault("mcp", {})
                if isinstance(mcp, dict):
                    mcp["enabled"] = True
                    mcp["tool_preset"] = preset["tool_preset"]
        merge_code_review_graph_mcp_server(
            config_doc,
            workspace=WorkspaceConfig.model_validate(config_doc),
            content_root=Path(config_doc.get("workspace_root") or "."),
        )
        return server_id in servers
    if preset_id == "graphify_query":
        cu = config_doc.setdefault("code_understanding", {})
        if isinstance(cu, dict):
            graphify = cu.setdefault("graphify", {})
            if isinstance(graphify, dict):
                graphify.setdefault("enabled", True)
                mcp = graphify.setdefault("mcp", {})
                if isinstance(mcp, dict):
                    mcp["enabled"] = True
        merge_gateway_mcp_servers(
            config_doc,
            workspace=WorkspaceConfig.model_validate(config_doc),
            content_root=Path(config_doc.get("workspace_root") or "."),
        )
        row = servers.get(server_id)
        if isinstance(row, dict):
            row["catalog_preset"] = preset_id
            row["tool_preset"] = preset["tool_preset"]
        return server_id in servers
    return False


__all__ = ["apply_catalog_preset_to_doc", "list_mcp_catalog_presets"]
