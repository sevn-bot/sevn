"""Google Maps recipe — search, place detail, directions, and reviews.

Read-only scraping of ``google.com/maps`` result and detail pages. All ops are
read-only (no write kill-switch).

Module: sevn.browser.recipes.google_maps
Depends: re, urllib.parse, sevn.browser.page, sevn.browser.recipes.base

Exports:
    parse_places — parse a places list from saved HTML.
    parse_place — parse place detail fields from saved HTML.
    parse_directions — parse a directions summary from saved HTML.
    parse_reviews — parse top reviews from saved HTML.
    GoogleMaps — live recipe over a page/dom pair.

Examples:
    >>> from sevn.browser.recipes.google_maps import parse_places
    >>> parse_places("<html></html>")["count"]
    0
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import quote_plus

from sevn.browser.recipes.base import RecipeError, validate_egress

if TYPE_CHECKING:
    from sevn.browser.element import Dom
    from sevn.browser.page import Page

GOOGLE_MAPS_EGRESS: Final[tuple[str, ...]] = ("google.com", "maps.google.com")
_MAPS_SEARCH_URL: Final[str] = "https://www.google.com/maps/search/{query}"
_MAPS_PLACE_URL: Final[str] = "https://www.google.com/maps/place/{place}"
_MAPS_DIRECTIONS_URL: Final[str] = "https://www.google.com/maps/dir/{origin}/{destination}"

_PLACE_CARD_RE: Final[re.Pattern[str]] = re.compile(
    r'role="article"[^>]*>(.*?)</div>\s*</div>',
    re.IGNORECASE | re.DOTALL,
)
_PLACE_NAME_RE: Final[re.Pattern[str]] = re.compile(
    r'class="fontHeadlineSmall"[^>]*>([^<]+)<',
    re.IGNORECASE,
)
_PLACE_ADDR_RE: Final[re.Pattern[str]] = re.compile(
    r'class="fontBodyMedium"[^>]*>([^<]+)<',
    re.IGNORECASE,
)
_DETAIL_NAME_RE: Final[re.Pattern[str]] = re.compile(
    r'class="DUwDvf"[^>]*>([^<]+)<',
    re.IGNORECASE,
)
_DETAIL_ADDR_RE: Final[re.Pattern[str]] = re.compile(
    r'data-item-id="address"[^>]*>([^<]+)<',
    re.IGNORECASE,
)
_DETAIL_RATING_RE: Final[re.Pattern[str]] = re.compile(
    r'aria-label="([0-9.]+)\s+stars?"',
    re.IGNORECASE,
)
_DETAIL_PHONE_RE: Final[re.Pattern[str]] = re.compile(
    r'data-item-id="phone"[^>]*>([^<]+)<',
    re.IGNORECASE,
)
_DETAIL_SITE_RE: Final[re.Pattern[str]] = re.compile(
    r'data-item-id="authority"[^>]*>([^<]+)<',
    re.IGNORECASE,
)
_DETAIL_HOURS_RE: Final[re.Pattern[str]] = re.compile(
    r'data-item-id="oh"[^>]*>([^<]+)<',
    re.IGNORECASE,
)
_DURATION_RE: Final[re.Pattern[str]] = re.compile(
    r'class="section-directions-trip-duration"[^>]*>([^<]+)<',
    re.IGNORECASE,
)
_DISTANCE_RE: Final[re.Pattern[str]] = re.compile(
    r'class="section-directions-trip-distance"[^>]*>([^<]+)<',
    re.IGNORECASE,
)
_REVIEW_BLOCK_RE: Final[re.Pattern[str]] = re.compile(
    r'class="jftiEf"[^>]*>(.*?)</div>\s*</div>',
    re.IGNORECASE | re.DOTALL,
)
_REVIEW_AUTHOR_RE: Final[re.Pattern[str]] = re.compile(
    r'class="d4r55"[^>]*>([^<]+)<',
    re.IGNORECASE,
)
_REVIEW_TEXT_RE: Final[re.Pattern[str]] = re.compile(
    r'class="MyEned"[^>]*>([^<]+)<',
    re.IGNORECASE,
)
_REVIEW_STARS_RE: Final[re.Pattern[str]] = re.compile(
    r'aria-label="([0-9.]+)\s+stars?"',
    re.IGNORECASE,
)


def parse_places(html: str) -> dict[str, Any]:
    """Parse a Google Maps search results list from saved HTML.

    Args:
        html (str): Saved Maps search results HTML.

    Returns:
        dict[str, Any]: ``{places: [...], count}``.

    Examples:
        >>> html = (
        ...     '<div role="article"><div class="fontHeadlineSmall">Cafe</div>'
        ...     '<div class="fontBodyMedium">1 Main St</div></div>'
        ... )
        >>> parse_places(html)["places"][0]["name"]
        'Cafe'
    """
    places: list[dict[str, str]] = []
    for block in _PLACE_CARD_RE.finditer(html or ""):
        chunk = block.group(1)
        name = _PLACE_NAME_RE.search(chunk)
        addr = _PLACE_ADDR_RE.search(chunk)
        if name:
            places.append(
                {
                    "name": name.group(1).strip(),
                    "address": addr.group(1).strip() if addr else "",
                }
            )
    if not places:
        for name in _PLACE_NAME_RE.finditer(html or ""):
            places.append({"name": name.group(1).strip(), "address": ""})
    return {"places": places, "count": len(places)}


def parse_place(html: str) -> dict[str, Any]:
    """Parse place detail fields from saved Maps HTML.

    Args:
        html (str): Saved Maps place detail HTML.

    Returns:
        dict[str, Any]: ``{name, address, rating, phone, website, hours}``.

    Examples:
        >>> html = (
        ...     '<h1 class="DUwDvf">Park</h1><div data-item-id="address">NYC</div>'
        ...     '<div aria-label="4.5 stars"></div>'
        ... )
        >>> parse_place(html)["name"]
        'Park'
    """
    name = _DETAIL_NAME_RE.search(html or "")
    addr = _DETAIL_ADDR_RE.search(html or "")
    rating = _DETAIL_RATING_RE.search(html or "")
    phone = _DETAIL_PHONE_RE.search(html or "")
    site = _DETAIL_SITE_RE.search(html or "")
    hours = _DETAIL_HOURS_RE.search(html or "")
    return {
        "name": name.group(1).strip() if name else "",
        "address": addr.group(1).strip() if addr else "",
        "rating": rating.group(1).strip() if rating else "",
        "phone": phone.group(1).strip() if phone else "",
        "website": site.group(1).strip() if site else "",
        "hours": hours.group(1).strip() if hours else "",
    }


def parse_directions(html: str) -> dict[str, Any]:
    """Parse a directions summary from saved Maps HTML.

    Args:
        html (str): Saved Maps directions HTML.

    Returns:
        dict[str, Any]: ``{duration, distance}``.

    Examples:
        >>> html = (
        ...     '<div class="section-directions-trip-duration">20 min</div>'
        ...     '<div class="section-directions-trip-distance">5.1 mi</div>'
        ... )
        >>> parse_directions(html)["duration"]
        '20 min'
    """
    duration = _DURATION_RE.search(html or "")
    distance = _DISTANCE_RE.search(html or "")
    return {
        "duration": duration.group(1).strip() if duration else "",
        "distance": distance.group(1).strip() if distance else "",
    }


def parse_reviews(html: str, *, limit: int = 10) -> dict[str, Any]:
    """Parse top reviews from saved Maps HTML.

    Args:
        html (str): Saved Maps reviews HTML.
        limit (int): Maximum reviews to return.

    Returns:
        dict[str, Any]: ``{reviews: [...], count}``.

    Examples:
        >>> html = (
        ...     '<div class="jftiEf"><div class="d4r55">Ann</div>'
        ...     '<span aria-label="5 stars"></span><div class="MyEned">Nice!</div></div>'
        ... )
        >>> parse_reviews(html)["reviews"][0]["author"]
        'Ann'
    """
    reviews: list[dict[str, str]] = []
    for block in _REVIEW_BLOCK_RE.finditer(html or ""):
        if len(reviews) >= limit:
            break
        chunk = block.group(1)
        author = _REVIEW_AUTHOR_RE.search(chunk)
        text = _REVIEW_TEXT_RE.search(chunk)
        stars = _REVIEW_STARS_RE.search(chunk)
        if author or text:
            reviews.append(
                {
                    "author": author.group(1).strip() if author else "",
                    "text": text.group(1).strip() if text else "",
                    "rating": stars.group(1).strip() if stars else "",
                }
            )
    return {"reviews": reviews, "count": len(reviews)}


class GoogleMaps:
    """Google Maps operations over a CDP page + finder."""

    def __init__(self, page: Page, dom: Dom) -> None:
        """Bind a page and finder for Google Maps.

        Args:
            page (Page): Page bound to the active tab.
            dom (Dom): Finder bound to the same tab.

        Returns:
            None

        Examples:
            >>> import inspect
            >>> inspect.isfunction(GoogleMaps.__init__)
            True
        """
        self._page = page
        self._dom = dom

    async def run(
        self,
        op: str,
        *,
        query: str = "",
        place: str = "",
        origin: str = "",
        destination: str = "",
    ) -> dict[str, Any]:
        """Dispatch a Google Maps recipe operation.

        Args:
            op (str): ``search``, ``place``, ``directions``, or ``reviews``.
            query (str): Search query for ``search``.
            place (str): Place name or slug for ``place`` / ``reviews``.
            origin (str): Start location for ``directions``.
            destination (str): End location for ``directions``.

        Returns:
            dict[str, Any]: Operation result payload.

        Raises:
            RecipeError: When required params are missing or the op is unknown.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(GoogleMaps.run)
            True
        """
        normalized = (op or "").strip().lower()
        if normalized == "search":
            return await self.search(query)
        if normalized == "place":
            return await self.place_detail(place or query)
        if normalized == "directions":
            return await self.directions(origin, destination)
        if normalized == "reviews":
            return await self.reviews(place or query)
        msg = f"unknown maps op: {op!r} (search|place|directions|reviews)"
        raise RecipeError(msg)

    async def search(self, query: str) -> dict[str, Any]:
        """Search Maps for ``query`` and return matching places.

        Args:
            query (str): Free-text search query.

        Returns:
            dict[str, Any]: Parsed places list.

        Raises:
            RecipeError: When ``query`` is empty.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(GoogleMaps.search)
            True
        """
        text = (query or "").strip()
        if not text:
            msg = "query is required for maps search"
            raise RecipeError(msg)
        url = validate_egress(
            _MAPS_SEARCH_URL.format(query=quote_plus(text)),
            allowlist=GOOGLE_MAPS_EGRESS,
        )
        await self._page.goto(url, wait_until="none")
        html = await self._page.extract_html()
        parsed = parse_places(html)
        return {"op": "search", "query": text, **parsed}

    async def place_detail(self, place: str) -> dict[str, Any]:
        """Open a place and return its detail fields.

        Args:
            place (str): Place name or URL slug.

        Returns:
            dict[str, Any]: Parsed place detail payload.

        Raises:
            RecipeError: When ``place`` is empty.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(GoogleMaps.place_detail)
            True
        """
        text = (place or "").strip()
        if not text:
            msg = "place or query is required for maps place"
            raise RecipeError(msg)
        url = validate_egress(
            _MAPS_PLACE_URL.format(place=quote_plus(text)),
            allowlist=GOOGLE_MAPS_EGRESS,
        )
        await self._page.goto(url, wait_until="none")
        html = await self._page.extract_html()
        parsed = parse_place(html)
        return {"op": "place", "place": text, **parsed}

    async def directions(self, origin: str, destination: str) -> dict[str, Any]:
        """Return a directions summary for ``origin`` → ``destination``.

        Args:
            origin (str): Start location.
            destination (str): End location.

        Returns:
            dict[str, Any]: Parsed directions summary.

        Raises:
            RecipeError: When either endpoint is missing.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(GoogleMaps.directions)
            True
        """
        start = (origin or "").strip()
        end = (destination or "").strip()
        if not start or not end:
            msg = "origin and destination are required for maps directions"
            raise RecipeError(msg)
        url = validate_egress(
            _MAPS_DIRECTIONS_URL.format(
                origin=quote_plus(start),
                destination=quote_plus(end),
            ),
            allowlist=GOOGLE_MAPS_EGRESS,
        )
        await self._page.goto(url, wait_until="none")
        html = await self._page.extract_html()
        parsed = parse_directions(html)
        return {"op": "directions", "origin": start, "destination": end, **parsed}

    async def reviews(self, place: str) -> dict[str, Any]:
        """Return top reviews for ``place``.

        Args:
            place (str): Place name or slug (same as :meth:`place_detail`).

        Returns:
            dict[str, Any]: Parsed reviews list.

        Raises:
            RecipeError: When ``place`` is empty.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(GoogleMaps.reviews)
            True
        """
        text = (place or "").strip()
        if not text:
            msg = "place or query is required for maps reviews"
            raise RecipeError(msg)
        url = validate_egress(
            _MAPS_PLACE_URL.format(place=quote_plus(text)),
            allowlist=GOOGLE_MAPS_EGRESS,
        )
        await self._page.goto(url, wait_until="none")
        html = await self._page.extract_html()
        parsed = parse_reviews(html)
        return {"op": "reviews", "place": text, **parsed}


__all__ = [
    "GOOGLE_MAPS_EGRESS",
    "GoogleMaps",
    "parse_directions",
    "parse_place",
    "parse_places",
    "parse_reviews",
]
