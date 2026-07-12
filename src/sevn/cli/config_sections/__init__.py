"""Section rendering helpers for ``sevn config <slug>``.

Module: sevn.cli.config_sections
Depends: typing, sevn.cli.config_paths, sevn.cli.workspace

Exports:
    nested_get — read a dotted path from a config document.
    section_payload — JSON summary for one section.
    format_section_plain — human section report.
"""

from __future__ import annotations

from typing import Any

from sevn.cli.config_paths import ConfigSection


def nested_get(document: dict[str, Any], dot_path: str) -> Any:
    """Read a dotted path from a nested dict (missing keys → None).

    Args:
        document (dict[str, Any]): Config document (e.g. ``sevn.json``).
        dot_path (str): Dot-separated key path.

    Returns:
        Any: Value at path, or None when absent.

    Examples:
        >>> nested_get({"gateway": {"port": 8080}}, "gateway.port")
        8080
        >>> nested_get({"gateway": {"port": 8080}}, "gateway.missing") is None
        True
    """
    current: Any = document
    for part in dot_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def section_payload(section: ConfigSection, document: dict[str, Any]) -> dict[str, Any]:
    """Build a JSON-serializable section summary.

    Args:
        section (ConfigSection): Config section metadata.
        document (dict[str, Any]): Bound workspace document.

    Returns:
        dict[str, Any]: Section summary with per-path values.

    Examples:
        >>> from sevn.cli.config_paths import section_by_slug
        >>> sec = section_by_slug("session")
        >>> assert sec is not None
        >>> payload = section_payload(sec, {"gateway": {"queue_mode": "cancel"}})
        >>> "paths" in payload
        True
    """
    paths = [{"path": path, "value": nested_get(document, path)} for path in section.dot_paths]
    return {
        "callback": section.callback,
        "dot_paths": list(section.dot_paths),
        "label": section.label,
        "paths": paths,
        "slug": section.slug,
    }


def format_section_plain(section: ConfigSection, document: dict[str, Any]) -> str:
    """Render a section summary for plain stdout.

    Args:
        section (ConfigSection): Config section metadata.
        document (dict[str, Any]): Bound workspace document.

    Returns:
        str: Multi-line human report.

    Examples:
        >>> from sevn.cli.config_paths import section_by_slug
        >>> sec = section_by_slug("session")
        >>> assert sec is not None
        >>> "Session" in format_section_plain(sec, {})
        True
    """
    lines = [
        f"{section.label} ({section.slug})",
        f"Telegram callback: {section.callback}",
        "",
        "sevn.json keys (use `sevn config set <path> <value>`):",
    ]
    if not section.dot_paths:
        lines.append("  (no toggle paths in menu_registry for this section yet)")
    else:
        for path in section.dot_paths:
            value = nested_get(document, path)
            lines.append(f"  {path} = {value!r}")
    lines.append("")
    lines.append("See also: sevn guide config")
    return "\n".join(lines)
