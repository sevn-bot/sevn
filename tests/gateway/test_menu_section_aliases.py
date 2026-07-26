"""W1 RED: permanent section-id aliases for stale callbacks (green after W6)."""

from __future__ import annotations

import pytest

from tests.gateway.telegram_menu_redesign_helpers import RETIRED_SECTION_ALIASES


@pytest.mark.parametrize(
    ("retired_id", "expected_target"),
    sorted(RETIRED_SECTION_ALIASES.items()),
)
def test_retired_section_alias_resolves(retired_id: str, expected_target: str) -> None:
    """W1.9 / D14 — stale ``cfg:section:{retired}`` callbacks never 500."""
    from sevn.gateway.menu.menu import resolve_config_section_alias

    resolved = resolve_config_section_alias(retired_id)
    if expected_target:
        assert resolved == expected_target
    else:
        assert resolved in {"", None} or "moved" in str(resolved).lower()


@pytest.mark.parametrize("unknown_id", ["not-a-section", "legacy_tile", ""])
def test_unknown_section_id_never_raises(unknown_id: str) -> None:
    """W1.9 — unknown ids answer an explicit toast; dispatch must not raise."""
    from sevn.gateway.menu.menu import resolve_config_section_alias

    try:
        resolve_config_section_alias(unknown_id)
    except Exception as exc:
        pytest.fail(f"unknown section id raised: {exc!r}")
