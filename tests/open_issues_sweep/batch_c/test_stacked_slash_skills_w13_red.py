"""W13.7 — stacked slash-skill parsing (→ W16, #87)."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from sevn.gateway.channel_router import IncomingMessage
from sevn.gateway.commands.core_commands import CoreCommandHandler


@dataclass(frozen=True)
class _SlashCase:
    """One parametrized stacked-slash expectation."""

    text: str
    expected_skill_ids: tuple[str, ...]
    expected_remainder: str
    known_skill_ids: frozenset[str]


def _parse_stacked_slash_skills(
    text: str,
    *,
    known_skill_ids: frozenset[str],
) -> object:
    """Call the W16 parser seam (lazy import)."""
    from sevn.gateway.slash_skills import parse_stacked_slash_skills

    return parse_stacked_slash_skills(text, known_skill_ids=known_skill_ids)


def _core_handler_matches_slash(text: str) -> bool:
    """Return whether ``CoreCommandHandler`` claims this slash command today."""
    handler = CoreCommandHandler.__new__(CoreCommandHandler)
    handler._content_root = __import__("pathlib").Path("/tmp")  # unused for core cmds
    return handler.matches_slash(
        IncomingMessage(channel="telegram", user_id="1", text=text),
    )


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            _SlashCase(
                text="/research summarize this",
                expected_skill_ids=("research",),
                expected_remainder="summarize this",
                known_skill_ids=frozenset({"research", "writing"}),
            ),
            id="single_skill_with_remainder",
        ),
        pytest.param(
            _SlashCase(
                text="/research /writing draft intro",
                expected_skill_ids=("research", "writing"),
                expected_remainder="draft intro",
                known_skill_ids=frozenset({"research", "writing"}),
            ),
            id="stacked_two_skills_ordered",
        ),
        pytest.param(
            _SlashCase(
                text="/research",
                expected_skill_ids=("research",),
                expected_remainder="",
                known_skill_ids=frozenset({"research"}),
            ),
            id="single_skill_only",
        ),
    ],
)
def test_stacked_slash_skill_parse_happy_paths(case: _SlashCase) -> None:
    """Single and stacked leading slash-skill tokens load in order with remainder text."""
    result = _parse_stacked_slash_skills(
        case.text,
        known_skill_ids=case.known_skill_ids,
    )
    assert result.skill_ids == case.expected_skill_ids
    assert result.remainder == case.expected_remainder
    assert result.errors == ()


def test_unknown_slash_skill_token_is_reported_not_prose() -> None:
    """Unknown slash tokens are reported explicitly — never silently treated as prose."""
    result = _parse_stacked_slash_skills(
        "/not-a-real-skill continue here",
        known_skill_ids=frozenset({"research"}),
    )
    assert result.skill_ids == ()
    assert "not-a-real-skill" in " ".join(result.errors).lower()
    assert result.remainder == "" or "continue here" not in result.remainder


def test_conflicting_stacked_skills_later_token_wins() -> None:
    """When stacked skills supply conflicting metadata, the later token wins deterministically."""
    result = _parse_stacked_slash_skills(
        "/alpha /beta user prompt",
        known_skill_ids=frozenset({"alpha", "beta"}),
    )
    assert result.skill_ids == ("alpha", "beta")
    assert result.conflict_resolution == "later_wins"
    assert result.effective_skill_id == "beta"
    assert result.remainder == "user prompt"


@pytest.mark.parametrize(
    "text",
    [
        "/help",
        "/status",
        "/model",
        "/new",
    ],
)
def test_core_slash_commands_still_match_core_handler(text: str) -> None:
    """Existing core slash dispatch still wins for built-in commands."""
    assert _core_handler_matches_slash(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "/help",
        "/status",
        "/model",
        "/new",
    ],
)
def test_parser_defers_core_slash_commands(text: str) -> None:
    """Stacked-slash parser must not treat core commands as skill tokens."""
    result = _parse_stacked_slash_skills(
        text,
        known_skill_ids=frozenset({"help", "status", "model", "new"}),
    )
    assert result.skill_ids == ()
    assert result.deferred_to_core_handler is True


def test_stacked_slash_skills_surface_loaded_metadata_in_order() -> None:
    """Ordered context load exposes which skills were loaded for the turn."""
    from sevn.gateway.slash_skills import build_slash_skill_turn_overlay

    overlay = build_slash_skill_turn_overlay(
        skill_ids=("research", "writing"),
        remainder="compare notes",
    )
    assert [row["skill_id"] for row in overlay["loaded_skills"]] == ["research", "writing"]
    assert overlay["user_prompt"] == "compare notes"
