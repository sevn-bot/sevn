"""RED contract tests for changelog Unreleased datestamps (D10). Green after W6."""

from __future__ import annotations

import pytest

from _helpers import require_module

pytestmark = pytest.mark.xfail(
    reason="green after W6: skw.changelog_validate datestamp", strict=False
)

UNRELEASED_HEADING = "Unreleased"
DATESTAMP = "[2026-07-14]"


def _rules_with_datestamp() -> dict:
    changelog_validate = require_module("skw.changelog_validate")
    rules = changelog_validate.load_changelog_rules()
    entry = rules["entry"]
    assert entry.get("require_datestamp") is True
    assert "datestamp_pattern" in entry
    return rules


def _lint_unreleased(text: str) -> tuple[list[str], list[str]]:
    changelog_validate = require_module("skw.changelog_validate")
    rules = _rules_with_datestamp()
    parsed = changelog_validate.parse_changelog(text)
    version = next(v for v in parsed["versions"] if v["name"] == UNRELEASED_HEADING)
    return changelog_validate.lint_entries(version, rules)


def _changelog(*bullets: str, released_bullet: str | None = None) -> str:
    released = ""
    if released_bullet is not None:
        released = f"""
## [0.0.1] - 2026-01-01

### Added

- {released_bullet}
"""
    body = "\n".join(f"- {bullet}" for bullet in bullets)
    return f"""# Changelog

## [{UNRELEASED_HEADING}]

### Added

{body}
{released}
"""


def test_rules_require_leading_datestamp_pattern() -> None:
    """D10: ``changelog-rules.toml [entry]`` enables datestamp enforcement."""
    rules = _rules_with_datestamp()
    pattern = rules["entry"]["datestamp_pattern"]
    assert pattern.startswith("^\\[")
    assert "require_datestamp" in rules["entry"]


def test_unreleased_bullet_without_datestamp_fails() -> None:
    """D10: Unreleased bullets without a leading ``[YYYY-MM-DD]`` stamp fail lint."""
    text = _changelog("New `--retry` flag on `sevn onboard`")
    errors, _warnings = _lint_unreleased(text)
    assert errors
    assert any("datestamp" in err.lower() or "[" in err for err in errors)


def test_unreleased_bullet_with_valid_datestamp_passes() -> None:
    """D10: leading ``[YYYY-MM-DD]`` datestamp satisfies the Unreleased rule."""
    text = _changelog(f"{DATESTAMP} New `--retry` flag on `sevn onboard`")
    errors, _warnings = _lint_unreleased(text)
    assert errors == []


def test_released_section_bullets_unaffected_by_datestamp_rule() -> None:
    """D10: released-version bullets remain exempt from datestamp enforcement."""
    text = _changelog(
        f"{DATESTAMP} Current unreleased entry",
        released_bullet="Legacy entry without a datestamp",
    )
    changelog_validate = require_module("skw.changelog_validate")
    rules = _rules_with_datestamp()
    parsed = changelog_validate.parse_changelog(text)
    released = next(v for v in parsed["versions"] if v["name"] == "0.0.1")
    errors, _warnings = changelog_validate.lint_entries(released, rules)
    assert errors == []


def test_datestamp_interacts_with_no_trailing_period_rule() -> None:
    """D10 + existing rules: stamp precedes sentence-case body; trailing period still forbidden."""
    text = _changelog(f"{DATESTAMP} Added retry support.")
    errors, _warnings = _lint_unreleased(text)
    assert any("period" in err.lower() for err in errors)


def test_datestamp_interacts_with_issue_ref_rule() -> None:
    """D10 + existing rules: ``(#123)`` refs remain valid after the leading stamp."""
    text = _changelog(f"{DATESTAMP} Added retry support (#123)")
    errors, warnings = _lint_unreleased(text)
    assert errors == []
    assert not any("(#123)" in err for err in errors)
    assert not any("(#123)" in warn for warn in warnings)


def test_optional_time_suffix_allowed_by_pattern() -> None:
    """D10: ``YYYY-MM-DDTHH:MMZ`` suffix is allowed though date-only is the default."""
    text = _changelog("[2026-07-14T12:00Z] Added retry support")
    errors, _warnings = _lint_unreleased(text)
    assert errors == []
