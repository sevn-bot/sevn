"""LinkedIn Voyager data models and pure parse helpers (ported from StaffSpy).

StaffSpy upstream: https://github.com/cullenwatson/StaffSpy (MIT) @ 0a8a8d73.

Module: sevn.browser.recipes.linkedin_models
Depends: datetime, re, pydantic, loguru

Exports:
    Staff — pydantic staff/connection profile row.
    Experience — pydantic work-experience row.
    School — pydantic education row.
    Skill — pydantic skill-endorsement row.
    Certification — pydantic certification row.
    ContactInfo — pydantic contact-info row.
    Comment — pydantic post-comment row.
    extract_emails_from_text — find email addresses in free text.
    create_emails — guess corporate email patterns from a name + domain.
    extract_base_domain — strip a URL to registrable domain suffix.
    parse_company_data — parse a Voyager company JSON payload to a dict.
    parse_date — parse a single ``May 2018`` / ``2018`` token.
    parse_dates — parse a start/end LinkedIn duration string.
    parse_duration — parse a ``Jan 2020 - Present · 4 yrs`` duration string.
    staff_rows_to_dicts — convert staff models to dict rows (hidden rows last).

Examples:
    >>> from sevn.browser.recipes.linkedin_models import extract_emails_from_text
    >>> extract_emails_from_text("reach me at ann@example.com")
    ['ann@example.com']
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import urlparse

from loguru import logger
from pydantic import BaseModel, ConfigDict

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_DATE_TOKEN_RE = re.compile(r"(\b\w+ \d{4}|\b\d{4}|\bPresent)")


class Comment(BaseModel):
    """LinkedIn post comment row."""

    model_config = ConfigDict(extra="ignore")

    post_id: str
    comment_id: str | None = None
    internal_profile_id: str | None = None
    public_profile_id: str | None = None
    name: str | None = None
    text: str | None = None
    num_likes: int | None = None
    created_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict.

        Returns:
            dict[str, Any]: See implementation.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(Comment.to_dict)
            True
        """
        return {
            "post_id": self.post_id,
            "comment_id": self.comment_id,
            "internal_profile_id": self.internal_profile_id,
            "public_profile_id": self.public_profile_id,
            "name": self.name,
            "text": self.text,
            "num_likes": self.num_likes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class School(BaseModel):
    """Education row."""

    model_config = ConfigDict(extra="ignore")

    start_date: date | None = None
    end_date: date | None = None
    school: str | None = None
    degree: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict.

        Returns:
            dict[str, Any]: See implementation.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(School.to_dict)
            True
        """
        return {
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "school": self.school,
            "degree": self.degree,
        }


class Skill(BaseModel):
    """Skill endorsement row."""

    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    endorsements: int | None = None
    passed_assessment: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict.

        Returns:
            dict[str, Any]: See implementation.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(Skill.to_dict)
            True
        """
        return {
            "name": self.name,
            "endorsements": self.endorsements if self.endorsements else 0,
            "passed_assessment": self.passed_assessment,
        }


class ContactInfo(BaseModel):
    """Connection contact-info row."""

    model_config = ConfigDict(extra="ignore")

    email_address: str | None = None
    websites: list[str] | None = None
    phone_numbers: list[str] | None = None
    address: str | None = None
    birthday: str | None = None
    created_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict.

        Returns:
            dict[str, Any]: See implementation.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(ContactInfo.to_dict)
            True
        """
        return {
            "email_address": self.email_address,
            "websites": self.websites,
            "phone_numbers": self.phone_numbers,
            "address": self.address,
            "birthday": self.birthday,
            "created_at": self.created_at,
        }


class Certification(BaseModel):
    """Certification row."""

    model_config = ConfigDict(extra="ignore")

    title: str | None = None
    issuer: str | None = None
    date_issued: str | None = None
    cert_id: str | None = None
    cert_link: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict.

        Returns:
            dict[str, Any]: See implementation.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(Certification.to_dict)
            True
        """
        return {
            "title": self.title,
            "issuer": self.issuer,
            "date_issued": self.date_issued,
            "cert_id": self.cert_id,
            "cert_link": self.cert_link,
        }


class Experience(BaseModel):
    """Work experience row."""

    model_config = ConfigDict(extra="ignore")

    duration: str | None = None
    title: str | None = None
    company: str | None = None
    location: str | None = None
    emp_type: str | None = None
    start_date: date | None = None
    end_date: date | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict.

        Returns:
            dict[str, Any]: See implementation.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(Experience.to_dict)
            True
        """
        return {
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "duration": self.duration,
            "title": self.title,
            "company": self.company,
            "location": self.location,
            "emp_type": self.emp_type,
        }


class Staff(BaseModel):
    """LinkedIn staff / connection profile row."""

    model_config = ConfigDict(extra="ignore")

    urn: str | None = None
    search_term: str
    id: str
    name: str | None = None
    headline: str | None = None
    current_position: str | None = None
    profile_id: str | None = None
    profile_link: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    potential_emails: list[str] | None = None
    bio: str | None = None
    emails_in_bio: list[str] | None = None
    followers: int | None = None
    connections: int | None = None
    mutual_connections: int | None = None
    is_connection: str | None = None
    location: str | None = None
    company: str | None = None
    school: str | None = None
    influencer: bool | None = None
    creator: bool | None = None
    premium: bool | None = None
    open_to_work: bool | None = None
    is_hiring: bool | None = None
    profile_photo: str | None = None
    banner_photo: str | None = None
    skills: list[Skill] | None = None
    experiences: list[Experience] | None = None
    certifications: list[Certification] | None = None
    contact_info: ContactInfo | None = None
    schools: list[School] | None = None
    languages: list[str] | None = None

    def get_top_skills(self) -> list[str | None]:
        """Return up to three top skill names by endorsement count.

        Returns:
            list[str | None]: See implementation.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(Staff.get_top_skills)
            True
        """
        top: list[str | None] = []
        if self.skills:
            sorted_skills = sorted(
                self.skills, key=lambda item: item.endorsements or 0, reverse=True
            )
            top = [skill.name for skill in sorted_skills[:3]]
        top.extend([None] * (3 - len(top)))
        return top[:3]

    def estimate_age_based_on_education(self) -> int | None:
        """Estimate age from first college start date (+18 years).

        Returns:
            int | None: See implementation.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(Staff.estimate_age_based_on_education)
            True
        """
        college_words = ("uni", "college")
        sorted_schools = (
            sorted(
                [school for school in self.schools if school.start_date],
                key=lambda item: item.start_date or date.min,
            )
            if self.schools
            else []
        )
        today = datetime.now(tz=UTC).date()
        for school in sorted_schools:
            school_name = (school.school or "").lower()
            if (
                any(word in school_name for word in college_words) or school.degree
            ) and school.start_date:
                years = (today - school.start_date).days // 365
                return int(18 + years)
        return None

    def to_dict(self) -> dict[str, Any]:
        """Return the StaffSpy-compatible flat dict shape.

        Returns:
            dict[str, Any]: See implementation.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(Staff.to_dict)
            True
        """
        sorted_schools = (
            sorted(
                self.schools,
                key=lambda item: (item.end_date is None, item.end_date),
                reverse=True,
            )
            if self.schools
            else []
        )
        top_school_names = [school.school for school in sorted_schools[:3]]
        top_school_names.extend([None] * (3 - len(top_school_names)))

        sorted_experiences = (
            sorted(
                self.experiences,
                key=lambda item: (item.end_date is None, item.end_date),
                reverse=True,
            )
            if self.experiences
            else []
        )

        top_companies: list[str | None] = []
        seen: set[str | None] = set()
        for exp in sorted_experiences:
            if exp.company not in seen:
                top_companies.append(exp.company)
                seen.add(exp.company)
            if len(top_companies) == 3:
                break
        top_companies.extend([None] * (3 - len(top_companies)))

        top_skills = self.get_top_skills()
        bio_emails = extract_emails_from_text(self.bio) if self.bio else None
        current_position = (
            sorted_experiences[0].title
            if sorted_experiences and sorted_experiences[0].end_date is None
            else None
        )
        contact = self.contact_info.to_dict() if self.contact_info else {}
        return {
            "search_term": self.search_term,
            "id": self.id,
            "urn": self.urn,
            "profile_link": self.profile_link,
            "profile_id": self.profile_id,
            "name": self.name,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "location": self.location,
            "headline": self.headline,
            "estimated_age": self.estimate_age_based_on_education(),
            "followers": self.followers,
            "connections": self.connections,
            "mutuals": self.mutual_connections,
            "is_connection": self.is_connection,
            "premium": self.premium,
            "creator": self.creator,
            "influencer": self.influencer,
            "open_to_work": self.open_to_work,
            "is_hiring": self.is_hiring,
            "current_position": current_position,
            "current_company": top_companies[0],
            "past_company_1": top_companies[1],
            "past_company_2": top_companies[2],
            "school_1": top_school_names[0],
            "school_2": top_school_names[1],
            "top_skill_1": top_skills[0],
            "top_skill_2": top_skills[1],
            "top_skill_3": top_skills[2],
            "bio": self.bio,
            "experiences": (
                [exp.to_dict() for exp in self.experiences] if self.experiences else None
            ),
            "schools": ([school.to_dict() for school in self.schools] if self.schools else None),
            "skills": ([skill.to_dict() for skill in self.skills] if self.skills else None),
            "certifications": (
                [cert.to_dict() for cert in self.certifications] if self.certifications else None
            ),
            "languages": self.languages,
            "emails_in_bio": ", ".join(bio_emails) if bio_emails else None,
            "potential_emails": self.potential_emails,
            "profile_photo": self.profile_photo,
            "banner_photo": self.banner_photo,
            "connection_created_at": contact.get("created_at"),
            "connection_email": contact.get("email_address"),
            "connection_phone_numbers": contact.get("phone_numbers"),
            "connection_websites": contact.get("websites"),
            "connection_street_address": contact.get("address"),
            "connection_birthday": contact.get("birthday"),
        }


def extract_emails_from_text(text: str) -> list[str] | None:
    """Return email addresses found in ``text``.

    Args:
        text (str): See implementation.

    Returns:
        list[str] | None: See implementation.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(extract_emails_from_text)
        True
    """
    if not text:
        return None
    return _EMAIL_RE.findall(text)


def extract_base_domain(url: str) -> str | None:
    """Return ``domain.tld`` from a company page URL.

    Args:
        url (str): See implementation.

    Returns:
        str | None: See implementation.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(extract_base_domain)
        True
    """
    host = urlparse(url).hostname or ""
    if not host:
        return None
    parts = host.lower().split(".")
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return host


def create_emails(first: str, last: str, domain: str) -> list[str]:
    """Guess common corporate email patterns for a person at ``domain``.

    Args:
        first (str): See implementation.
        last (str): See implementation.
        domain (str): See implementation.

    Returns:
        list[str]: See implementation.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(create_emails)
        True
    """
    first_clean = "".join(ch for ch in first if ch.isalpha()).lower()
    last_clean = "".join(ch for ch in last if ch.isalpha()).lower()
    if not first_clean or not last_clean or not domain:
        return []
    return [
        f"{first_clean}.{last_clean}@{domain}",
        f"{first_clean[:1]}{last_clean}@{domain}",
        f"{first_clean[:2]}{last_clean}@{domain}",
        f"{first_clean}{last_clean[:1]}@{domain}",
        f"{first_clean}{last_clean[:2]}@{domain}",
    ]


def _parse_month_year(token: str) -> date | None:
    """Parse a ``May 2018`` or ``2018`` token to a date (first of month).

    Args:
        token (str): Raw month-year or year token.

    Returns:
        date | None: Parsed date, or ``None`` when the token does not match.

    Examples:
        >>> _parse_month_year("2018") is not None
        True
        >>> _parse_month_year("not a date") is None
        True
    """
    for fmt in ("%b %Y", "%Y"):
        try:
            parsed = datetime.strptime(token.strip(), fmt).replace(tzinfo=UTC)
            return parsed.date()
        except ValueError:
            continue
    return None


def parse_date(date_str: str) -> date | None:
    """Parse ``May 2018`` or ``2018`` style tokens.

    Args:
        date_str (str): See implementation.

    Returns:
        date | None: See implementation.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(parse_date)
        True
    """
    return _parse_month_year(date_str)


def parse_dates(date_str: str) -> tuple[date | None, date | None]:
    """Parse a LinkedIn duration string into start/end dates.

    Args:
        date_str (str): See implementation.

    Returns:
        tuple[date | None, date | None]: See implementation.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(parse_dates)
        True
    """
    matches = _DATE_TOKEN_RE.findall(date_str or "")
    start_date: date | None = None
    end_date: date | None = None
    if not matches:
        return start_date, end_date
    if "Present" in matches:
        if len(matches) == 1:
            return None, None
        start_date = _parse_month_year(matches[0])
        return start_date, None
    if len(matches) == 2:
        start_date = _parse_month_year(matches[0])
        end_date = _parse_month_year(matches[1])
    elif len(matches) == 1:
        start_date = _parse_month_year(matches[0])
    return start_date, end_date


def parse_duration(duration: str) -> tuple[date | None, date | None]:
    """Parse ``Jan 2020 - Present · 4 yrs`` style duration strings.

    Args:
        duration (str): See implementation.

    Returns:
        tuple[date | None, date | None]: See implementation.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(parse_duration)
        True
    """
    parts = (duration or "").split(" · ")
    if len(parts) <= 1:
        return None, None
    date_range = parts[0]
    range_parts = date_range.split(" - ")
    from_str = range_parts[0].strip() if range_parts else ""
    to_str = range_parts[1].strip() if len(range_parts) > 1 else ""
    from_date = parse_date(from_str) if from_str else None
    to_date = None if to_str in {"", "Present"} else parse_date(to_str)
    return from_date, to_date


def parse_company_data(
    json_data: dict[str, Any], *, search_term: str | None = None
) -> dict[str, Any]:
    """Parse a Voyager company payload into a flat dict (StaffSpy shape, no pandas).

    Args:
        json_data (dict[str, Any]): See implementation.
        search_term (str | None): See implementation.

    Returns:
        dict[str, Any]: See implementation.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(parse_company_data)
        True
    """
    company_info = json_data["elements"][0]
    company_name = company_info.get("name", "")
    staff_count = company_info.get("staffCount")
    company_type = company_info.get("type", "")
    description = company_info.get("description", "")
    industries_list = [
        ind.get("localizedName", "") for ind in company_info.get("companyIndustries", [])
    ]
    headquarter = company_info.get("headquarter", {})
    headquarter_full = (
        f"{headquarter.get('line1', '')}, {headquarter.get('city', '')}, "
        f"{headquarter.get('country', '')} {headquarter.get('postalCode', '')}"
    )
    logo_data = company_info.get("logo", {})
    vector_image = logo_data.get("image", {}).get("com.linkedin.common.VectorImage", {})
    root_url = vector_image.get("rootUrl", "")
    artifacts = vector_image.get("artifacts", [])
    logo_url = None
    if artifacts:
        logo_url = root_url + artifacts[0].get("fileIdentifyingUrlPathSegment", "")
    tracking_info = company_info.get("trackingInfo", {})
    object_urn = tracking_info.get("objectUrn", "")
    internal_id = object_urn.split(":")[-1] if object_urn.startswith("urn:li:company:") else None
    bg_photo = company_info.get("backgroundCoverPhoto", {})
    bg_vector = bg_photo.get("com.linkedin.common.VectorImage", {})
    bg_root = bg_vector.get("rootUrl", "")
    bg_artifacts = bg_vector.get("artifacts", [])
    banner_url = None
    if bg_artifacts:
        banner_url = bg_root + bg_artifacts[0].get("fileIdentifyingUrlPathSegment", "")
    logger.debug("parsed company {}", company_name)
    return {
        "search_term": search_term,
        "linkedin_company_id": internal_id,
        "company_name": company_name,
        "staff_count": staff_count,
        "company_type": company_type,
        "industries": industries_list,
        "headquarters_address": headquarter_full,
        "description": description,
        "logo_url": logo_url,
        "banner_url": banner_url,
    }


def staff_rows_to_dicts(staff: list[Staff]) -> list[dict[str, Any]]:
    """Convert staff models to dict rows, deprioritizing hidden LinkedIn Member rows.

    Args:
        staff (list[Staff]): See implementation.

    Returns:
        list[dict[str, Any]]: See implementation.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(staff_rows_to_dicts)
        True
    """
    rows = [person.to_dict() for person in staff]
    visible = [row for row in rows if row.get("name") != "LinkedIn Member"]
    hidden = [row for row in rows if row.get("name") == "LinkedIn Member"]
    return visible + hidden


__all__ = [
    "Certification",
    "Comment",
    "ContactInfo",
    "Experience",
    "School",
    "Skill",
    "Staff",
    "create_emails",
    "extract_base_domain",
    "extract_emails_from_text",
    "parse_company_data",
    "parse_date",
    "parse_dates",
    "parse_duration",
    "staff_rows_to_dicts",
]
