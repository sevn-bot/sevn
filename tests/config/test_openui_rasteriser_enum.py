"""W1 RED — OpenUI rasteriser enum drops playwright (DP7; green after W5)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError


def test_openui_rasteriser_accepts_only_weasyprint() -> None:
    """DP7: OpenUIWorkspaceConfig.rasteriser is weasyprint-only."""
    from sevn.config.workspace_config import OpenUIWorkspaceConfig

    cfg = OpenUIWorkspaceConfig(rasteriser="weasyprint")
    assert cfg.rasteriser == "weasyprint"


def test_openui_rasteriser_playwright_is_unknown_enum_not_reserved() -> None:
    """DP7: ``playwright`` is an unknown enum value — not a reserved-but-erroring backend."""
    from sevn.config.workspace_config import OpenUIWorkspaceConfig

    with pytest.raises((ValidationError, ValueError)) as exc_info:
        OpenUIWorkspaceConfig(rasteriser="playwright")  # type: ignore[arg-type]
    msg = str(exc_info.value).lower()
    assert "reserved" not in msg
    assert "playwright" in msg or "literal" in msg or "enum" in msg or "input" in msg


def test_openui_models_rasteriser_name_excludes_playwright() -> None:
    """DP7: ui.openui.models.RasteriserName no longer includes playwright."""
    from sevn.ui.openui import models as openui_models

    args = get_args(openui_models.RasteriserName)
    assert args == ("weasyprint",)
    assert "playwright" not in args


def test_sevn_schema_rasteriser_enum_weasyprint_only() -> None:
    """DP7: infra/sevn.schema.json openui.rasteriser enum is weasyprint-only."""
    schema_path = Path(__file__).resolve().parents[2] / "infra" / "sevn.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    # Walk to openui.properties.rasteriser (structure may nest under $defs / properties).
    found: list[str] | None = None

    def _walk(node: object) -> None:
        nonlocal found
        if found is not None or not isinstance(node, dict):
            return
        raster = node.get("rasteriser")
        if isinstance(raster, dict) and "enum" in raster:
            found = list(raster["enum"])
            return
        for value in node.values():
            _walk(value)

    _walk(schema)
    assert found is not None, "rasteriser enum not found in sevn.schema.json"
    assert found == ["weasyprint"]
