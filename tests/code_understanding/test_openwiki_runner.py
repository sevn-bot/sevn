"""Unit tests for ``sevn.code_understanding.openwiki_runner``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sevn.code_understanding.openwiki_runner import (
    build_openwiki_argv,
    content_root_from_env,
    looks_like_credentials_error,
    openwiki_status,
    resolve_openwiki_root,
)


def test_build_openwiki_argv_init_print() -> None:
    """Init mode includes ``--init`` and ``-p``."""
    assert build_openwiki_argv(mode="init", message=None, model_id=None) == [
        "openwiki",
        "--init",
        "-p",
    ]


def test_build_openwiki_argv_update_with_message() -> None:
    """Update mode appends a trimmed message after flags."""
    argv = build_openwiki_argv(mode="update", message="  refresh api docs  ", model_id=None)
    assert argv == ["openwiki", "--update", "-p", "refresh api docs"]


def test_build_openwiki_argv_chat_with_model_id() -> None:
    """Chat mode supports model override before the message."""
    argv = build_openwiki_argv(mode="chat", message="summarize", model_id="gpt-5.5")
    assert argv == ["openwiki", "-p", "--model-id", "gpt-5.5", "summarize"]


def test_build_openwiki_argv_rejects_blank_model_id() -> None:
    """Blank model ids raise ``ValueError``."""
    with pytest.raises(ValueError, match="model_id"):
        build_openwiki_argv(mode="chat", message=None, model_id="   ")


def test_resolve_openwiki_root_prefers_source_code_mirror(tmp_path: Path) -> None:
    """When ``source_code/`` exists, it becomes the OpenWiki repo root."""
    mirror = tmp_path / "source_code"
    mirror.mkdir()
    assert resolve_openwiki_root(tmp_path) == mirror.resolve()


def test_resolve_openwiki_root_falls_back_to_workspace(tmp_path: Path) -> None:
    """Without a mirror, the workspace root is used."""
    assert resolve_openwiki_root(tmp_path) == tmp_path.resolve()


def test_openwiki_status_absent_wiki(tmp_path: Path) -> None:
    """Status reports ``exists=False`` when no wiki directory is present."""
    status = openwiki_status(tmp_path)
    assert status["exists"] is False
    assert status["wiki_dir"].endswith("/openwiki")


def test_openwiki_status_with_metadata_and_pages(tmp_path: Path) -> None:
    """Status reads last-update metadata and counts markdown pages."""
    wiki = tmp_path / "openwiki"
    wiki.mkdir()
    (wiki / "intro.md").write_text("# Intro\n", encoding="utf-8")
    meta = {"updated_at": "2026-07-05T12:00:00Z"}
    (wiki / ".last-update.json").write_text(json.dumps(meta), encoding="utf-8")
    status = openwiki_status(tmp_path)
    assert status["exists"] is True
    assert status["page_count"] == 1
    assert status["last_update"] == meta


def test_looks_like_credentials_error() -> None:
    """Credential heuristics match common auth failure strings."""
    assert looks_like_credentials_error("Missing API key for provider")
    assert not looks_like_credentials_error("ENOENT: no such file")


def test_content_root_from_env_prefers_content_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``SEVN_CONTENT_ROOT`` wins over shadow ``SEVN_WORKSPACE``."""
    content = tmp_path / "content"
    shadow = tmp_path / "shadow"
    content.mkdir()
    shadow.mkdir()
    monkeypatch.setenv("SEVN_CONTENT_ROOT", str(content))
    monkeypatch.setenv("SEVN_WORKSPACE", str(shadow))
    assert content_root_from_env() == content.resolve()
