from __future__ import annotations

"""Shared helper for bundled ``playwright-browser`` scripts (_page_intel).

Module: sevn.data.bundled_skills.core.playwright-browser.scripts._lib._page_intel
Depends: sevn.lcm.script_cli

Exports:
    (see module members)
"""

import contextlib
import re
from typing import Any
from urllib.parse import urlparse

# Testable without Playwright: keyword / URL heuristics
_BOT_WALL_KEYWORDS = (
    "unusual traffic",
    "i'm not a robot",
    "im not a robot",
    "verify you're human",
    "verify you are human",
    "automated queries",
    "captcha",
    "recaptcha",
    "hcaptcha",
    "cloudflare",
    "checking your browser",
    "just a moment",
    "enable javascript",
    "access denied",
    "bot detection",
)


def classify_obstacles(
    url: str,
    title: str,
    text_excerpt: str,
    *,
    frame_urls: list[str] | None = None,
) -> dict[str, Any]:
    """Pure classification for tests and ``obstacle_signals``."""
    u = (url or "").lower()
    t = (title or "").lower()
    body = (text_excerpt or "").lower()
    blob = f"{t}\n{body}"
    frames = [((f or "").lower()) for f in (frame_urls or [])]

    google_sorry = False
    try:
        p = urlparse(url or "")
        host = (p.netloc or "").lower()
        path = (p.path or "").lower()
        if "google." in host and ("/sorry/" in path or path.rstrip("/").endswith("/sorry")):
            google_sorry = True
        if "google." in host and "sorry/index" in u:
            google_sorry = True
    except ValueError:
        pass

    recaptcha_iframe = any("recaptcha" in f for f in frames)
    hcaptcha_iframe = any("hcaptcha" in f for f in frames)

    suspicious = google_sorry or recaptcha_iframe or hcaptcha_iframe
    if not suspicious:
        suspicious = any(k in blob for k in _BOT_WALL_KEYWORDS)

    return {
        "google_sorry_page": google_sorry,
        "recaptcha_iframe_present": recaptcha_iframe,
        "hcaptcha_iframe_present": hcaptcha_iframe,
        "suspicious_bot_wall": suspicious,
    }


async def _page_text_excerpt(page: Any, max_chars: int = 8000) -> str:
    try:
        txt = await page.inner_text("body", timeout=10_000)
    except Exception:
        try:
            txt = await page.content()
        except Exception:
            txt = ""
    txt = (txt or "").strip()
    if len(txt) > max_chars:
        return txt[:max_chars] + "…"
    return txt


async def _collect_frame_urls(page: Any) -> list[str]:
    out: list[str] = []
    try:
        for fr in page.frames:
            u = getattr(fr, "url", None) or ""
            if u:
                out.append(u)
    except Exception:
        pass
    return out


async def obstacle_signals(page: Any, *, text_excerpt_max: int = 8000) -> dict[str, Any]:
    """Snapshot url, title, excerpt, and obstacle flags for the agent."""
    url = ""
    title = ""
    try:
        url = page.url or ""
    except Exception:
        pass
    try:
        title = await page.title()
    except Exception:
        pass
    excerpt = await _page_text_excerpt(page, max_chars=text_excerpt_max)
    frames = await _collect_frame_urls(page)
    flags = classify_obstacles(url, title, excerpt, frame_urls=frames)
    return {
        "url": url,
        "title": title,
        "text_excerpt": excerpt,
        "frame_urls_sample": frames[:20],
        **flags,
    }


_COOKIE_BUTTON_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("accept_all", re.compile(r"accept\s+all|allow\s+all|agree\s+to\s+all|i\s+accept", re.I)),
    ("accept", re.compile(r"^accept($|\s)|^agree($|\s)|^ok$|^got\s+it$|^i\s+understand", re.I)),
    (
        "reject_nonessential",
        re.compile(
            r"reject\s+all|decline\s+all|only\s+necessary|essential\s+only|reject\s+optional", re.I
        ),
    ),
    ("consent_save", re.compile(r"save\s+(preferences|settings)|confirm\s+choices", re.I)),
    ("cookie_close", re.compile(r"^close$|^no\s+thanks$|^dismiss$", re.I)),
]

_GOOGLE_CONSENT_SELECTORS: tuple[str, ...] = (
    "#L2AGLb",
    "#introAgreeButton",
    'button[aria-label*="Accept all" i]',
    'button[aria-label*="Accept cookies" i]',
    'form[action*="consent"] button',
)

_CMP_SELECTOR_HINTS: tuple[str, ...] = (
    '[id*="onetrust-accept"]',
    "#onetrust-accept-btn-handler",
    'button[id*="cookie"][id*="accept"]',
    'button[class*="cookie"][class*="accept"]',
    '[aria-label*="Accept cookies" i]',
    '[aria-label*="Accept all" i]',
    '[data-testid*="accept" i]',
)


async def _click_first_visible(
    page: Any,
    locator: Any,
    *,
    label: str,
    timeout_ms: int,
    log: list[str],
) -> bool:
    """Click the first visible match; append to *log* when successful."""
    try:
        if await locator.count() == 0:
            return False
        target = locator.first
        await target.wait_for(state="visible", timeout=800)
        await target.click(timeout=timeout_ms)
        log.append(label)
        with contextlib.suppress(Exception):
            await page.wait_for_timeout(300)
        return True
    except Exception:
        return False


async def try_dismiss_cookie_banners(page: Any, *, timeout_ms: int = 8_000) -> list[str]:
    """Best-effort cookie / consent dismissal; returns human-readable steps."""
    log: list[str] = []
    with contextlib.suppress(Exception):
        await page.wait_for_timeout(400)

    for sel in _GOOGLE_CONSENT_SELECTORS:
        if await _click_first_visible(
            page,
            page.locator(sel),
            label=f"clicked:google:{sel}",
            timeout_ms=timeout_ms,
            log=log,
        ):
            return log

    accept_patterns = _COOKIE_BUTTON_PATTERNS[:2]
    for label, pat in accept_patterns:
        for role in ("button", "link"):
            if await _click_first_visible(
                page,
                page.get_by_role(role, name=pat),
                label=f"clicked:{role}:{label}",
                timeout_ms=timeout_ms,
                log=log,
            ):
                return log
        if await _click_first_visible(
            page,
            page.locator('[role="button"]').filter(has_text=pat),
            label=f"clicked:role_button:{label}",
            timeout_ms=timeout_ms,
            log=log,
        ):
            return log

    for label, pat in _COOKIE_BUTTON_PATTERNS[2:]:
        if await _click_first_visible(
            page,
            page.get_by_role("button", name=pat),
            label=f"clicked:button:{label}",
            timeout_ms=timeout_ms,
            log=log,
        ):
            return log

    for sel in _CMP_SELECTOR_HINTS:
        if await _click_first_visible(
            page,
            page.locator(sel),
            label=f"clicked:selector:{sel}",
            timeout_ms=timeout_ms,
            log=log,
        ):
            return log

    for frame in page.frames:
        frame_url = (getattr(frame, "url", "") or "").lower()
        if frame_url == "about:blank":
            continue
        for sel in _GOOGLE_CONSENT_SELECTORS[:2]:
            if await _click_first_visible(
                page,
                frame.locator(sel),
                label=f"clicked:frame:{sel}",
                timeout_ms=timeout_ms,
                log=log,
            ):
                return log
        for label, pat in accept_patterns:
            if await _click_first_visible(
                page,
                frame.get_by_role("button", name=pat),
                label=f"clicked:frame_button:{label}",
                timeout_ms=timeout_ms,
                log=log,
            ):
                return log

    if not any(s.startswith("clicked:") for s in log):
        log.append("no_cookie_banner_matched")
    return log


async def try_click_recaptcha_checkbox(page: Any, *, timeout_ms: int = 12_000) -> tuple[bool, str]:
    """Try main reCAPTCHA v2 checkbox inside iframe. Often fails under automation."""
    for iframe_sel in (
        'iframe[src*="recaptcha/api2/anchor"]',
        'iframe[src*="recaptcha"]',
        'iframe[title*="reCAPTCHA" i]',
    ):
        handle = page.locator(iframe_sel).first
        try:
            await handle.wait_for(state="attached", timeout=5_000)
        except Exception:
            continue
        try:
            frame = await handle.content_frame()
        except Exception:
            frame = None
        if frame is None:
            continue
        for box in ("#recaptcha-anchor", ".recaptcha-checkbox-border"):
            try:
                el = frame.locator(box).first
                await el.wait_for(state="visible", timeout=5_000)
                await el.click(timeout=timeout_ms)
                return True, f"clicked:{iframe_sel}:{box}"
            except Exception:
                continue

    try:
        for fr in page.frames:
            u = (getattr(fr, "url", "") or "").lower()
            if "recaptcha" not in u:
                continue
            try:
                loc = fr.locator("#recaptcha-anchor, .recaptcha-checkbox-border").first
                await loc.wait_for(state="visible", timeout=5_000)
                await loc.click(timeout=timeout_ms)
                return True, f"clicked:frame:{u[:80]}"
            except Exception:
                continue
    except Exception as e:
        return False, f"frame_iterate_failed:{e!s}"[:200]

    return False, "recaptcha_checkbox_not_found_or_not_clickable"
