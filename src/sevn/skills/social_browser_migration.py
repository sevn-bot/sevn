"""Rewrite legacy ``sevn.skills.social_browser`` imports for operator workspaces (#128 / D7).

Module: sevn.skills.social_browser_migration
Depends: re

Exports:
    rewrite_legacy_imports — rewrite Python source text to the social stack.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Final

LEGACY_MODULE: Final[str] = "sevn.skills.social_browser"

# Closest SSOT homes after retired x-use skill tree removal (D7).
SYMBOL_TARGET_MODULES: Final[dict[str, str]] = {
    "host_allowed": "sevn.browser.recipes.base",
    "validate_social_url": "sevn.browser.recipes.base",
    "validate_egress": "sevn.browser.recipes.base",
    "resolve_browser_profile": "sevn.browser.chrome",
    "resolve_profile_dir": "sevn.browser.chrome",
    "dry_run_requested": "sevn.integrations.social_media.legacy_compat",
    "cdp_reachable": "sevn.skills.browser_session",
    "default_cdp_url": "sevn.skills.browser_session",
    "session_status_payload": "sevn.skills.browser_session",
    "merge_social_browser_proc_env": "sevn.skills.browser_session",
    "merge_browser_proc_env": "sevn.skills.browser_session",
    "logged_in_browser_page": "sevn.skills.browser_session",
    "fetch_page_snapshot": "sevn.browser.recipes.social",
    "x_search_url": "sevn.browser.recipes.social",
    "facebook_search_url": "sevn.browser.recipes.social",
    "SocialRecipe": "sevn.browser.recipes.social",
    "social_write_allowed": "sevn.browser.recipes.social",
    "parse_post_html": "sevn.browser.recipes.social",
    "X_USE_SKILL_ID": "sevn.integrations.social_media.legacy_compat",
    "FACEBOOK_USE_SKILL_ID": "sevn.integrations.social_media.legacy_compat",
    "SOCIAL_BROWSER_SKILL_IDS": "sevn.integrations.social_media.legacy_compat",
    "SKILL_EGRESS": "sevn.integrations.social_media.legacy_compat",
    "X_EGRESS_DOMAINS": "sevn.browser.recipes.social",
    "FACEBOOK_EGRESS_DOMAINS": "sevn.browser.recipes.social",
}

_FROM_IMPORT_RE: Final[re.Pattern[str]] = re.compile(
    r"^(\s*)from\s+sevn\.skills\.social_browser\s+import\s+(.+)$",
    re.MULTILINE,
)
_IMPORT_AS_RE: Final[re.Pattern[str]] = re.compile(
    r"^(\s*)import\s+sevn\.skills\.social_browser(?:\s+as\s+(\w+))?\s*$",
    re.MULTILINE,
)

__all__ = [
    "LEGACY_MODULE",
    "SYMBOL_TARGET_MODULES",
    "rewrite_legacy_imports",
]


def _split_import_names(raw: str) -> list[str]:
    """Split a comma-separated import clause into bare symbol names.

    Args:
        raw (str): Text after ``import`` on a ``from … import`` line.

    Returns:
        list[str]: Imported symbol names (no aliases).

    Examples:
        >>> _split_import_names("host_allowed, SocialRecipe as SR")
        ['host_allowed', 'SocialRecipe']
    """
    names: list[str] = []
    for part in raw.split(","):
        chunk = part.strip()
        if not chunk or chunk.startswith("#"):
            continue
        if " as " in chunk:
            chunk = chunk.split(" as ", 1)[0].strip()
        if chunk:
            names.append(chunk)
    return names


def _format_from_import(module: str, symbols: list[str], indent: str) -> str:
    """Build one ``from module import …`` line.

    Args:
        module (str): Target module path.
        symbols (list[str]): Symbols to import.
        indent (str): Leading whitespace for the line.

    Returns:
        str: Replacement import line.

    Examples:
        >>> _format_from_import("sevn.browser.recipes.social", ["SocialRecipe"], "")
        'from sevn.browser.recipes.social import SocialRecipe'
    """
    joined = ", ".join(sorted(set(symbols)))
    return f"{indent}from {module} import {joined}"


def rewrite_legacy_imports(source: str) -> str:
    """Rewrite deleted ``social_browser`` imports to the social_media_manager stack.

    Replaces ``from sevn.skills.social_browser import …`` with grouped imports from
    :mod:`sevn.integrations.social_media`, :mod:`sevn.browser.recipes.social`, and
    :mod:`sevn.skills.browser_session`. Bare ``import sevn.skills.social_browser`` lines
    become a migration comment. Non-import references to ``LEGACY_MODULE`` are left for
    manual review.

    Args:
        source (str): Python source text (typically an operator skill script).

    Returns:
        str: Source with legacy import lines rewritten.

    Examples:
        >>> text = "from sevn.skills.social_browser import host_allowed\\n"
        >>> "sevn.browser.recipes.base" in rewrite_legacy_imports(text)
        True
    """
    if LEGACY_MODULE not in source:
        return source

    def _replace_from(match: re.Match[str]) -> str:
        indent = match.group(1)
        symbols = _split_import_names(match.group(2))
        by_module: dict[str, list[str]] = defaultdict(list)
        for symbol in symbols:
            target = SYMBOL_TARGET_MODULES.get(
                symbol, "sevn.integrations.social_media.legacy_compat"
            )
            by_module[target].append(symbol)
        lines = [
            _format_from_import(module, names, indent)
            for module, names in sorted(by_module.items())
        ]
        return "\n".join(lines)

    updated = _FROM_IMPORT_RE.sub(_replace_from, source)

    def _replace_import(match: re.Match[str]) -> str:
        indent = match.group(1)
        alias = match.group(2)
        hint = (
            f"{indent}# MIGRATION(#128): sevn.skills.social_browser removed — "
            "use social_media_manager + browser action=social"
        )
        if alias:
            hint += f" (was `import … as {alias}`)"
        return hint

    return _IMPORT_AS_RE.sub(_replace_import, updated)
