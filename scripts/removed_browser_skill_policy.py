"""Shared policy for removed Playwright-era bundled browser skills (#117, #127, D6).

Consumed by ``scripts/check_removed_browser_skill_ids.py`` and
``tests/browser/test_browser_removal_parity.py`` so survivor allowlists and gate
needles stay in one place.
"""

from __future__ import annotations

REMOVED_SKILL_IDS: frozenset[str] = frozenset(
    {
        "playwright-browser",
        "x-use",
        "facebook-use",
        "linkedin-use",
    }
)

FORBIDDEN_SUBSTRINGS: tuple[str, ...] = (*tuple(sorted(REMOVED_SKILL_IDS)), "playwright_browser")

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
