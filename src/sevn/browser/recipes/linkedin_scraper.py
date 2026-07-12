"""LinkedIn Voyager API scraper over an authenticated browser page (ported from StaffSpy).

StaffSpy upstream: https://github.com/cullenwatson/StaffSpy (MIT).

Module: sevn.browser.recipes.linkedin_scraper
Depends: asyncio, base64, calendar, json, re, urllib.parse, loguru, sevn.browser.page,
    sevn.browser.recipes.base, sevn.browser.recipes.linkedin_models

Exports:
    VoyagerClient — in-page fetch wrapper over :class:`~sevn.browser.page.Page`.
    LinkedInVoyagerScraper — async staff/connection scraper and profile enrichment.
    VoyagerResponse — decoded Voyager fetch result (status + JSON body).
    RateLimitedError — raised on 429 cooldown.
    VoyagerStaleError — raised when a Voyager payload is stale/unavailable.
    GeoUrnNotFound — raised when a location geo-urn cannot be resolved.

Examples:
    >>> from sevn.browser.recipes.linkedin_scraper import LINKEDIN_EGRESS
    >>> "linkedin.com" in LINKEDIN_EGRESS
    True
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import re
from calendar import month_name
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import quote, unquote

from loguru import logger

from sevn.browser.recipes.base import RecipeError, validate_egress
from sevn.browser.recipes.linkedin_models import (
    Certification,
    ContactInfo,
    Experience,
    School,
    Skill,
    Staff,
    create_emails,
    extract_base_domain,
    parse_dates,
    parse_duration,
)

if TYPE_CHECKING:
    from sevn.browser.page import Page

LINKEDIN_EGRESS: Final[tuple[str, ...]] = ("linkedin.com", "licdn.com")

_PROFILE_URN_RE: Final[re.Pattern[str]] = re.compile(
    r"urn:li:fsd_profile:([^,]+),(?:SEARCH_SRP|MYNETWORK_CURATION_HUB)"
)
_GEO_URN_RE: Final[re.Pattern[str]] = re.compile(r"urn:li:geo:(.+)")
_COMPANY_SLUG_RE: Final[re.Pattern[str]] = re.compile(r"/company/([^/]+)")
_MUTUAL_COUNT_RE: Final[re.Pattern[str]] = re.compile(r"\d+")


class RateLimitedError(RecipeError):
    """LinkedIn returned HTTP 429 (rate limited)."""


class VoyagerStaleError(RecipeError):
    """LinkedIn Voyager rejected the request (typically HTTP 400 / stale session)."""


class GeoUrnNotFound(RecipeError):
    """LinkedIn geo typeahead did not resolve a location URN."""


class VoyagerResponse:
    """Minimal HTTP response shape for Voyager in-page fetch results."""

    __slots__ = ("ok", "reason", "status_code", "text")

    def __init__(self, *, ok: bool, status_code: int, text: str, reason: str) -> None:
        """Store Voyager fetch metadata.

        Args:
            ok (bool): Whether the status is in the 200-299 range.
            status_code (int): HTTP status code.
            text (str): Response body text.
            reason (str): HTTP status text.

        Returns:
            None

        Examples:
            >>> resp = VoyagerResponse(ok=True, status_code=200, text="{}", reason="OK")
            >>> resp.json()
            {}
        """
        self.ok = ok
        self.status_code = status_code
        self.text = text
        self.reason = reason

    def json(self) -> Any:
        """Parse the response body as JSON.

        Returns:
            Any: Parsed JSON value.

        Raises:
            json.JSONDecodeError: When the body is not valid JSON.

        Examples:
            >>> VoyagerResponse(ok=True, status_code=200, text='{"a":1}', reason="OK").json()
            {'a': 1}
        """
        return json.loads(self.text)


class VoyagerClient:
    """In-page Voyager HTTP client over an authenticated LinkedIn :class:`Page`."""

    def __init__(self, page: Page) -> None:
        """Bind a browser page for credentialed Voyager fetch calls.

        Args:
            page (Page): Authenticated LinkedIn page session.

        Returns:
            None

        Examples:
            >>> import inspect
            >>> inspect.isfunction(VoyagerClient.__init__)
            True
        """
        self._page = page
        self.on_block = False
        self.connect_block = False

    async def get(self, url: str, *, graphql: bool = False) -> VoyagerResponse:
        """GET ``url`` via in-page ``fetch`` with LinkedIn Voyager headers.

        Args:
            url (str): Absolute Voyager API URL.
            graphql (bool): When ``True``, send the GraphQL pegasus client header.

        Returns:
            VoyagerResponse: Parsed fetch result.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(VoyagerClient.get)
            True
        """
        validate_egress(url, allowlist=LINKEDIN_EGRESS)
        extra_headers = {"x-li-graphql-pegasus-client": "true"} if graphql else {}
        return await self._fetch(
            url,
            method="GET",
            headers=extra_headers,
            body_b64=None,
        )

    async def post(
        self,
        url: str,
        body: bytes,
        content_type: str,
    ) -> VoyagerResponse:
        """POST binary ``body`` to ``url`` via in-page ``fetch``.

        Args:
            url (str): Absolute Voyager API URL.
            body (bytes): Request payload (protobuf for block/connect actions).
            content_type (str): ``Content-Type`` header value.

        Returns:
            VoyagerResponse: Parsed fetch result.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(VoyagerClient.post)
            True
        """
        validate_egress(url, allowlist=LINKEDIN_EGRESS)
        return await self._fetch(
            url,
            method="POST",
            headers={"Content-Type": content_type},
            body_b64=base64.b64encode(body).decode("ascii"),
        )

    async def _fetch(
        self,
        url: str,
        *,
        method: str,
        headers: dict[str, str],
        body_b64: str | None,
    ) -> VoyagerResponse:
        """Execute a credentialed Voyager fetch inside the page context.

        Args:
            url (str): Target URL.
            method (str): HTTP method (``GET`` or ``POST``).
            headers (dict[str, str]): Extra request headers.
            body_b64 (str | None): Base64-encoded POST body, if any.

        Returns:
            VoyagerResponse: Parsed fetch result.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(VoyagerClient._fetch)
            True
        """
        url_js = json.dumps(url)
        method_js = json.dumps(method)
        headers_js = json.dumps(
            {
                "accept": "application/vnd.linkedin.normalized+json+2.1",
                "x-restli-protocol-version": "2.0.0",
                **headers,
            }
        )
        body_js = json.dumps(body_b64)
        expression = f"""
(async () => {{
  const getCookie = (name) => {{
    const value = `; ${{document.cookie}}`;
    const parts = value.split(`; ${{name}}=`);
    if (parts.length === 2) return parts.pop().split(';').shift();
    return undefined;
  }};
  const csrf = (getCookie('JSESSIONID') || '').replace(/"/g, '');
  const headers = {headers_js};
  if (csrf) headers['csrf-token'] = csrf;
  const init = {{ method: {method_js}, credentials: 'include', headers }};
  const bodyB64 = {body_js};
  if (bodyB64) {{
    const binary = atob(bodyB64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    init.body = bytes;
  }}
  const resp = await fetch({url_js}, init);
  const text = await resp.text();
  return {{
    ok: resp.ok,
    status: resp.status,
    statusText: resp.statusText || '',
    text,
  }};
}})()
"""
        result = await self._page.evaluate(expression)
        if not isinstance(result, dict):
            msg = f"unexpected voyager fetch result: {result!r}"
            raise RecipeError(msg)
        status = int(result.get("status") or 0)
        text = str(result.get("text") or "")
        reason = str(result.get("statusText") or "")
        return VoyagerResponse(
            ok=bool(result.get("ok")),
            status_code=status,
            text=text,
            reason=reason,
        )


class LinkedInVoyagerScraper:
    """Async LinkedIn Voyager staff/connection scraper (StaffSpy port)."""

    employees_ep = (
        "https://www.linkedin.com/voyager/api/graphql?variables=(start:{offset},"
        "query:(flagshipSearchIntent:SEARCH_SRP,{search}queryParameters:List("
        "{company_id}{location}(key:resultType,value:List(PEOPLE))),"
        "includeFiltersInResponse:false),count:{count})"
        "&queryId=voyagerSearchDashClusters.66adc6056cf4138949ca5dcb31bb1749"
    )
    company_id_ep = (
        "https://www.linkedin.com/voyager/api/organization/companies?q=universalName&universalName="
    )
    company_search_ep = (
        "https://www.linkedin.com/voyager/api/graphql?"
        "queryId=voyagerSearchDashClusters.02af3bc8bc85a169bb76bb4805d05759"
        "&queryName=SearchClusterCollection&variables=(query:(flagshipSearchIntent:"
        "SEARCH_SRP,keywords:{company},includeFiltersInResponse:false,"
        "queryParameters:(keywords:List({company}),resultType:List(COMPANIES))),"
        "count:10,origin:GLOBAL_SEARCH_HEADER,start:0)"
    )
    location_id_ep = (
        "https://www.linkedin.com/voyager/api/graphql?"
        "queryId=voyagerSearchDashReusableTypeahead.57a4fa1dd92d3266ed968fdbab2d7bf5"
        "&queryName=SearchReusableTypeaheadByType&variables=(query:("
        "showFullLastNameForConnections:false,typeaheadFilterQuery:("
        "geoSearchTypes:List(MARKET_AREA,COUNTRY_REGION,ADMIN_DIVISION_1,CITY))),"
        "keywords:{location},type:GEO,start:0)"
    )
    public_user_id_ep = (
        "https://www.linkedin.com/voyager/api/identity/profiles/{user_id}/profileView"
    )
    connections_ep = (
        "https://www.linkedin.com/voyager/api/graphql?"
        "queryId=voyagerSearchDashClusters.dfcd3603c2779eddd541f572936f4324"
        "&queryName=SearchClusterCollection&variables=(query:(queryParameters:("
        "resultType:List(FOLLOWERS)),flagshipSearchIntent:MYNETWORK_CURATION_HUB,"
        "includeFiltersInResponse:true),count:50,origin:CurationHub,start:{offset})"
    )
    block_user_ep = (
        "https://www.linkedin.com/voyager/api/voyagerTrustDashContentReportingForm"
        "?action=entityBlock"
    )
    connect_to_user_ep = (
        "https://www.linkedin.com/voyager/api/voyagerRelationshipsDashMemberRelationships"
        "?action=verifyQuotaAndCreateV2&decorationId="
        "com.linkedin.voyager.dash.deco.relationships.InvitationCreationResultWithInvitee-1"
    )
    _employee_ep = (
        "https://www.linkedin.com/voyager/api/voyagerIdentityDashProfiles?count=1"
        "&decorationId=com.linkedin.voyager.dash.deco.identity.profile.TopCardComplete-138"
        "&memberIdentity={employee_id}&q=memberIdentity"
    )
    _skills_ep = (
        "https://www.linkedin.com/voyager/api/graphql?"
        "queryId=voyagerIdentityDashProfileComponents.277ba7d7b9afffb04683953cede751fb"
        "&queryName=ProfileComponentsBySectionType&variables=(tabIndex:0,"
        "sectionType:skills,profileUrn:urn%3Ali%3Afsd_profile%3A{employee_id},count:50)"
    )
    _experiences_ep = (
        "https://www.linkedin.com/voyager/api/graphql?"
        "queryId=voyagerIdentityDashProfileComponents.277ba7d7b9afffb04683953cede751fb"
        "&queryName=ProfileComponentsBySectionType&variables=(tabIndex:0,"
        "sectionType:experience,profileUrn:urn%3Ali%3Afsd_profile%3A{employee_id},count:50)"
    )
    _certifications_ep = (
        "https://www.linkedin.com/voyager/api/graphql?"
        "queryId=voyagerIdentityDashProfileComponents.277ba7d7b9afffb04683953cede751fb"
        "&queryName=ProfileComponentsBySectionType&variables=(tabIndex:0,"
        "sectionType:certifications,profileUrn:urn%3Ali%3Afsd_profile%3A{employee_id},count:50)"
    )
    _schools_ep = (
        "https://www.linkedin.com/voyager/api/graphql?"
        "queryId=voyagerIdentityDashProfileComponents.277ba7d7b9afffb04683953cede751fb"
        "&queryName=ProfileComponentsBySectionType&variables=(tabIndex:0,"
        "sectionType:education,profileUrn:urn%3Ali%3Afsd_profile%3A{employee_id},count:50)"
    )
    _bio_ep = (
        "https://www.linkedin.com/voyager/api/graphql?"
        "queryId=voyagerIdentityDashProfileCards.9ad2590cb61a073ad514922fa752f566"
        "&queryName=ProfileTabInitialCards&variables=(count:50,"
        "profileUrn:urn%3Ali%3Afsd_profile%3A{employee_id})"
    )
    _languages_ep = (
        "https://www.linkedin.com/voyager/api/graphql?"
        "queryId=voyagerIdentityDashProfileComponents.9117695ef207012719e3e0681c667e14"
        "&queryName=ProfileComponentsBySectionType&variables=(tabIndex:0,"
        "sectionType:languages,profileUrn:urn%3Ali%3Afsd_profile%3A{employee_id},count:50)"
    )
    _contact_ep = (
        "https://www.linkedin.com/voyager/api/graphql?"
        "queryId=voyagerIdentityDashProfiles.13618f886ce95bf503079f49245fbd6f"
        "&queryName=ProfilesByMemberIdentity&variables=(memberIdentity:{employee_id},count:1)"
    )

    def __init__(self, client: VoyagerClient) -> None:
        """Create a scraper bound to a :class:`VoyagerClient`.

        Args:
            client (VoyagerClient): Credentialed Voyager HTTP client.

        Returns:
            None

        Examples:
            >>> import inspect
            >>> inspect.isfunction(LinkedInVoyagerScraper.__init__)
            True
        """
        self.client = client
        self.company_id: str | None = None
        self.staff_count: int | None = None
        self.num_staff: int | None = None
        self.company_name: str | None = None
        self.domain: str | None = None
        self.max_results: int | None = None
        self.search_term: str | None = None
        self.location: str | None = None
        self.raw_location: str | None = None

    @property
    def on_block(self) -> bool:
        """Return whether a fatal rate-limit or stale-session block was hit.

        Returns:
            bool: See implementation.

        Examples:
            >>> isinstance(LinkedInVoyagerScraper.on_block, property)
            True
        """
        return self.client.on_block

    @on_block.setter
    def on_block(self, value: bool) -> None:
        """Set the fatal-block flag on the underlying client.

        Args:
            value (bool): New block state.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(LinkedInVoyagerScraper.on_block.fset)
            True
        """
        self.client.on_block = value

    @property
    def connect_block(self) -> bool:
        """Return whether connection requests are paused for this scrape.

        Returns:
            bool: See implementation.

        Examples:
            >>> isinstance(LinkedInVoyagerScraper.connect_block, property)
            True
        """
        return self.client.connect_block

    @connect_block.setter
    def connect_block(self, value: bool) -> None:
        """Set the connection-request pause flag on the underlying client.

        Args:
            value (bool): New pause state.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(LinkedInVoyagerScraper.connect_block.fset)
            True
        """
        self.client.connect_block = value

    def _raise_voyager_status(self, res: VoyagerResponse) -> None:
        """Map Voyager HTTP status codes to recipe errors.

        Args:
            res (VoyagerResponse): Response to inspect.

        Returns:
            None

        Raises:
            VoyagerStaleError: On HTTP 400.
            RateLimitedError: On HTTP 429 (also sets ``on_block``).

        Examples:
            >>> import inspect
            >>> inspect.isfunction(LinkedInVoyagerScraper._raise_voyager_status)
            True
        """
        if res.status_code == 400:
            raise VoyagerStaleError("Outdated login, delete the session file to log in again")
        if res.status_code == 429:
            self.on_block = True
            raise RateLimitedError("429 Too Many Requests")

    def _raise_rate_limit(self, res: VoyagerResponse) -> None:
        """Raise :class:`RateLimitedError` when ``res`` is HTTP 429.

        Args:
            res (VoyagerResponse): Response to inspect.

        Returns:
            None

        Raises:
            RateLimitedError: On HTTP 429 (also sets ``on_block``).

        Examples:
            >>> import inspect
            >>> inspect.isfunction(LinkedInVoyagerScraper._raise_rate_limit)
            True
        """
        if res.status_code == 429:
            self.on_block = True
            raise RateLimitedError("429 Too Many Requests")

    async def search_companies(self, company_name: str) -> str:
        """Resolve a company universal name via LinkedIn company search.

        Args:
            company_name (str): Human-readable company name.

        Returns:
            str: LinkedIn company universal name (slug).

        Raises:
            RecipeError: When search fails or no company is found.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(LinkedInVoyagerScraper.search_companies)
            True
        """
        company_search_url = self.company_search_ep.format(company=quote(company_name))
        res = await self.client.get(company_search_url, graphql=True)
        if not res.ok:
            msg = f"Failed to search for company {company_name}: {res.status_code} {res.text[:200]}"
            raise RecipeError(msg)
        logger.debug(
            "Searched companies for name {!r} - res code {}",
            company_name,
            res.status_code,
        )
        try:
            companies = res.json()["data"]["searchDashClustersByAll"]["elements"]
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            msg = f"Failed to load json in search_companies: {exc}; response: {res.text[:200]}"
            raise RecipeError(msg) from exc

        err_msg = f"No companies found for name {company_name}"
        if len(companies) < 2:
            raise RecipeError(err_msg)
        try:
            num_results = companies[0]["items"][0]["item"]["simpleTextV2"]["text"]["text"]
            first_company = companies[1]["items"][0]["item"].get("entityResult")
            if not first_company and len(companies) > 2:
                first_company = companies[2]["items"][0]["item"].get("entityResult")
            if not first_company:
                raise RecipeError(err_msg)

            company_link = first_company["navigationUrl"]
            slug_match = _COMPANY_SLUG_RE.search(company_link)
            if not slug_match:
                raise RecipeError(err_msg)
            company_name_id = unquote(slug_match.group(1))
            company_name_new = first_company["title"]["text"]
        except RecipeError:
            raise
        except (KeyError, TypeError, IndexError) as exc:
            msg = f"Failed to load json in search_companies {exc}, Response: {res.text[:200]}"
            raise RecipeError(msg) from exc

        logger.info(
            "Searched company {} on LinkedIn and were {}, using first result "
            "with company name - {!r} and company id - {!r}",
            company_name,
            num_results,
            company_name_new,
            company_name_id,
        )
        return company_name_id

    async def fetch_or_search_company(self, company_name: str) -> VoyagerResponse:
        """Fetch company details by universal name, searching when not found directly.

        Args:
            company_name (str): Company universal name or search term.

        Returns:
            VoyagerResponse: Company details payload.

        Raises:
            RecipeError: When lookup fails after direct and search attempts.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(LinkedInVoyagerScraper.fetch_or_search_company)
            True
        """
        res = await self.client.get(f"{self.company_id_ep}{company_name}")
        if res.status_code not in (200, 404):
            msg = (
                f"Failed to find company {company_name} "
                "(likely due to outdated login if you know it's valid company): "
                f"{res.status_code} {res.text[:200]}"
            )
            raise RecipeError(msg)
        if res.status_code == 404:
            logger.info(
                "Failed to directly use company {!r} as company id, now searching",
                company_name,
            )
            company_name = await self.search_companies(company_name)
            res = await self.client.get(f"{self.company_id_ep}{company_name}")
            if res.status_code != 200:
                msg = (
                    f"Failed to find company after performing a direct and generic "
                    f"search for {company_name}: {res.status_code} {res.text[:200]}"
                )
                raise RecipeError(msg)
        if not res.ok:
            logger.debug("res code {} - fetched company", res.status_code)
        return res

    async def _get_company_id_and_staff_count(self, company_name: str) -> tuple[str, int]:
        """Resolve company id and staff count from a company name or slug.

        Args:
            company_name (str): Company universal name or search term.

        Returns:
            tuple[str, int]: ``(company_id, staff_count)``.

        Raises:
            RecipeError: When the company payload cannot be parsed.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(LinkedInVoyagerScraper._get_company_id_and_staff_count)
            True
        """
        res = await self.fetch_or_search_company(company_name)
        try:
            response_json = res.json()
        except json.JSONDecodeError as exc:
            logger.debug(res.text[:200])
            msg = f"Failed to load json in get_company_id_and_staff_count {res.text[:200]}"
            raise RecipeError(msg) from exc

        company = response_json["elements"][0]
        self.domain = (
            extract_base_domain(company["companyPageUrl"])
            if company.get("companyPageUrl")
            else None
        )
        staff_count = company["staffCount"]
        company_id = company["trackingInfo"]["objectUrn"].split(":")[-1]
        resolved_name = company["universalName"]
        logger.info("Found company {!r} with {} staff", resolved_name, staff_count)
        return company_id, staff_count

    def parse_staff(self, elements: list[dict[str, Any]]) -> list[Staff]:
        """Parse staff rows from Voyager search cluster elements.

        Args:
            elements (list[dict[str, Any]]): ``searchDashClustersByAll`` elements.

        Returns:
            list[Staff]: Parsed staff rows.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(LinkedInVoyagerScraper.parse_staff)
            True
        """
        staff: list[Staff] = []
        for elem in elements:
            for card in elem.get("items", []):
                person = card.get("item", {}).get("entityResult", {})
                if not person:
                    continue
                match = _PROFILE_URN_RE.search(person["entityUrn"])
                linkedin_id = match.group(1) if match else None
                person_urn = person["trackingUrn"].split(":")[-1]
                name = person["title"]["text"].strip()
                headline = (
                    person.get("primarySubtitle", {}).get("text", "")
                    if person.get("primarySubtitle")
                    else ""
                )
                profile_link = person["navigationUrl"].split("?")[0]
                staff.append(
                    Staff(
                        urn=person_urn,
                        id=linkedin_id or "",
                        name=name,
                        headline=headline,
                        search_term=" - ".join(
                            filter(
                                None,
                                [self.company_name, self.search_term, self.raw_location],
                            )
                        ),
                        profile_link=profile_link,
                    )
                )
        return staff

    async def fetch_staff(self, offset: int) -> tuple[list[Staff] | None, int]:
        """Fetch one page of staff search results.

        Args:
            offset (int): Pagination offset.

        Returns:
            tuple[list[Staff] | None, int]: Staff rows and total result count.

        Raises:
            VoyagerStaleError: On HTTP 400.
            RateLimitedError: On HTTP 429.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(LinkedInVoyagerScraper.fetch_staff)
            True
        """
        ep = self.employees_ep.format(
            offset=offset,
            company_id=(
                f"(key:currentCompany,value:List({self.company_id}))," if self.company_id else ""
            ),
            count=50,
            search=f"keywords:{quote(self.search_term)}," if self.search_term else "",
            location=(f"(key:geoUrn,value:List({self.location}))," if self.location else ""),
        )
        res = await self.client.get(ep)
        if not res.ok:
            logger.debug("employees, status code - {}", res.status_code)
        self._raise_voyager_status(res)
        if not res.ok:
            return None, 0
        try:
            res_json = res.json()
        except json.JSONDecodeError:
            logger.debug(res.text)
            return None, 0
        try:
            elements = res_json["data"]["searchDashClustersByAll"]["elements"]
            total_count = res_json["data"]["searchDashClustersByAll"]["metadata"][
                "totalResultCount"
            ]
        except (KeyError, IndexError, TypeError):
            logger.debug("{}", res_json)
            return None, 0
        new_staff = self.parse_staff(elements) if elements else []
        return new_staff, total_count

    async def fetch_connections_page(self, offset: int) -> tuple[list[Staff], int] | None:
        """Fetch one page of the signed-in user's connections.

        Args:
            offset (int): Pagination offset.

        Returns:
            tuple[list[Staff], int] | None: Staff rows and total count, or ``None``.

        Raises:
            VoyagerStaleError: On HTTP 400.
            RateLimitedError: On HTTP 429.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(LinkedInVoyagerScraper.fetch_connections_page)
            True
        """
        res = await self.client.get(self.connections_ep.format(offset=offset), graphql=True)
        if not res.ok:
            logger.debug("employees, status code - {}", res.status_code)
        self._raise_voyager_status(res)
        if not res.ok:
            return None
        try:
            res_json = res.json()
        except json.JSONDecodeError:
            logger.debug(res.text)
            return None
        try:
            elements = res_json["data"]["searchDashClustersByAll"]["elements"]
            total_count = res_json["data"]["searchDashClustersByAll"]["metadata"][
                "totalResultCount"
            ]
        except (KeyError, IndexError, TypeError):
            logger.debug("{}", res_json)
            return None
        new_staff = self.parse_staff(elements) if elements else []
        return new_staff, total_count

    async def scrape_connections(
        self,
        max_results: int = 10**8,
        *,
        extra_profile_data: bool = False,
    ) -> list[Staff]:
        """Scrape the signed-in user's connections.

        Args:
            max_results (int): Maximum profiles to return.
            extra_profile_data (bool): Enrich each profile when ``True``.

        Returns:
            list[Staff]: Connection rows (capped at ``max_results``).

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(LinkedInVoyagerScraper.scrape_connections)
            True
        """
        self.search_term = "connections"
        staff_list: list[Staff] = []
        try:
            initial = await self.fetch_connections_page(0)
            if initial:
                initial_staff, total_search_result_count = initial
                if initial_staff:
                    staff_list.extend(initial_staff)
                self.num_staff = min(total_search_result_count, max_results)
                for offset in range(50, self.num_staff, 50):
                    page = await self.fetch_connections_page(offset)
                    if not page:
                        break
                    staff, _ = page
                    logger.debug(
                        "Connections from search: {} new, {} total",
                        len(staff),
                        len(staff_list) + len(staff),
                    )
                    if not staff:
                        break
                    staff_list.extend(staff)
        except (VoyagerStaleError, RateLimitedError) as exc:
            self.on_block = True
            logger.error("Exiting early due to fatal error: {}", exc)
            return staff_list[:max_results]

        reduced_staff_list = staff_list[:max_results]
        non_restricted = [row for row in reduced_staff_list if row.name != "LinkedIn Member"]
        if extra_profile_data:
            try:
                for index, employee in enumerate(non_restricted, start=1):
                    await self.fetch_all_info_for_employee(employee, index)
            except RateLimitedError as exc:
                logger.error("{}", exc)
        return reduced_staff_list

    async def fetch_location_id(self) -> None:
        """Resolve ``self.raw_location`` to a Voyager geo URN id in ``self.location``.

        Raises:
            VoyagerStaleError: On INKApi Error responses.
            GeoUrnNotFound: When the geo id cannot be resolved.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(LinkedInVoyagerScraper.fetch_location_id)
            True
        """
        ep = self.location_id_ep.format(location=quote(self.raw_location or ""))
        res = await self.client.get(ep)
        try:
            res_json = res.json()
        except json.JSONDecodeError as exc:
            if res.reason == "INKApi Error":
                raise VoyagerStaleError(
                    f"Delete session file and log in again: {res.status_code} "
                    f"{res.text[:200]} {res.reason}"
                ) from exc
            raise GeoUrnNotFound(
                f"Failed to send request to get geo id: {res.status_code} "
                f"{res.text[:200]} {res.reason}"
            ) from exc
        try:
            elems = res_json["data"]["searchDashReusableTypeaheadByType"]["elements"]
        except (KeyError, IndexError, TypeError) as exc:
            raise GeoUrnNotFound(f"Failed to locate geo id: {str(res_json)[:200]}") from exc
        geo_id = None
        if elems:
            urn = elems[0]["trackingUrn"]
            geo_match = _GEO_URN_RE.search(urn)
            if geo_match:
                geo_id = geo_match.group(1)
        if not geo_id:
            raise GeoUrnNotFound("Failed to parse geo id")
        self.location = geo_id

    async def scrape_staff(
        self,
        company_name: str | None,
        search_term: str,
        location: str,
        extra_profile_data: bool,
        max_results: int,
        block: bool,
        connect: bool,
    ) -> list[Staff]:
        """Scrape LinkedIn staff for a company, keyword, and optional location.

        Args:
            company_name (str | None): Company universal name (optional).
            search_term (str): Additional keyword filter.
            location (str): Human-readable location filter.
            extra_profile_data (bool): Enrich each profile when ``True``.
            max_results (int): Maximum profiles to return.
            block (bool): Block each enriched profile when ``True``.
            connect (bool): Send connection requests when ``True``.

        Returns:
            list[Staff]: Staff rows (capped at ``max_results``).

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(LinkedInVoyagerScraper.scrape_staff)
            True
        """
        self.search_term = search_term
        self.company_name = company_name
        self.max_results = max_results
        self.raw_location = location
        self.company_id = None

        if self.company_name:
            self.company_id, _staff_count = await self._get_company_id_and_staff_count(
                company_name or ""
            )

        staff_list: list[Staff] = []
        if self.raw_location:
            try:
                await self.fetch_location_id()
            except GeoUrnNotFound as exc:
                logger.error("{}", exc)
                return staff_list[:max_results]

        try:
            initial_staff, total_count = await self.fetch_staff(0)
            if initial_staff:
                staff_list.extend(initial_staff)
            location_suffix = f", location: '{location}'" if location else ""
            logger.info(
                "1) Search results for company: {!r}{} - {:,} staff",
                company_name,
                location_suffix,
                total_count,
            )
            self.num_staff = min(total_count, max_results, 1000)
            for offset in range(50, self.num_staff, 50):
                staff, _ = await self.fetch_staff(offset)
                logger.debug(
                    "Staff members from search: {} new, {} total",
                    len(staff or []),
                    len(staff_list) + len(staff or []),
                )
                if not staff:
                    break
                staff_list.extend(staff)
            logger.info(
                "2) Total results collected for company: {!r}{} - {} results",
                company_name,
                location_suffix,
                len(staff_list),
            )
        except (VoyagerStaleError, RateLimitedError) as exc:
            self.on_block = True
            logger.error("Exiting early due to fatal error: {}", exc)
            return staff_list[:max_results]

        reduced_staff_list = staff_list[:max_results]
        non_restricted = [row for row in reduced_staff_list if row.name != "LinkedIn Member"]
        if extra_profile_data:
            try:
                for index, employee in enumerate(non_restricted, start=1):
                    await self.fetch_all_info_for_employee(employee, index)
                    if block:
                        await self.block_user(employee)
                    elif connect:
                        await self.connect_user(employee)
            except RateLimitedError as exc:
                logger.error("{}", exc)
        return reduced_staff_list

    async def fetch_all_info_for_employee(self, employee: Staff, index: int) -> None:
        """Concurrently fetch profile enrichment sections for one employee.

        Args:
            employee (Staff): Staff row to enrich in place.
            index (int): 1-based index for logging.

        Returns:
            None

        Raises:
            RateLimitedError: When any enrichment call is rate limited.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(LinkedInVoyagerScraper.fetch_all_info_for_employee)
            True
        """
        logger.info(
            "Fetching data for account {} {:>4} / {} - {}",
            employee.id,
            index,
            self.num_staff,
            employee.profile_link,
        )
        await asyncio.gather(
            self.fetch_employee(employee, self.domain),
            self.fetch_skills(employee),
            self.fetch_experiences(employee),
            self.fetch_certifications(employee),
            self.fetch_schools(employee),
            self.fetch_employee_bio(employee),
            self.fetch_languages(employee),
        )
        if employee.is_connection:
            await self.fetch_contact_info(employee)

    async def fetch_user_profile_data_from_public_id(
        self, user_id: str, key: str
    ) -> tuple[Any, str] | str:
        """Fetch a nested profile field and the member URN for a public id.

        Args:
            user_id (str): LinkedIn public profile id.
            key (str): One of ``user_id`` or ``company_id``.

        Returns:
            tuple[Any, str] | str: Field value and URN, or ``""`` when user id missing.

        Raises:
            RecipeError: When JSON or keys cannot be resolved.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(LinkedInVoyagerScraper.fetch_user_profile_data_from_public_id)
            True
        """
        endpoint = self.public_user_id_ep.format(user_id=user_id)
        response = await self.client.get(endpoint)
        try:
            response_json = response.json()
        except json.JSONDecodeError as exc:
            logger.debug(response.text[:200])
            msg = f"Failed to load JSON from endpoint {response.status_code} {response.reason}"
            raise RecipeError(msg) from exc
        keys: dict[str, tuple[str | int, ...]] = {
            "user_id": ("positionView", "profileId"),
            "company_id": (
                "positionView",
                "elements",
                0,
                "company",
                "miniCompany",
                "universalName",
            ),
        }
        path = keys.get(key)
        if path is None:
            msg = f"unknown profile key {key!r}"
            raise RecipeError(msg)
        try:
            data: Any = response_json
            for part in path:
                data = data[part]
            urn = response_json["profile"]["miniProfile"]["objectUrn"].split(":")[-1]
            return data, urn
        except (KeyError, TypeError, IndexError) as exc:
            logger.warning("Failed to find user_id {}", user_id)
            if key == "user_id":
                return ""
            msg = f"Failed to fetch {key!r} for user_id {user_id}: {exc}"
            raise RecipeError(msg) from exc

    async def block_user(self, employee: Staff) -> None:
        """Block a user on LinkedIn given their member URN.

        Args:
            employee (Staff): Staff row with ``urn`` set.

        Returns:
            None

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(LinkedInVoyagerScraper.block_user)
            True
        """
        if employee.urn == "headless":
            return
        urn_string = f"urn:li:member:{employee.urn}"
        length_byte = bytes([len(urn_string)])
        body = b"\x00\x01\x14\nblockeeUrn\x14" + length_byte + urn_string.encode()
        res = await self.client.post(
            self.block_user_ep,
            body,
            "application/x-protobuf2; symbol-table=voyager-20757",
        )
        if res.ok:
            logger.info("Successfully blocked user {}", employee.id)
        elif res.status_code == 403:
            logger.warning(
                "Failed to block user - status code 403, one possible reason is you have "
                "already blocked/unblocked this person in past 48 hours and on cooldown: {}",
                employee.profile_link,
            )
        else:
            logger.warning(
                "Failed to block user - status code {} {}: {}",
                res.status_code,
                employee.id,
                employee.name,
            )

    async def connect_user(self, employee: Staff) -> None:
        """Send a connection request to a user given their profile id.

        Args:
            employee (Staff): Staff row with ``id`` and connection state.

        Returns:
            None

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(LinkedInVoyagerScraper.connect_user)
            True
        """
        if self.connect_block:
            logger.info(
                "Skipping connection request for user due to previous block: {} - {}",
                employee.id,
                employee.profile_link,
            )
            return
        if employee.urn == "headless":
            return
        if employee.is_connection != "no":
            logger.info(
                "Already connected or pending connection request to user {} - {}",
                employee.id,
                employee.profile_link,
            )
            return
        body = (
            b"\x00\x01\x03\xe2\x05\x00\x01\x03\xd3w\x00\x01\x03\xd5\x06\x14:urn:li:fsd_profile:"
            + employee.id.encode()
        )
        res = await self.client.post(
            self.connect_to_user_ep,
            body,
            "application/x-protobuf2; symbol-table=voyager-20757",
        )
        if res.ok:
            logger.info(
                "Successfully sent connection request to user {} - {}",
                employee.id,
                employee.profile_link,
            )
        elif res.status_code == 429:
            self.connect_block = True
            logger.warning(
                "Failed to connect to user - status code 429 - pausing connection "
                "requests for this scrape: {} - {}",
                employee.id,
                employee.profile_link,
            )
        else:
            logger.warning(
                "Failed to connect to user - status code {} {} - {}",
                res.status_code,
                employee.id,
                employee.profile_link,
            )

    async def fetch_employee(self, base_staff: Staff, domain: str | None) -> bool:
        """Fetch top-card profile fields for ``base_staff``.

        Args:
            base_staff (Staff): Staff row to enrich in place.
            domain (str | None): Company email domain for guessed addresses.

        Returns:
            bool: ``True`` when profile data was parsed.

        Raises:
            RateLimitedError: On HTTP 429.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(LinkedInVoyagerScraper.fetch_employee)
            True
        """
        ep = self._employee_ep.format(employee_id=base_staff.id)
        res = await self.client.get(ep)
        logger.debug("basic info, status code - {}", res.status_code)
        self._raise_rate_limit(res)
        if not res.ok:
            logger.debug(res.text[:200])
            return False
        try:
            res_json = res.json()
        except json.JSONDecodeError:
            logger.debug(res.text[:200])
            return False
        try:
            employee_json = res_json["elements"][0]
        except (KeyError, IndexError, TypeError):
            logger.debug("{}", res_json)
            return False
        self._parse_employee(base_staff, employee_json, domain)
        return True

    def _photo_url(self, emp_dict: dict[str, Any], key: str) -> str | None:
        """Return a profile or banner photo URL from a Voyager profile dict.

        Args:
            emp_dict (dict[str, Any]): See implementation.
            key (str): See implementation.

        Returns:
            str | None: See implementation.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(LinkedInVoyagerScraper._photo_url)
            True
        """
        try:
            photo_data = emp_dict[key]["displayImageReference"]["vectorImage"]
            photo_base_url = photo_data["rootUrl"]
            photo_ext_url = photo_data["artifacts"][-1]["fileIdentifyingUrlPathSegment"]
            return f"{photo_base_url}{photo_ext_url}"
        except (KeyError, TypeError, IndexError, ValueError):
            return None

    def _parse_employee(self, emp: Staff, emp_dict: dict[str, Any], domain: str | None) -> None:
        """Parse top-card employee fields onto ``emp``.

        Args:
            emp (Staff): See implementation.
            emp_dict (dict[str, Any]): See implementation.
            domain (str | None): See implementation.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(LinkedInVoyagerScraper._parse_employee)
            True
        """
        emp.profile_photo = self._photo_url(emp_dict, "profilePicture")
        emp.banner_photo = self._photo_url(emp_dict, "backgroundPicture")
        emp.profile_id = emp_dict["publicIdentifier"]
        try:
            emp.headline = emp_dict.get("headline")
            if not emp.headline:
                emp.headline = emp_dict["memberRelationship"]["memberRelationshipData"][
                    "noInvitation"
                ]["targetInviteeResolutionResult"]["headline"]
        except (KeyError, TypeError):
            pass
        union_type = next(iter(emp_dict["memberRelationship"]["memberRelationshipUnion"]))
        emp.is_connection = "no"
        if union_type == "connection":
            emp.is_connection = "yes"
        elif union_type == "noConnection":
            invitation = (
                emp_dict["memberRelationship"]["memberRelationshipUnion"]["noConnection"]
                .get("invitationUnion", {})
                .get("invitation", {})
            )
            if invitation and invitation.get("invitationState") == "PENDING":
                emp.is_connection = "pending"

        profile_picture = emp_dict.get("profilePicture") or {}
        emp.open_to_work = profile_picture.get("frameType") == "OPEN_TO_WORK"
        emp.is_hiring = profile_picture.get("frameType") == "HIRING"
        emp.first_name = emp_dict["firstName"]
        emp.last_name = emp_dict["lastName"].split(",")[0]
        if not emp.name:
            emp.name = " ".join(filter(None, [emp.first_name, emp.last_name]))
        emp.potential_emails = (
            create_emails(emp.first_name or "", emp.last_name or "", domain) if domain else None
        )
        emp.followers = emp_dict.get("followingState", {}).get("followerCount")
        emp.connections = emp_dict["connections"]["paging"]["total"]
        emp.location = emp_dict.get("geoLocation", {}).get("geo", {}).get("defaultLocalizedName")
        top_positions = emp_dict.get("profileTopPosition", {}).get("elements", [])
        emp.company = top_positions[0].get("companyName") if top_positions else None
        edu_cards = emp_dict.get("profileTopEducation", {}).get("elements", [])
        if edu_cards:
            emp.school = edu_cards[0].get("schoolName", edu_cards[0].get("school", {}).get("name"))
        emp.influencer = emp_dict.get("influencer", False)
        emp.creator = emp_dict.get("creator", False)
        emp.premium = emp_dict.get("premium", False)
        emp.mutual_connections = 0
        try:
            profile_insight = emp_dict.get("profileInsight", {}).get("elements", [])
            if profile_insight:
                mutual_connections_str = profile_insight[0]["text"]["text"]
                match = _MUTUAL_COUNT_RE.search(mutual_connections_str)
                if match:
                    emp.mutual_connections = int(match.group()) + 2
                else:
                    emp.mutual_connections = 2 if " and " in mutual_connections_str else 1
        except (KeyError, TypeError, IndexError, ValueError):
            pass

    async def fetch_skills(self, staff: Staff) -> bool:
        """Fetch endorsed skills for ``staff``.

        Args:
            staff (Staff): Staff row to enrich in place.

        Returns:
            bool: ``True`` when skills were parsed.

        Raises:
            RateLimitedError: On HTTP 429.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(LinkedInVoyagerScraper.fetch_skills)
            True
        """
        ep = self._skills_ep.format(employee_id=staff.id)
        res = await self.client.get(ep)
        logger.debug("skills, status code - {}", res.status_code)
        self._raise_rate_limit(res)
        if not res.ok:
            logger.debug(res.text[:200])
            return False
        try:
            res_json = res.json()
        except json.JSONDecodeError:
            logger.debug(res.text[:200])
            return False
        if res_json.get("errors"):
            return False
        tab_comp = res_json["data"]["identityDashProfileComponentsBySectionType"]["elements"][0][
            "components"
        ]["tabComponent"]
        if tab_comp:
            sections = tab_comp["sections"]
            staff.skills = self._parse_skills(sections)
        return True

    def _parse_skills(self, sections: list[dict[str, Any]]) -> list[Skill]:
        """Parse skill tab sections into :class:`Skill` rows.

        Args:
            sections (list[dict[str, Any]]): See implementation.

        Returns:
            list[Skill]: See implementation.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(LinkedInVoyagerScraper._parse_skills)
            True
        """
        names: set[str] = set()
        skills: list[Skill] = []
        for section in sections:
            elems = section["subComponent"]["components"]["pagedListComponent"]["components"][
                "elements"
            ]
            for elem in elems:
                passed_assessment: bool | None = None
                endorsements = 0
                entity = elem["components"]["entityComponent"]
                name = entity["titleV2"]["text"]["text"]
                if name in names:
                    continue
                names.add(name)
                components = entity["subComponents"]["components"]
                for component in components:
                    try:
                        candidate = component["components"]["insightComponent"]["text"]["text"][
                            "text"
                        ]
                        if " endorsements" in candidate:
                            endorsements = int(candidate.replace(" endorsements", ""))
                        if "Passed LinkedIn Skill Assessment" in candidate:
                            passed_assessment = True
                    except (KeyError, TypeError):
                        pass
                skills.append(
                    Skill(
                        name=name,
                        endorsements=endorsements,
                        passed_assessment=passed_assessment,
                    )
                )
        return skills

    async def fetch_experiences(self, staff: Staff) -> bool:
        """Fetch work experience for ``staff``.

        Args:
            staff (Staff): Staff row to enrich in place.

        Returns:
            bool: ``True`` when experiences were parsed.

        Raises:
            VoyagerStaleError: On INKApi Error responses.
            RateLimitedError: On HTTP 429.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(LinkedInVoyagerScraper.fetch_experiences)
            True
        """
        ep = self._experiences_ep.format(employee_id=staff.id)
        res = await self.client.get(ep)
        logger.debug("exps, status code - {}", res.status_code)
        if res.reason == "INKApi Error":
            raise VoyagerStaleError(
                f"Delete session file and log in again: {res.status_code} "
                f"{res.text[:200]} {res.reason}"
            )
        self._raise_rate_limit(res)
        if not res.ok:
            logger.debug(res.text[:200])
            return False
        try:
            res_json = res.json()
        except json.JSONDecodeError:
            logger.debug(res.text[:200])
            return False
        try:
            skills_json = res_json["data"]["identityDashProfileComponentsBySectionType"][
                "elements"
            ][0]["components"]["pagedListComponent"]["components"]["elements"]
        except (KeyError, IndexError, TypeError):
            logger.debug("{}", res_json)
            return False
        staff.experiences = self._parse_experiences(skills_json)
        return True

    def _parse_experiences(self, elements: list[dict[str, Any]]) -> list[Experience]:
        """Parse experience section elements into :class:`Experience` rows.

        Args:
            elements (list[dict[str, Any]]): See implementation.

        Returns:
            list[Experience]: See implementation.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(LinkedInVoyagerScraper._parse_experiences)
            True
        """
        exps: list[Experience] = []
        for elem in elements:
            try:
                components = elem.get("components")
                if components is None:
                    continue
                entity = components.get("entityComponent")
                if entity is None:
                    continue
                sub_components = entity.get("subComponents")
                if (
                    sub_components is None
                    or len(sub_components.get("components", [])) == 0
                    or sub_components["components"][0].get("components") is None
                    or sub_components["components"][0]["components"].get("pagedListComponent")
                    is None
                ):
                    emp_type = None
                    start_date = None
                    end_date = None
                    caption = entity.get("caption")
                    duration = caption.get("text") if caption else None
                    if duration:
                        start_date, end_date = parse_dates(duration)
                        from_date, _to_date = parse_duration(duration)
                        if from_date:
                            duration_parts = duration.split(" · ")
                            if len(duration_parts) > 1:
                                duration = duration_parts[1]
                    subtitle = entity.get("subtitle")
                    company = subtitle.get("text") if subtitle else None
                    title_v2 = entity.get("titleV2")
                    title_text = title_v2.get("text") if title_v2 else None
                    title = title_text.get("text") if title_text else None
                    metadata = entity.get("metadata")
                    location = metadata.get("text") if metadata else None
                    if company:
                        parts = company.split(" · ")
                        if len(parts) > 1:
                            company = parts[0]
                            emp_type = parts[-1].lower()
                    exps.append(
                        Experience(
                            duration=duration,
                            title=title,
                            company=company,
                            emp_type=emp_type,
                            start_date=start_date,
                            end_date=end_date,
                            location=location,
                        )
                    )
                else:
                    exps.extend(self._parse_multi_exp(entity))
            except Exception as exc:
                logger.exception(exc)
        return exps

    def _parse_multi_exp(self, entity: dict[str, Any]) -> list[Experience]:
        """Parse a grouped multi-role experience block.

        Args:
            entity (dict[str, Any]): See implementation.

        Returns:
            list[Experience]: See implementation.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(LinkedInVoyagerScraper._parse_multi_exp)
            True
        """
        exps: list[Experience] = []
        company = entity["titleV2"]["text"]["text"]
        elements = entity["subComponents"]["components"][0]["components"]["pagedListComponent"][
            "components"
        ]["elements"]
        for elem in elements:
            role = elem["components"]["entityComponent"]
            duration = role["caption"]["text"]
            title = role["titleV2"]["text"]["text"]
            emp_type = role["subtitle"]["text"].lower() if role["subtitle"] else None
            location = role["metadata"]["text"] if role["metadata"] else None
            start_date, end_date = parse_dates(duration)
            from_date, _to_date = parse_duration(duration)
            if from_date:
                duration = duration.split(" · ")[1]
            exps.append(
                Experience(
                    duration=duration,
                    title=title,
                    company=company,
                    emp_type=emp_type,
                    start_date=start_date,
                    end_date=end_date,
                    location=location,
                )
            )
        return exps

    async def fetch_certifications(self, staff: Staff) -> bool:
        """Fetch certifications for ``staff``.

        Args:
            staff (Staff): Staff row to enrich in place.

        Returns:
            bool: ``True`` when certifications were parsed.

        Raises:
            RateLimitedError: On HTTP 429.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(LinkedInVoyagerScraper.fetch_certifications)
            True
        """
        ep = self._certifications_ep.format(employee_id=staff.id)
        res = await self.client.get(ep)
        logger.debug("certs, status code - {}", res.status_code)
        self._raise_rate_limit(res)
        if not res.ok:
            logger.debug(res.text[:200])
            return False
        try:
            res_json = res.json()
        except json.JSONDecodeError:
            logger.debug(res.text[:200])
            return False
        try:
            elems = res_json["data"]["identityDashProfileComponentsBySectionType"]["elements"]
        except (KeyError, IndexError, TypeError):
            logger.debug("{}", res_json)
            return False
        if elems:
            cert_elems = elems[0]["components"]["pagedListComponent"]["components"]["elements"]
            staff.certifications = self._parse_certifications(cert_elems)
        return True

    def _parse_certifications(self, sections: list[dict[str, Any]]) -> list[Certification]:
        """Parse certification section elements.

        Args:
            sections (list[dict[str, Any]]): See implementation.

        Returns:
            list[Certification]: See implementation.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(LinkedInVoyagerScraper._parse_certifications)
            True
        """
        certs: list[Certification] = []
        for section in sections:
            elem = section["components"]["entityComponent"]
            if not elem:
                break
            title = elem["titleV2"]["text"]["text"]
            issuer = elem["subtitle"]["text"] if elem["subtitle"] else None
            date_issued = (
                elem["caption"]["text"].replace("Issued ", "") if elem["caption"] else None
            )
            cert_id = (
                elem["metadata"]["text"].replace("Credential ID ", "") if elem["metadata"] else None
            )
            try:
                subcomp = elem["subComponents"]["components"][0]
                cert_link = subcomp["components"]["actionComponent"]["action"]["navigationAction"][
                    "actionTarget"
                ]
            except (KeyError, TypeError, IndexError):
                cert_link = None
            certs.append(
                Certification(
                    title=title,
                    issuer=issuer,
                    date_issued=date_issued,
                    cert_link=cert_link,
                    cert_id=cert_id,
                )
            )
        return certs

    async def fetch_schools(self, staff: Staff) -> bool:
        """Fetch education history for ``staff``.

        Args:
            staff (Staff): Staff row to enrich in place.

        Returns:
            bool: ``True`` when schools were parsed.

        Raises:
            RateLimitedError: On HTTP 429.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(LinkedInVoyagerScraper.fetch_schools)
            True
        """
        ep = self._schools_ep.format(employee_id=staff.id)
        res = await self.client.get(ep)
        logger.debug("schools, status code - {}", res.status_code)
        self._raise_rate_limit(res)
        if not res.ok:
            logger.debug(res.text[:200])
            return False
        try:
            res_json = res.json()
        except json.JSONDecodeError:
            logger.debug(res.text[:200])
            return False
        try:
            elements = res_json["data"]["identityDashProfileComponentsBySectionType"]["elements"][
                0
            ]["components"]["pagedListComponent"]["components"]["elements"]
        except (KeyError, IndexError, TypeError):
            logger.debug("{}", res_json)
            return False
        staff.schools = self._parse_schools(elements)
        return True

    def _parse_schools(self, elements: list[dict[str, Any]]) -> list[School]:
        """Parse education section elements.

        Args:
            elements (list[dict[str, Any]]): See implementation.

        Returns:
            list[School]: See implementation.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(LinkedInVoyagerScraper._parse_schools)
            True
        """
        schools: list[School] = []
        start: date | None = None
        end: date | None = None
        for elem in elements:
            entity = elem["components"]["entityComponent"]
            if not entity:
                break
            years = entity["caption"]["text"] if entity["caption"] else None
            school_name = entity["titleV2"]["text"]["text"]
            if years:
                start, end = parse_dates(years)
            degree = entity["subtitle"]["text"] if entity["subtitle"] else None
            schools.append(
                School(start_date=start, end_date=end, school=school_name, degree=degree)
            )
        return schools

    async def fetch_employee_bio(self, base_staff: Staff) -> bool:
        """Fetch the about/bio text for ``base_staff``.

        Args:
            base_staff (Staff): Staff row to enrich in place.

        Returns:
            bool: ``True`` when a bio was parsed.

        Raises:
            RateLimitedError: On HTTP 429.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(LinkedInVoyagerScraper.fetch_employee_bio)
            True
        """
        ep = self._bio_ep.format(employee_id=base_staff.id)
        res = await self.client.get(ep)
        logger.debug("bio info, status code - {}", res.status_code)
        self._raise_rate_limit(res)
        if not res.ok:
            logger.debug(res.text)
            return False
        try:
            data = res.json()
        except json.JSONDecodeError:
            logger.debug(res.text)
            return False
        try:
            base_staff.bio = data["data"]["identityDashProfileCardsByInitialCards"]["elements"][3][
                "topComponents"
            ][1]["components"]["textComponent"]["text"]["text"]
        except (KeyError, IndexError, TypeError):
            return False
        return True

    async def fetch_languages(self, staff: Staff) -> bool:
        """Fetch spoken languages for ``staff``.

        Args:
            staff (Staff): Staff row to enrich in place.

        Returns:
            bool: ``True`` when languages were parsed.

        Raises:
            RateLimitedError: On HTTP 429.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(LinkedInVoyagerScraper.fetch_languages)
            True
        """
        ep = self._languages_ep.format(employee_id=staff.id)
        res = await self.client.get(ep)
        logger.debug("skills, status code - {}", res.status_code)
        self._raise_rate_limit(res)
        if not res.ok:
            logger.debug(res.text)
            return False
        try:
            res_json = res.json()
        except json.JSONDecodeError:
            logger.debug(res.text)
            return False
        if res_json.get("errors"):
            return False
        staff.languages = self._parse_languages(res_json)
        return True

    def _parse_languages(self, language_json: dict[str, Any]) -> list[str]:
        """Parse language section JSON into a list of language names.

        Args:
            language_json (dict[str, Any]): See implementation.

        Returns:
            list[str]: See implementation.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(LinkedInVoyagerScraper._parse_languages)
            True
        """
        languages: list[str] = []
        elements = language_json["data"]["identityDashProfileComponentsBySectionType"]["elements"][
            0
        ]["components"]["pagedListComponent"]["components"]["elements"]
        for element in elements:
            comp = element["components"]["entityComponent"]
            if comp:
                title = comp["titleV2"]["text"]["text"]
                languages.append(title)
        return languages

    async def fetch_contact_info(self, base_staff: Staff) -> bool:
        """Fetch connection contact info for ``base_staff``.

        Args:
            base_staff (Staff): Staff row to enrich in place.

        Returns:
            bool: ``True`` when contact info was parsed.

        Raises:
            RateLimitedError: On HTTP 429.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(LinkedInVoyagerScraper.fetch_contact_info)
            True
        """
        ep = self._contact_ep.format(employee_id=base_staff.id)
        res = await self.client.get(ep)
        logger.debug("bio info, status code - {}", res.status_code)
        self._raise_rate_limit(res)
        if not res.ok:
            logger.debug(res.text)
            return False
        try:
            employee_json = res.json()
        except json.JSONDecodeError:
            logger.debug(res.text)
            return False
        self._parse_contact_info(base_staff, employee_json)
        return True

    def _parse_contact_info(self, emp: Staff, emp_dict: dict[str, Any]) -> None:
        """Parse contact-info fields onto ``emp.contact_info``.

        Args:
            emp (Staff): See implementation.
            emp_dict (dict[str, Any]): See implementation.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(LinkedInVoyagerScraper._parse_contact_info)
            True
        """
        contact_info = ContactInfo()
        profile = emp_dict["data"]["identityDashProfilesByMemberIdentity"]["elements"][0]
        with contextlib.suppress(KeyError, TypeError):
            contact_info.email_address = profile["emailAddress"]["emailAddress"]
        with contextlib.suppress(KeyError, TypeError):
            contact_info.address = profile["address"]
        try:
            month = month_name[profile["birthDateOn"]["month"]]
            day = profile["birthDateOn"]["day"]
            contact_info.birthday = f"{month} {day}"
        except (KeyError, TypeError):
            pass
        with contextlib.suppress(KeyError, TypeError):
            contact_info.websites = [item["url"] for item in profile["websites"]]
        with contextlib.suppress(KeyError, TypeError):
            contact_info.phone_numbers = [
                item["phoneNumber"]["number"] for item in profile["phoneNumbers"]
            ]
        try:
            created_at = profile["memberRelationship"]["memberRelationshipDataResolutionResult"][
                "connection"
            ]["createdAt"]
            dt = datetime.fromtimestamp(created_at / 1000, tz=timezone.utc)  # noqa: UP017
            contact_info.created_at = dt.strftime("%Y-%m-%d %H:%M:%S %Z")
        except (KeyError, TypeError):
            pass
        emp.contact_info = contact_info

    async def scrape_users(
        self,
        user_ids: list[str],
        *,
        extra_profile_data: bool = True,
        block: bool = False,
        connect: bool = False,
    ) -> list[Staff]:
        """Scrape LinkedIn profiles by public profile id slug.

        Args:
            user_ids (list[str]): See implementation.
            extra_profile_data (bool): See implementation.
            block (bool): See implementation.
            connect (bool): See implementation.

        Returns:
            list[Staff]: See implementation.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(LinkedInVoyagerScraper.scrape_users)
            True
        """
        self.num_staff = len(user_ids)
        users = [
            Staff(
                id="",
                search_term="manual",
                profile_id=user_id,
                profile_link=f"https://www.linkedin.com/in/{user_id}",
            )
            for user_id in user_ids
        ]
        for index, user in enumerate(users, start=1):
            profile_data = await self.fetch_user_profile_data_from_public_id(
                user.profile_id or "", "user_id"
            )
            if isinstance(profile_data, str):
                # "" (or a bare id string) means the member urn could not be resolved;
                # skip enrichment — the final filter drops users without an id.
                continue
            user_id, urn = profile_data
            user.id = user_id
            user.urn = urn
            if user.id and extra_profile_data:
                await self.fetch_all_info_for_employee(user, index)
                if block:
                    await self.block_user(user)
                elif connect:
                    await self.connect_user(user)
        return [user for user in users if user.id]


__all__ = [
    "LINKEDIN_EGRESS",
    "GeoUrnNotFound",
    "LinkedInVoyagerScraper",
    "RateLimitedError",
    "VoyagerClient",
    "VoyagerStaleError",
]
