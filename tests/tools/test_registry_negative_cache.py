"""Tests for the per-turn negative cache + ``did_you_mean`` injection (PROBLEMS.md §Priority 1.f, 1.h)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sevn.tools.base import ToolCall
from sevn.tools.context import ToolContext
from sevn.tools.registry import (
    _did_you_mean_for_load_skill,
    _did_you_mean_for_load_tool,
    _did_you_mean_for_read,
    _did_you_mean_for_run_skill_script,
    _inject_did_you_mean,
    _is_cacheable_failure,
    _stable_args_key,
)


def _ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(
        session_id="s",
        workspace_path=tmp_path,
        workspace_id="w",
        registry_version=1,
    )


def test_stable_args_key_is_deterministic() -> None:
    assert _stable_args_key({"b": 2, "a": 1}) == _stable_args_key({"a": 1, "b": 2})


def test_stable_args_key_distinguishes_callsites() -> None:
    assert _stable_args_key({"path": "a"}) != _stable_args_key({"path": "b"})


def test_inject_did_you_mean_passthrough_on_success(tmp_path: Path) -> None:
    raw = '{"ok":true,"data":{"x":1}}'
    call = ToolCall(name="read", arguments={"path": "x"})
    assert _inject_did_you_mean(_ctx(tmp_path), call, raw) == raw


def test_inject_did_you_mean_passthrough_when_tool_already_provided(tmp_path: Path) -> None:
    raw = '{"ok":false,"error":"not found: a","did_you_mean":["b"]}'
    call = ToolCall(name="read", arguments={"path": "a"})
    assert _inject_did_you_mean(_ctx(tmp_path), call, raw) == raw


def test_inject_did_you_mean_passthrough_on_invalid_json(tmp_path: Path) -> None:
    raw = "not-json"
    call = ToolCall(name="read", arguments={"path": "x"})
    assert _inject_did_you_mean(_ctx(tmp_path), call, raw) == raw


def test_did_you_mean_for_read_suggests_sibling_in_source_code_mirror(
    tmp_path: Path,
) -> None:
    """A typo'd path under ``source_code/`` resolves to its real sibling."""
    ws = tmp_path / "ws"
    gateway = ws / "source_code" / "src" / "sevn" / "gateway"
    gateway.mkdir(parents=True)
    (gateway / "agent_turn.py").write_text("x", encoding="utf-8")
    ctx = _ctx(ws)
    out = _did_you_mean_for_read(ctx, {"path": "source_code/src/sevn/gateway/agent_trn.py"})
    assert any("agent_turn.py" in s for s in out)


def test_did_you_mean_for_read_suggests_sibling_via_fuzzy_match(tmp_path: Path) -> None:
    """List parent-dir entries close to the requested filename."""
    ws = tmp_path / "ws"
    (ws / "skills").mkdir(parents=True)
    (ws / "skills" / "INDEX.md").write_text("x", encoding="utf-8")
    ctx = _ctx(ws)
    out = _did_you_mean_for_read(ctx, {"path": "skills/INDX.md"})
    assert any("INDEX.md" in s for s in out)


def test_did_you_mean_for_read_strips_stale_workspace_prefix(tmp_path: Path) -> None:
    """A ``workspace/<X>`` miss suggests the bare ``<X>`` when it exists.

    Regression for ``plan/minimax-m3-session-bugs-plan.md`` P2: workspace/user
    files resolve as bare paths at the root, so the model's guessed
    ``workspace/IDENTITY.md`` should point back at bare ``IDENTITY.md``.
    """
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)
    (ws / "IDENTITY.md").write_text("x", encoding="utf-8")
    ctx = _ctx(ws)
    out = _did_you_mean_for_read(ctx, {"path": "workspace/IDENTITY.md"})
    assert "IDENTITY.md" in out


def test_did_you_mean_for_read_empty_when_no_clue(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    out = _did_you_mean_for_read(ctx, {"path": "absolutely/nothing/like/this.md"})
    assert out == []


def test_did_you_mean_for_load_skill_matches_against_index() -> None:
    """The shipped skills/INDEX.md is the candidate pool — typos resolve."""
    out = _did_you_mean_for_load_skill({"name": "graphfy"})  # missing 'i'
    assert "graphify" in out


def test_did_you_mean_for_load_skill_empty_when_no_match() -> None:
    assert _did_you_mean_for_load_skill({"name": "z" * 50}) == []


def test_did_you_mean_for_load_tool_matches_against_known_names(tmp_path: Path) -> None:
    """``load_tool`` suggestions come from the ctx's registered tool snapshot."""
    ctx = ToolContext(
        session_id="s",
        workspace_path=tmp_path,
        workspace_id="w",
        registry_version=1,
        known_tool_names=frozenset({"search_code", "search_in_file", "read"}),
    )
    out = _did_you_mean_for_load_tool(ctx, {"name": "search"})
    assert "search_code" in out
    assert "search_in_file" in out


def test_did_you_mean_for_load_tool_empty_when_snapshot_unpopulated(tmp_path: Path) -> None:
    """No registry snapshot → no guesses (don't fabricate)."""
    ctx = ToolContext(
        session_id="s",
        workspace_path=tmp_path,
        workspace_id="w",
        registry_version=1,
    )
    assert _did_you_mean_for_load_tool(ctx, {"name": "search"}) == []


def test_did_you_mean_for_run_skill_script_unknown_never_echoed(tmp_path: Path) -> None:
    """Unknown script → fuzzy match declared paths, not the bogus input."""
    ctx = _ctx(tmp_path)
    suggestions = _did_you_mean_for_run_skill_script(
        ctx,
        {"skill": "scheduling", "script": "cron_status"},
    )
    assert "scripts/cron_list.py" in suggestions
    assert any(s == "skills/core/scheduling/scripts/cron_list.py" for s in suggestions)
    assert "scripts/cron_status" not in suggestions
    assert "scripts/cron_status.py" not in suggestions


def test_did_you_mean_for_read_suggests_core_skill_source_path(tmp_path: Path) -> None:
    """A ``skills/<name>/…`` miss points at the seeded ``skills/core/<name>/…`` tree."""
    ws = tmp_path / "ws"
    script = ws / "skills" / "core" / "pdf" / "scripts" / "pdf.py"
    script.parent.mkdir(parents=True)
    script.write_text("# pdf", encoding="utf-8")
    ctx = _ctx(ws)
    out = _did_you_mean_for_read(ctx, {"path": "skills/pdf/scripts/pdf.py"})
    assert "skills/core/pdf/scripts/pdf.py" in out


def test_did_you_mean_for_run_skill_script_empty_without_skill(tmp_path: Path) -> None:
    """Missing skill/script fields → no suggestions."""
    ctx = _ctx(tmp_path)
    assert _did_you_mean_for_run_skill_script(ctx, {"script": "cron_list.py"}) == []
    assert _did_you_mean_for_run_skill_script(ctx, {"skill": "scheduling"}) == []


def test_did_you_mean_envelope_round_trip_for_read(tmp_path: Path) -> None:
    """End-to-end: failure envelope gets a ``did_you_mean`` list when relevant."""
    ws = tmp_path / "ws"
    (ws / "skills").mkdir(parents=True)
    (ws / "skills" / "INDEX.md").write_text("x", encoding="utf-8")
    ctx = _ctx(ws)
    call = ToolCall(name="read", arguments={"path": "skills/INDX.md"})
    raw = '{"ok":false,"error":"not found: skills/INDX.md","code":"VALIDATION_ERROR"}'
    out = _inject_did_you_mean(ctx, call, raw)
    blob = json.loads(out)
    assert blob["ok"] is False
    assert isinstance(blob.get("did_you_mean"), list)
    assert blob["did_you_mean"]


def test_negative_cache_field_is_independent_per_context(tmp_path: Path) -> None:
    """Each ToolContext gets its own cache — no cross-turn contamination."""
    a = _ctx(tmp_path)
    b = _ctx(tmp_path)
    a.negative_cache[("read", '{"path": "x"}')] = "cached"
    assert b.negative_cache == {}


@pytest.mark.parametrize("name", ["read", "load_skill", "load_tool", "run_skill_script"])
def test_inject_did_you_mean_handles_known_tool_names_without_raising(
    tmp_path: Path, name: str
) -> None:
    """Smoke: even tools without a matcher yet should pass through cleanly."""
    raw = '{"ok":false,"error":"x"}'
    call = ToolCall(name=name, arguments={"path": "x", "name": "x"})
    out = _inject_did_you_mean(_ctx(tmp_path), call, raw)
    json.loads(out)  # must remain valid JSON


@pytest.mark.parametrize(
    ("raw", "cacheable"),
    [
        ('{"ok":false,"code":"VALIDATION_ERROR","error":"not found"}', True),
        ('{"ok":false,"code":"UNKNOWN_TOOL","error":"missing"}', True),
        ('{"ok":false,"code":"PLAN_HUMAN_GATE","error":"ack"}', False),
        ('{"ok":false,"code":"MCP_UNAVAILABLE","error":"x"}', False),
        ('{"ok":false,"code":"PROVIDER_TIMEOUT","error":"x"}', False),
        ('{"ok":false,"error":"no code"}', False),
        ('{"ok":true}', False),
        ("not-json", False),
    ],
)
def test_is_cacheable_failure(raw: str, cacheable: bool) -> None:
    """Only deterministic structural failures are cached — gating + transport flip."""
    assert _is_cacheable_failure(raw) is cacheable


def test_run_skill_script_validation_error_not_negative_cached() -> None:
    """Skill execution failures must not replay from the per-turn negative cache."""
    raw = '{"ok":false,"code":"VALIDATION_ERROR","error":"pdf: path escapes workspace root"}'
    assert _is_cacheable_failure(raw, tool_name="run_skill_script") is False
    assert _is_cacheable_failure(raw, tool_name="run_skill_runnable") is False
    assert _is_cacheable_failure(raw, tool_name="read") is True
