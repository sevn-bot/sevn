"""Batch A W1.6 — ``/config add @botname`` routes to config handler, not slash skill (#134, D12).

Telegram attaches the bot username to slash commands (``/config@MyBot add …``). The
slash-skill parser must not treat ``config@MyBot`` as a skill id; ``@botname`` stays in
the arg tail for the config handler (W6).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from sevn.gateway.channel_router import IncomingMessage
from sevn.gateway.commands.core_commands import CoreCommandHandler
from sevn.gateway.menu.menu import ConfigMenuHandler
from tests.gateway.test_config_menu_actions import _build_router

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True)
class _SlashMentionCase:
    """One Telegram-style ``/config@bot`` inbound line."""

    text: str
    bot_suffix: str
    args_tail: str


def _parse_stacked_slash_skills(text: str) -> object:
    from sevn.gateway.slash_skills import parse_stacked_slash_skills

    return parse_stacked_slash_skills(
        text,
        known_skill_ids=frozenset({"research", "writing"}),
    )


def _core_matches_slash(text: str) -> bool:
    handler = CoreCommandHandler.__new__(CoreCommandHandler)
    handler._content_root = __import__("pathlib").Path("/tmp")
    return handler.matches_slash(
        IncomingMessage(channel="telegram", user_id="u1", text=text),
    )


def _config_menu_matches_slash(text: str) -> bool:
    handler = ConfigMenuHandler.__new__(ConfigMenuHandler)
    return handler.matches_slash(
        IncomingMessage(channel="telegram", user_id="u1", text=text),
    )


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            _SlashMentionCase(
                text="/config@alexstestee_bot add channel:telegram",
                bot_suffix="alexstestee_bot",
                args_tail="add channel:telegram",
            ),
            id="telegram_command_entity_add_channel",
        ),
        pytest.param(
            _SlashMentionCase(
                text="/config@MyBot add @someuser",
                bot_suffix="MyBot",
                args_tail="add @someuser",
            ),
            id="add_with_user_mention_in_args",
        ),
        pytest.param(
            _SlashMentionCase(
                text="/config@sevn_bot add",
                bot_suffix="sevn_bot",
                args_tail="add",
            ),
            id="add_only_tail",
        ),
    ],
)
@pytest.mark.xfail(
    reason="green after W6: split /config from @bot suffix before slash-skill lookup", strict=False
)
def test_parse_stacked_slash_skills_defers_config_at_mention(case: _SlashMentionCase) -> None:
    """Parser must defer ``/config@bot`` to the core/config handler — never ``config@…`` skill error."""
    result = _parse_stacked_slash_skills(case.text)
    assert result.errors == (), f"unexpected parser errors: {result.errors!r}"
    assert result.deferred_to_core_handler is True
    assert result.skill_ids == ()


@pytest.mark.parametrize(
    "text",
    [
        "/config@alexstestee_bot add channel:telegram",
        "/config@MyBot add @someuser",
    ],
)
@pytest.mark.xfail(reason="green after W6: core handler recognizes /config@bot forms", strict=False)
def test_core_command_handler_matches_config_with_bot_suffix(text: str) -> None:
    """``CoreCommandHandler`` must claim Telegram ``/config@bot …`` before slash-skill dispatch."""
    assert _core_matches_slash(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "/config add @alexstestee_bot",
        "/config add channel:telegram",
    ],
)
def test_core_command_handler_matches_config_add_with_space_args(text: str) -> None:
    """Baseline: ``/config add …`` (space-separated) already routes through core handler."""
    assert _core_matches_slash(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "/config@alexstestee_bot add channel:telegram",
        "/config@MyBot add @someuser",
    ],
)
@pytest.mark.xfail(
    reason="green after W6: ConfigMenuHandler matches /config@bot slash variants", strict=False
)
def test_config_menu_handler_matches_slash_with_bot_suffix(text: str) -> None:
    """``ConfigMenuHandler`` opens the menu for ``/config@bot …`` lines."""
    assert _config_menu_matches_slash(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "/config add @alexstestee_bot",
        "/config add channel:telegram",
    ],
)
def test_config_menu_handler_matches_slash_add_with_space_args(text: str) -> None:
    """Baseline: ``/config add …`` (space-separated) already matches config menu handler."""
    assert _config_menu_matches_slash(text) is True


@pytest.mark.xfail(
    reason="green after W6: forbid unknown slash skill config@… on config add lines", strict=False
)
def test_parse_stacked_slash_skills_does_not_emit_config_at_skill_error() -> None:
    """Regression guard: forbid ``unknown slash skill `config@…``` on config add lines."""
    text = "/config@alexstestee_bot add channel:telegram"
    result = _parse_stacked_slash_skills(text)
    joined = " ".join(result.errors).lower()
    assert "config@" not in joined, (
        f"slash parser must not treat @ suffix as skill name: {result.errors!r}"
    )


@pytest.mark.asyncio
@pytest.mark.xfail(
    reason="green after W6: gateway routes /config@bot add to config menu, not slash-skill error",
    strict=False,
)
async def test_route_incoming_config_at_bot_opens_config_menu_not_slash_skill_error(
    tmp_path: Path,
) -> None:
    """End-to-end: ``/config@bot add …`` opens ``/config`` menu — no unknown-slash-skill reply."""
    router, cap, _ws = _build_router(tmp_path)
    text = "/config@alexstestee_bot add channel:telegram"
    msg = IncomingMessage(
        channel="telegram",
        user_id="u1",
        text=text,
        metadata={"chat_id": 42, "message_id": 99},
    )
    await router.route_incoming(msg)
    outbound = [sent[0] for sent in cap.sent]
    assert outbound, "config add with @bot suffix must produce a user-visible gateway reply"
    combined = "\n".join(outbound).lower()
    assert "unknown slash skill" not in combined
    assert "config@" not in combined
    assert "/config" in combined or "sevn" in combined


@pytest.mark.asyncio
@pytest.mark.xfail(
    reason="green after W6: preserve @mention token in config add args after command split",
    strict=False,
)
async def test_route_incoming_config_add_preserves_at_mention_in_args(tmp_path: Path) -> None:
    """D12: ``@botname`` stays in the arg token after splitting command from Telegram suffix."""
    router, cap, _ws = _build_router(tmp_path)
    bot = "alexstestee_bot"
    text = f"/config@{bot} add @{bot}"
    msg = IncomingMessage(
        channel="telegram",
        user_id="u1",
        text=text,
        metadata={"chat_id": 42, "message_id": 99},
    )
    await router.route_incoming(msg)
    assert cap.sent or cap.edited, "config handler must respond"
    combined = "\n".join([sent[0] for sent in cap.sent]).lower()
    assert "unknown slash skill" not in combined
