"""Batch F W27 RED: Reddit karma loop draft-only enforcement (#74, D11) → W33."""

from __future__ import annotations

from pathlib import Path

import pytest


def test_reddit_karma_skill_manifest_exists() -> None:
    """Bundled skill layout includes reddit-karma-loop with SKILL.md."""
    skill_root = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "sevn"
        / "data"
        / "bundled_skills"
        / "core"
        / "reddit-karma-loop"
    )
    assert skill_root.is_dir()
    assert (skill_root / "SKILL.md").is_file()


def test_reddit_post_action_returns_confirm_required_without_approval() -> None:
    """Reddit skill cannot post without explicit operator confirmation (D11)."""
    from sevn.data.bundled_skills.core.reddit_karma_loop.scripts._reddit_runtime import (
        require_reddit_post_confirm,
    )

    class _Args:
        confirm = False
        dry_run = False

    preview = require_reddit_post_confirm(
        _Args(),
        would_do={"action": "post_comment", "subreddit": "test", "body": "hello"},
    )
    assert preview is not None
    assert preview["error"]["code"] == "CONFIRM_REQUIRED"


def test_reddit_auto_post_mode_is_not_available() -> None:
    """``auto_post`` must not be implemented in this wave (D11 draft-only)."""
    from sevn.data.bundled_skills.core.reddit_karma_loop.scripts._reddit_runtime import (
        reddit_post_modes,
    )

    modes = reddit_post_modes()
    assert "auto_post" not in modes
    assert "draft_only" in modes


@pytest.mark.parametrize(
    ("posts_today", "max_per_day", "expect_blocked"),
    [
        (0, 5, False),
        (5, 5, True),
        (10, 3, True),
    ],
)
def test_reddit_daily_post_cap_enforced(
    posts_today: int,
    max_per_day: int,
    expect_blocked: bool,
) -> None:
    """Per-day caps block additional Reddit actions once the limit is reached."""
    from sevn.data.bundled_skills.core.reddit_karma_loop.scripts._reddit_runtime import (
        enforce_reddit_rate_limits,
    )

    blocked, reason = enforce_reddit_rate_limits(
        posts_today=posts_today,
        max_posts_per_day=max_per_day,
        cooldown_seconds=0,
        seconds_since_last_post=999,
    )
    assert blocked is expect_blocked
    if expect_blocked:
        assert reason is not None
        assert "cap" in reason.lower()


def test_reddit_cooldown_enforced_between_posts() -> None:
    """Cooldown window blocks back-to-back Reddit actions."""
    from sevn.data.bundled_skills.core.reddit_karma_loop.scripts._reddit_runtime import (
        enforce_reddit_rate_limits,
    )

    blocked, reason = enforce_reddit_rate_limits(
        posts_today=0,
        max_posts_per_day=10,
        cooldown_seconds=3600,
        seconds_since_last_post=30,
    )
    assert blocked is True
    assert reason is not None
    assert "cooldown" in reason.lower()
