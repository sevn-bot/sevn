"""Wave W4.1: tier-B always exposes ``log_query`` regardless of triager narrowing (D5)."""

from __future__ import annotations

from sevn.agent.adapters.pydantic_adapter import register_pydantic_tools
from sevn.agent.adapters.tier_b_tools import _ALWAYS_INVOKABLE_TIER_B
from sevn.tools.registry import build_session_registry


def test_register_pydantic_tools_always_includes_log_query() -> None:
    """``log_query`` is in the tier-B core set even when triage.tools omits it."""
    _executor, tool_set = build_session_registry(registry_version=5)
    triage = {"tools": ("glob",), "skills": ()}
    reg = register_pydantic_tools(tool_set, triage, add_core_tools=True)
    assert "log_query" in reg.tool_names


def test_register_pydantic_tools_always_includes_list_registry() -> None:
    """``list_registry`` is in the tier-B core set for self-listing (W4.5)."""
    _executor, tool_set = build_session_registry(registry_version=5)
    triage = {"tools": (), "skills": ()}
    reg = register_pydantic_tools(tool_set, triage, add_core_tools=True)
    assert "list_registry" in reg.tool_names


def test_always_invokable_tier_b_includes_log_query_and_list_registry() -> None:
    assert {"log_query", "list_registry"}.issubset(_ALWAYS_INVOKABLE_TIER_B)


def test_log_query_playbook_covers_operator_postmortem_phrases() -> None:
    from sevn.prompts.tier_b import tier_b_log_query_playbook_prompt

    body = tier_b_log_query_playbook_prompt()
    assert "what happened with my request" in body
    assert "why did you fail" in body
    assert "check the logs for" in body
    assert "msg=" in body
    assert "ERROR|WARNING" in body


def test_log_provenance_playbook_covers_audit_shape() -> None:
    from sevn.prompts.tier_b import (
        tier_b_log_provenance_playbook_prompt,
        tier_b_triager_bound_mandate_prompt,
    )

    body = tier_b_log_provenance_playbook_prompt()
    assert "provenance audit" in body.lower()
    assert "re-answer the prior" in body.lower()
    assert "successful_tools" in body
    assert "tools_attempted" in body
    assert "compound pattern" in body.lower() or "compound `pattern`" in body
    assert "load_tool" in body
    assert "this turn's" in body
    mandate = tier_b_triager_bound_mandate_prompt(
        ["log_query", "read_transcript"],
        [],
        log_provenance_audit=True,
    )
    assert "log_query" in mandate
    assert "read_transcript" in mandate


def test_bound_skill_playbook_playwright_capture_and_send_file() -> None:
    from sevn.prompts.tier_b import (
        tier_b_bound_skill_playbook_prompt,
        tier_b_triager_bound_mandate_prompt,
    )

    body = tier_b_bound_skill_playbook_prompt(["playwright-browser"])
    assert "Bound skill playbook" in body
    assert "load_skill" in body
    assert "run_skill_script" in body
    assert "scripts/capture.py" in body
    assert "send_file" in body
    assert "unavailable" in body.lower()
    mandate = tier_b_triager_bound_mandate_prompt([], ["playwright-browser"])
    assert "playwright-browser" in mandate
    assert "scripts/capture.py" in mandate
