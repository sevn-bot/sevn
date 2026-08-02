"""Shared policy for removed Playwright-era bundled browser skills (#117, #127, D6).

Consumed by ``scripts/check_removed_browser_skill_ids.py`` and
``tests/browser/test_browser_removal_parity.py`` so survivor allowlists and gate
needles stay in one place.

Exports:
    contains_forbidden_substring — word-boundary substring scan helper
"""

from __future__ import annotations

import re

REMOVED_SKILL_IDS: frozenset[str] = frozenset(
    {
        "playwright-browser",
        "x-use",
        "facebook-use",
        "linkedin-use",
    }
)

FORBIDDEN_SUBSTRINGS: tuple[str, ...] = (*tuple(sorted(REMOVED_SKILL_IDS)), "playwright_browser")

# Bundled paths that may cite removed ids only for operator migration guidance (#128).
MIGRATION_DOC_REL_PATHS: frozenset[str] = frozenset(
    {
        "src/sevn/data/bundled_skills/core/social_media_manager/SKILL.md",
    }
)


def contains_forbidden_substring(text: str, needle: str) -> bool:
    """Return True when *needle* appears as a standalone token in *text*.

    Hyphenated ids such as ``x-use`` must not match inside unrelated words
    (e.g. ``max-users``).

    Args:
        text (str): File or registry body to scan.
        needle (str): Forbidden skill id or legacy alias substring.

    Returns:
        bool: ``True`` when *needle* matches as a standalone token.

    Examples:
        >>> contains_forbidden_substring("see also x-use migration", "x-use")
        True
        >>> contains_forbidden_substring("configure max-users limit", "x-use")
        False
    """
    return re.search(rf"(?<![\w-]){re.escape(needle)}(?![\w-])", text) is not None


# Repo-wide ``playwright`` driver grep survivors — artifacts that document removal.
BROWSER_REMOVAL_PARITY_SURVIVOR_PREFIXES: tuple[str, ...] = (
    "CHANGELOG.md:",
    "about-sevn.bot/specs/11-tools-registry.md:",
    "about-sevn.bot/specs/12-skills-system.md:",
    "scripts/check_removed_browser_skill_ids.py:",
    "scripts/removed_browser_skill_policy.py:",
    "scripts/ci_lib.py:",
    "Makefile:",
    "tests/browser/test_browser_removal_parity.py:",
    "tests/infra/test_removed_browser_skill_ids_check.py:",
)
