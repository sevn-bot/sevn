"""Telegram session mirror path names (#21; W1 contracts; green after W2/W3)."""

from __future__ import annotations

import importlib
import inspect
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from sevn.config.workspace_config import WorkspaceConfig
from sevn.gateway.session import session_mirror as session_mirror_mod
from sevn.gateway.session.session_mirror import (
    _parse_scope_key,
    _safe_segment,
    mirror_gateway_message,
)
from sevn.storage.migrate import apply_migrations


@dataclass
class StaticNameResolver:
    """Minimal name resolver stub for path-resolution contract tests."""

    chat_names: dict[str, str] = field(default_factory=dict)
    topic_names: dict[tuple[str, str], str] = field(default_factory=dict)

    def get_chat_name(self, chat_id: str) -> str | None:
        return self.chat_names.get(chat_id)

    def get_topic_name(self, chat_id: str, topic_id: str) -> str | None:
        return self.topic_names.get((chat_id, topic_id))


def _format_named_path_segment(name: str | None, entity_id: str) -> str:
    fn = getattr(session_mirror_mod, "format_named_path_segment", None)
    assert fn is not None, "format_named_path_segment not implemented (green after W3)"
    return str(fn(name, entity_id))


def _parse_scope_path(
    scope_key: str,
    resolver: StaticNameResolver | None = None,
) -> tuple[str, dict[str, Any]]:
    sig = inspect.signature(_parse_scope_key)
    kwargs: dict[str, Any] = {}
    for param_name in ("name_resolver", "resolver", "conn"):
        if param_name in sig.parameters:
            if resolver is not None:
                kwargs[param_name] = resolver
            return _parse_scope_key(scope_key, **kwargs)
    if resolver is not None:
        pytest.fail("_parse_scope_key has no name resolver parameter (green after W3)")
    return _parse_scope_key(scope_key)


def _mirror_with_resolver(
    *,
    content_root: Path,
    workspace: WorkspaceConfig,
    session_id: str,
    scope_key: str,
    resolver: StaticNameResolver | None = None,
    message_id: int = 1,
) -> None:
    sig = inspect.signature(mirror_gateway_message)
    kwargs: dict[str, Any] = {
        "content_root": content_root,
        "workspace": workspace,
        "message_id": message_id,
        "session_id": session_id,
        "scope_key": scope_key,
        "channel": "telegram",
        "user_id": "42",
        "role": "user",
        "kind": "message",
        "content": "mirror line",
        "visible_to_llm": 1,
        "status": "sent",
        "created_at": "2026-07-15T12:00:00",
        "extras_json": None,
    }
    for param_name in ("name_resolver", "resolver", "conn"):
        if param_name in sig.parameters and resolver is not None:
            kwargs[param_name] = resolver
            break
    mirror_gateway_message(**kwargs)


@pytest.mark.parametrize(
    ("raw", "expected_slug"),
    [
        ("My Group", "My_Group"),
        ("General", "General"),
        ("  spaced  ", "spaced"),
        ("", "unknown"),
        ("   ", "unknown"),
        ("Café ☕", "Café_"),
        ("file/name:test", "file_name_test"),
        ("dots.and-dashes", "dots.and-dashes"),
    ],
)
def test_safe_segment_sanitizes_titles(raw: str, expected_slug: str) -> None:
    """W1.0: ``_safe_segment`` produces filesystem-safe slug fragments."""
    assert _safe_segment(raw) == expected_slug


def test_safe_segment_whitespace_variants_collide() -> None:
    """W1.0: title variants can share a slug; uniqueness comes from ``--{id}`` suffix."""
    assert _safe_segment("My Group") == _safe_segment("My  Group") == "My_Group"


@pytest.mark.parametrize(
    ("name", "entity_id", "expected"),
    [
        ("My Group", "-1001234567890", "My_Group--1001234567890"),
        ("General", "7", "General--7"),
        (None, "-1001234567890", "-1001234567890"),
        ("", "7", "7"),
        ("   ", "42", "42"),
    ],
)
def test_format_named_path_segment_assembly(
    name: str | None,
    entity_id: str,
    expected: str,
) -> None:
    """W1.0: ``{slug}--{id}`` assembly with D2 missing-name ID-only fallback."""
    assert _format_named_path_segment(name, entity_id) == expected


def test_topic_scope_path_uses_group_and_topic_names() -> None:
    """W1.1: forum topic scope resolves enriched chat + topic folder segments."""
    scope = "telegram:-1001234567890:topic:7"
    resolver = StaticNameResolver(
        chat_names={"-1001234567890": "My Group"},
        topic_names={("-1001234567890", "7"): "General"},
    )
    rel, extras = _parse_scope_path(scope, resolver)
    assert rel == "telegram/chats/My_Group--1001234567890/topics/General--7"
    assert extras["chat_id"] == "-1001234567890"
    assert extras["topic_id"] == "7"


def test_topic_scope_path_falls_back_when_names_missing() -> None:
    """W1.2: resolver returns ``None`` → ID-only segments (backward compatible)."""
    scope = "telegram:-1001234567890:topic:7"
    resolver = StaticNameResolver()
    rel, extras = _parse_scope_path(scope, resolver)
    assert rel == "telegram/chats/-1001234567890/topics/7"
    assert extras["chat_id"] == "-1001234567890"
    assert extras["topic_id"] == "7"


def test_general_group_scope_path_uses_group_name() -> None:
    """W1.3: non-topic group scope → ``…/general/`` under enriched chat folder."""
    scope = "telegram:-1001234567890:general"
    resolver = StaticNameResolver(chat_names={"-1001234567890": "Ops Team"})
    rel, extras = _parse_scope_path(scope, resolver)
    assert rel == "telegram/chats/Ops_Team--1001234567890/general"
    assert extras["chat_id"] == "-1001234567890"
    assert extras.get("topic_id") is None


def test_private_chat_scope_skips_name_enrichment_even_with_resolver() -> None:
    """D7: positive ``chat_id`` (DM) stays ID-only despite resolver names."""
    scope = "telegram:99:general"
    resolver = StaticNameResolver(chat_names={"99": "Should Not Appear"})
    rel, _extras = _parse_scope_path(scope, resolver)
    assert rel == "telegram/chats/99/general"


def test_index_jsonl_rel_matches_enriched_mirror_folder(tmp_path: Path) -> None:
    """W1.5: ``_index.json`` ``jsonl`` rel path matches enriched on-disk folder."""
    content_root = tmp_path / "ws"
    content_root.mkdir()
    ws = WorkspaceConfig(
        schema_version=1,
        gateway={
            "session_mirror": {"enabled": True},
            "token": "${SECRET:keychain:sevn.gateway.token}",
        },
    )
    scope = "telegram:-1001234567890:topic:7"
    session_id = "sess-enriched-index"
    resolver = StaticNameResolver(
        chat_names={"-1001234567890": "My Group"},
        topic_names={("-1001234567890", "7"): "General"},
    )
    _mirror_with_resolver(
        content_root=content_root,
        workspace=ws,
        session_id=session_id,
        scope_key=scope,
        resolver=resolver,
    )
    rel, _ = _parse_scope_path(scope, resolver)
    jsonl_path = content_root / "sessions" / rel / f"{_safe_segment(session_id)}.jsonl"
    assert jsonl_path.is_file()
    index = json.loads((content_root / "sessions" / "_index.json").read_text(encoding="utf-8"))
    entry = index["sessions"][session_id]
    assert entry["jsonl"] == str(jsonl_path.relative_to(content_root / "sessions"))


def test_parse_scope_key_baseline_id_only_topic_path() -> None:
    """Baseline (pre-W3): current ID-only topic path still parses."""
    rel, extras = _parse_scope_key("telegram:-1001234567890:topic:7")
    assert rel == "telegram/chats/-1001234567890/topics/7"
    assert extras["topic_id"] == "7"


def test_db_chat_name_lookup_helper_returns_none_when_missing() -> None:
    """W2 contract: ``get_telegram_chat_name`` exists and returns ``None`` when unknown."""
    fn = None
    for module_name in ("sevn.storage.telegram_names", "sevn.gateway.session.path_names"):
        try:
            mod = importlib.import_module(module_name)
        except ModuleNotFoundError:
            continue
        fn = getattr(mod, "get_telegram_chat_name", None)
        if fn is not None:
            break
    assert fn is not None, "get_telegram_chat_name not implemented (green after W2)"
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    assert fn(conn, -100) is None
