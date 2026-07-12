"""Tests for context reference injection."""

from __future__ import annotations

from sevn.agent.context_refs import expand_context_refs
from sevn.gateway.openai_compat_api import build_openai_compat_router


def test_expand_context_refs_injects_file(tmp_path) -> None:
    (tmp_path / "note.md").write_text("hello world")
    out = expand_context_refs("read @note.md please", workspace_root=tmp_path)
    assert "hello world" in out


def test_openai_compat_router_models_route() -> None:
    routes = [r.path for r in build_openai_compat_router().routes]
    assert "/v1/models" in routes
    assert "/v1/chat/completions" in routes
