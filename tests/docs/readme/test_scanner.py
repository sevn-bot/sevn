"""Tests for README repo scanner."""

from __future__ import annotations

from pathlib import Path

import pytest

from sevn.docs.readme.fingerprint import expand_source_globs
from sevn.docs.readme.manifest import get_entry, load_manifest
from sevn.docs.readme.scanner import _read_sevn_json, scan_repo_context

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_scan_gateway_includes_package_and_source_files() -> None:
    """Gateway scan surfaces pyproject metadata and gateway Python files."""
    manifest = load_manifest(REPO_ROOT / "docs/readmes/manifest.toml")
    entry = get_entry(manifest, "gateway")
    if not any(p.suffix == ".py" for p in expand_source_globs(REPO_ROOT, entry.source_globs)):
        pytest.skip("src/sevn/gateway is not git-tracked in this checkout")
    ctx = scan_repo_context(REPO_ROOT, entry)
    assert ctx["slug"] == "gateway"
    assert ctx["package"]["name"] == "sevn"
    assert any(p.endswith(".py") for p in ctx["source_py_files"])
    assert ctx["source_dir"].startswith("src/sevn/gateway")


def test_scan_specs_index_lists_markdown_specs() -> None:
    """Scanner collects specs/*.md paths when present."""
    if not (REPO_ROOT / "specs").is_dir():
        pytest.skip("specs/ is gitignored and absent in CI checkout")
    manifest = load_manifest(REPO_ROOT / "docs/readmes/manifest.toml")
    entry = get_entry(manifest, "gateway")
    ctx = scan_repo_context(REPO_ROOT, entry)
    assert any(path.startswith("specs/") and path.endswith(".md") for path in ctx["specs_index"])


def test_scanner_logs_on_malformed_sevn_json(tmp_path: Path) -> None:
    """Malformed sevn.json returns None and emits a warning."""
    from loguru import logger

    (tmp_path / "sevn.json").write_text("{invalid json", encoding="utf-8")

    messages: list[str] = []
    sink_id = logger.add(messages.append, level="WARNING")
    try:
        result = _read_sevn_json(tmp_path)
    finally:
        logger.remove(sink_id)

    assert result is None
    assert any("readme_scanner" in m and "sevn.json" in m for m in messages)
