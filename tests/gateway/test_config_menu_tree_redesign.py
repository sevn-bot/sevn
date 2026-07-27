"""W1 RED: redesigned /config root tree constraints (green after W3)."""

from __future__ import annotations

import pytest

from sevn.gateway.menu.menu import build_config_menu_keyboard
from tests.gateway.telegram_menu_redesign_helpers import (
    DEFAULT_DOCS_WORKSPACE,
    REDESIGN_MAX_ROWS_PER_SCREEN,
    REDESIGN_NON_OWNER_ROOT_SLUGS,
    REDESIGN_OWNER_ROOT_TILES,
    count_rows_for_section,
    current_root_tile_count,
    root_section_tile_callbacks,
)


def test_owner_root_renders_eight_tiles_in_order() -> None:
    """W1.5 — owner sees eight intent tiles in redesign order."""
    callbacks = root_section_tile_callbacks(is_owner=True)
    expected = [f"cfg:section:{slug}" for _label, slug, _owner in REDESIGN_OWNER_ROOT_TILES]
    assert callbacks == expected


def test_non_owner_root_renders_four_tiles() -> None:
    """W1.5 — paired non-owner users see Chat, Agent, Skills & Tools, Help only."""
    callbacks = root_section_tile_callbacks(is_owner=False)
    expected = [f"cfg:section:{slug}" for slug in REDESIGN_NON_OWNER_ROOT_SLUGS]
    assert callbacks == expected
    assert current_root_tile_count(is_owner=False) == 4


@pytest.mark.parametrize("section", ["chat", "agent", "skills", "memory", "access", "health"])
def test_redesign_sections_respect_max_row_width(section: str) -> None:
    """W1.5 — no redesigned section exceeds 14 inline keyboard rows."""
    assert count_rows_for_section(section) <= REDESIGN_MAX_ROWS_PER_SCREEN


@pytest.mark.parametrize(
    ("nav_callback", "target_section"),
    [
        ("cfg:section:chat", "chat"),
        ("cfg:section:agent", "agent"),
        ("cfg:section:skills", "skills"),
        ("cfg:section:memory", "memory"),
    ],
)
def test_nav_to_targets_resolve(nav_callback: str, target_section: str) -> None:
    """W1.5 — every redesign nav ``to:`` target maps to a renderable section."""
    _ = nav_callback
    kb = build_config_menu_keyboard(DEFAULT_DOCS_WORKSPACE, section=target_section)  # type: ignore[arg-type]
    assert kb.get("inline_keyboard")


def test_redesign_leaf_depth_within_three_taps() -> None:
    """W1.5 — leaves are ≤3 taps from root except Discogs setup + sub-agents running."""
    from sevn.browser.recipes.telegram_menu import max_leaf_depth_from_root

    depths = max_leaf_depth_from_root()
    for section_id, depth in depths.items():
        if section_id in {"skills:discogs:setup", "subagents_running"}:
            continue
        assert depth <= 3, f"{section_id} depth {depth}"
