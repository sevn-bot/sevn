"""Tests for LinkedIn recipe models and parsers."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from sevn.browser.recipes.linkedin_models import (
    Staff,
    create_emails,
    extract_base_domain,
    extract_emails_from_text,
    parse_company_data,
    parse_dates,
    parse_duration,
    staff_rows_to_dicts,
)

_FIXTURES = Path(__file__).parent / "fixtures" / "linkedin"


def test_extract_emails_from_text() -> None:
    """Find email addresses in free text."""
    assert extract_emails_from_text("mail ann@example.com now") == ["ann@example.com"]


def test_create_emails() -> None:
    """Guess corporate email patterns."""
    emails = create_emails("Ann", "Lee", "example.com")
    assert emails[0] == "ann.lee@example.com"


def test_extract_base_domain() -> None:
    """Strip company page URL to domain suffix."""
    assert extract_base_domain("https://www.amazon.com/jobs") == "amazon.com"


def test_parse_dates_present() -> None:
    """Parse a Present-style duration."""
    start, end = parse_dates("Jan 2020 - Present")
    assert start == date(2020, 1, 1)
    assert end is None


def test_parse_duration() -> None:
    """Parse duration with tenure suffix."""
    from_date, to_date = parse_duration("Jan 2020 - Present · 4 yrs")
    assert from_date == date(2020, 1, 1)
    assert to_date is None


def test_parse_company_data_fixture() -> None:
    """Parse saved Voyager company payload."""
    payload = json.loads((_FIXTURES / "company_amazon.json").read_text(encoding="utf-8"))
    row = parse_company_data(payload, search_term="amazon")
    assert row["company_name"] == "Amazon"
    assert row["linkedin_company_id"] == "1586"
    assert row["staff_count"] == 750000


def test_staff_to_dict_shape() -> None:
    """Staff.to_dict preserves StaffSpy flat columns."""
    staff = Staff(
        id="abc",
        search_term="amazon",
        name="Jane Doe",
        headline="Engineer",
        profile_link="https://www.linkedin.com/in/jane",
    )
    row = staff.to_dict()
    assert row["name"] == "Jane Doe"
    assert row["search_term"] == "amazon"


def test_staff_rows_to_dicts_orders_hidden_last() -> None:
    """Deprioritize LinkedIn Member hidden rows."""
    rows = staff_rows_to_dicts(
        [
            Staff(id="1", search_term="x", name="LinkedIn Member"),
            Staff(id="2", search_term="x", name="Visible Person"),
        ]
    )
    assert rows[0]["name"] == "Visible Person"
    assert rows[-1]["name"] == "LinkedIn Member"
