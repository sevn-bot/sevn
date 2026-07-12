"""Small text/normalisation helpers for the ``job-ops`` skill.

Module: job-ops/scripts/lib/text.py
"""

from __future__ import annotations

import re
from html import unescape

_WS = re.compile(r"\s+")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_TAG = re.compile(r"<[^>]+>")
_SCRIPT_STYLE = re.compile(r"<(script|style)\b[^>]*>[\s\S]*?</\1>", re.IGNORECASE)
_CHALLENGE = re.compile(r"cloudflare|cf-browser-verification|challenge-platform", re.IGNORECASE)


def normalize_whitespace(value: str) -> str:
    """Collapse runs of whitespace and trim."""
    return _WS.sub(" ", value).strip()


def normalize_token(value: str | None) -> str:
    """Lowercase and reduce to single-spaced alphanumerics."""
    if not value:
        return ""
    lowered = value.lower()
    return _WS.sub(" ", _NON_ALNUM.sub(" ", lowered)).strip()


def strip_html(value: str) -> str:
    """Return readable text from an HTML fragment."""
    without_scripts = _SCRIPT_STYLE.sub(" ", value)
    text = _TAG.sub(" ", without_scripts)
    return normalize_whitespace(unescape(text))


def prepare_text(value: str | None, limit: int) -> str:
    """Strip HTML, collapse whitespace, and truncate to ``limit`` characters.

    Used to feed clean, bounded resume/JD text to the LLM scorer and reviewer.
    """
    if not value:
        return ""
    return strip_html(value)[:limit]


def looks_like_challenge(html: str) -> bool:
    """Return ``True`` when ``html`` looks like a Cloudflare/anti-bot challenge page."""
    return bool(_CHALLENGE.search(html))


def matches_search_term(haystack: str, search_term: str) -> bool:
    """Token matching: full-phrase or all-tokens containment."""
    term = normalize_token(search_term)
    if not term:
        return True
    normalized = normalize_token(haystack)
    if not normalized:
        return False
    if term in normalized:
        return True
    return all(token in normalized for token in term.split(" ") if token)


def infer_job_type(text: str) -> str | None:
    """Infer a job-type label from free text."""
    patterns: list[tuple[str, str]] = [
        (r"\bpart[\s-]?time\b", "Part-time"),
        (r"\bfull[\s-]?time\b", "Full-time"),
        (r"\bcontract(or)?\b", "Contract"),
        (r"\bfreelance\b", "Freelance"),
        (r"\bintern(ship)?\b", "Internship"),
        (r"\btemporary\b", "Temporary"),
    ]
    for pattern, label in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return label
    return None
