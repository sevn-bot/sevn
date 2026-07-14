"""Deterministic list-skills/tools capability replies."""

from __future__ import annotations

from sevn.agent.capability_reply import (
    compose_list_skills_reply,
    compose_list_tools_reply,
    is_list_skills_message,
    is_list_tools_message,
)
from sevn.tools.base import ToolDefinition


def test_list_skills_message_detection() -> None:
    assert is_list_skills_message("list your skills")
    assert is_list_skills_message("what skills do you have?")
    assert not is_list_skills_message("list skills in source_code")


def test_list_tools_message_detection() -> None:
    assert is_list_tools_message("list your tools")
    assert is_list_tools_message("what tools do you have?")
    assert not is_list_tools_message("list tools for pdf")


def test_compose_list_skills_reply_includes_inventory_counts() -> None:
    body = compose_list_skills_reply(
        {"pdf": "Render PDFs", "lcm": "Session recall"},
        skill_inventory={
            "pdf": {"scripts": ["scripts/render.py"], "runnables": []},
        },
    )
    assert "2 skills" in body
    assert "**pdf**" in body
    assert "1 script" in body
    assert "load_skill" in body


def test_compose_list_skills_reply_prefers_full_inventory_summary() -> None:
    # skill_descriptions carries the ~80-char clipped Triager index line; the reply
    # must surface the untruncated manifest description from the inventory summary.
    clipped = "browser-harness — Thin CDP harness with extendable helpers.py for open-ended br…"
    full = "Thin CDP harness with extendable helpers.py for open-ended browser automation flows."
    body = compose_list_skills_reply(
        {"browser-harness": clipped},
        skill_inventory={
            "browser-harness": {"summary": full, "scripts": ["a.py"], "runnables": []},
        },
    )
    assert full in body
    assert "…" not in body
    assert "1 script" in body


def test_compose_list_skills_reply_falls_back_when_no_inventory_summary() -> None:
    # Without an inventory summary (e.g. mgr is None), keep the description as given.
    body = compose_list_skills_reply({"pdf": "Render PDFs"})
    assert "Render PDFs" in body


def test_howto_messages_do_not_match_tier_a_regex() -> None:
    assert not is_list_skills_message("how does listregistry work?")
    assert not is_list_tools_message("how does list_registry work?")
    assert not is_list_skills_message("do you have a pdf skill?")


def test_compose_list_tools_reply_excludes_meta_tools() -> None:
    body = compose_list_tools_reply(
        [
            ToolDefinition(
                name="read",
                category="file",
                description="Read a file",
                parameters={},
            ),
            ToolDefinition(
                name="list_registry",
                category="meta",
                description="List registry",
                parameters={},
            ),
        ],
    )
    assert "read" in body
    assert "list_registry" not in body
