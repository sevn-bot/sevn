"""Tests for Second Brain scope layout bootstrap."""

from __future__ import annotations

from pathlib import Path

from sevn.second_brain.bootstrap import ensure_second_brain_scope_layout


def test_bootstrap_creates_layout(tmp_path: Path) -> None:
    created = ensure_second_brain_scope_layout(tmp_path, copy_model=False)
    assert (tmp_path / "wiki" / "index.md").is_file()
    assert (tmp_path / "wiki" / "log.md").is_file()
    assert (tmp_path / "raw").is_dir()
    assert "wiki/index.md" in created


def test_bootstrap_idempotent(tmp_path: Path) -> None:
    ensure_second_brain_scope_layout(tmp_path, copy_model=False)
    index = tmp_path / "wiki" / "index.md"
    index.write_text("# Custom index\n", encoding="utf-8")
    created = ensure_second_brain_scope_layout(tmp_path, copy_model=False)
    assert index.read_text(encoding="utf-8") == "# Custom index\n"
    assert "wiki/index.md" not in created


def test_legacy_bootstrap_with_explicit_layout_key(tmp_path: Path) -> None:
    from sevn.config.workspace_config import parse_workspace_config

    cfg = parse_workspace_config(
        {
            "schema_version": 1,
            "gateway": {"token": "test-token-1234567890"},
            "second_brain": {"enabled": True, "layout": "legacy"},
        },
    )
    created = ensure_second_brain_scope_layout(tmp_path, cfg=cfg, copy_model=False)  # type: ignore[call-arg]
    assert (tmp_path / "wiki" / "index.md").is_file()
    assert (tmp_path / "raw").is_dir()
    assert "wiki/index.md" in created or "raw" in created
