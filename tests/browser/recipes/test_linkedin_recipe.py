"""Tests for LinkedIn Voyager scraper parsing (offline fixtures)."""

from __future__ import annotations

import pytest

from sevn.browser.recipes.linkedin_scraper import (
    LinkedInVoyagerScraper,
    RateLimitedError,
    VoyagerClient,
)


class _FakePage:
    async def evaluate(self, expression: str, *, return_by_value: bool = True) -> object:
        _ = expression, return_by_value
        return {"status": 200, "ok": True, "statusText": "OK", "json": {}, "text": "{}"}


@pytest.mark.asyncio
async def test_parse_staff_from_search_elements() -> None:
    """parse_staff extracts Staff rows from Voyager search clusters."""
    scraper = LinkedInVoyagerScraper(VoyagerClient(_FakePage()))  # type: ignore[arg-type]
    scraper.company_name = "amazon"
    scraper.search_term = ""
    scraper.raw_location = ""
    elements = [
        {
            "items": [
                {
                    "item": {
                        "entityResult": {
                            "entityUrn": "urn:li:fsd_profile:abc123,SEARCH_SRP",
                            "trackingUrn": "urn:li:member:999",
                            "title": {"text": "Jane Doe"},
                            "primarySubtitle": {"text": "Engineer at Amazon"},
                            "navigationUrl": "https://www.linkedin.com/in/jane?trk=foo",
                        }
                    }
                }
            ]
        }
    ]
    staff = scraper.parse_staff(elements)
    assert len(staff) == 1
    assert staff[0].name == "Jane Doe"
    assert staff[0].id == "abc123"


@pytest.mark.asyncio
async def test_raise_voyager_status_maps_429() -> None:
    """HTTP 429 raises RateLimitedError via scraper status helper."""
    from sevn.browser.recipes.linkedin_scraper import VoyagerResponse

    scraper = LinkedInVoyagerScraper(VoyagerClient(_FakePage()))  # type: ignore[arg-type]
    res = VoyagerResponse(
        ok=False, status_code=429, text="rate limited", reason="Too Many Requests"
    )
    with pytest.raises(RateLimitedError):
        scraper._raise_voyager_status(res)
