"""W1 RED: ``sevn config`` CLI surface after eight-slug redesign (green after W6)."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from sevn.cli.app import app
from sevn.cli.config_paths import iter_config_sections, menu_registry_root_slugs

REDESIGN_ROOT_SLUGS: tuple[str, ...] = (
    "chat",
    "agent",
    "skills",
    "memory",
    "access",
    "health",
    "deployment",
    "help",
)


@pytest.mark.xfail(
    reason="green after W6: menu_registry_root_slugs returns eight slugs", strict=False
)
def test_menu_registry_root_slugs_returns_eight() -> None:
    """W1.10 — CLI SSOT derives eight root slugs from the redesigned registry."""
    slugs = menu_registry_root_slugs()
    assert slugs == REDESIGN_ROOT_SLUGS


@pytest.mark.xfail(
    reason="green after W6: iter_config_sections returns eight sections", strict=False
)
def test_iter_config_sections_returns_eight() -> None:
    """W1.10 — ``sevn config sections`` lists the eight menu groups."""
    sections = iter_config_sections()
    assert len(sections) == 8
    assert [s.slug for s in sections] == list(REDESIGN_ROOT_SLUGS)


@pytest.mark.xfail(
    reason="green after W6: sevn config sections CLI lists eight slugs", strict=False
)
def test_sevn_config_sections_lists_eight_slugs() -> None:
    """W1.10 — operator-facing ``sevn config sections`` matches the new tree."""
    runner = CliRunner()
    result = runner.invoke(app, ["config", "sections"], env={"NO_COLOR": "1"})
    assert result.exit_code == 0
    for slug in REDESIGN_ROOT_SLUGS:
        assert slug in result.stdout


@pytest.mark.xfail(reason="green after W6: sevn config sections --json payload", strict=False)
def test_sevn_config_sections_json_lists_eight() -> None:
    """W1.10 — JSON sections payload carries eight redesigned groups."""
    runner = CliRunner()
    result = runner.invoke(app, ["config", "sections", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert len(payload["data"]["sections"]) == 8


@pytest.mark.parametrize("slug", REDESIGN_ROOT_SLUGS)
@pytest.mark.xfail(
    reason="green after W6: sevn config <slug> accepts redesigned slugs", strict=False
)
def test_sevn_config_section_slug_accepted(slug: str) -> None:
    """W1.10 — each redesigned slug is a valid ``sevn config`` target."""
    runner = CliRunner()
    result = runner.invoke(app, ["config", slug, "--json"], env={"NO_COLOR": "1"})
    assert result.exit_code == 0


@pytest.mark.xfail(reason="green after W6: config_paths doctest len(slugs)==8", strict=False)
def test_config_paths_doctest_slug_count() -> None:
    """W1.10 — doctest anchor moves from 19 → 8 root slugs."""
    import doctest

    import sevn.cli.config_paths as config_paths

    failures, _attempts = doctest.testmod(config_paths, verbose=False)
    assert failures == 0
