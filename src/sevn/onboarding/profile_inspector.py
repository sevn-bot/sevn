"""Read-only profile inspector rows for the onboarding wizard (D12 / W7).

Module: sevn.onboarding.profile_inspector
Depends: typing, sevn.onboarding.capabilities_manifest, sevn.onboarding.merge,
    sevn.onboarding.profiles, sevn.onboarding.web_app

Exports:
    build_profile_inspector_payload — merged rows for ``GET /api/profile-inspector``.
    format_inspector_value — JSON-safe display string for a config value.
    get_config_at_path — dotted-path lookup in merged ``sevn.json`` preview.

Examples:
    >>> payload = build_profile_inspector_payload("good_value_osx")
    >>> payload["profile_id"]
    'good_value_osx'
    >>> any(r["field_id"] == "providers.tier_default.triager" for r in payload["rows"])
    True
"""

from __future__ import annotations

from typing import Any

from sevn.onboarding.capabilities_manifest import (
    CapabilityEntry,
    CapabilityManifest,
    load_manifest,
    merged_capability_defaults,
)
from sevn.onboarding.profiles import load_profile_catalog, load_profile_fragment

TAB_ORDER: tuple[str, ...] = (
    "Profile",
    "Workspace",
    "My Sevn.bot",
    "Main model",
    "Capabilities",
    "Channels",
    "Sandbox",
    "Public access",
)

_WIZARD_CONFIG_ROWS: tuple[tuple[str, str, str], ...] = (
    ("Workspace", "workspace_root", "Workspace root"),
    ("Workspace", "gateway.host", "Gateway host"),
    ("Workspace", "gateway.port", "Gateway port"),
    ("My Sevn.bot", "my_sevn.repo_url", "Sevn.bot repo URL"),
    ("My Sevn.bot", "my_sevn.sync.enabled", "Daily repo sync"),
    ("My Sevn.bot", "my_sevn.workspace_backup.repo_url", "Workspace backup repo"),
    ("My Sevn.bot", "self_improve.enabled", "Self-improve"),
    ("My Sevn.bot", "self_improve.hub.use_github", "GitHub self-improve hub"),
    ("Main model", "providers.use_main_model_for_all", "Use main model for all slots"),
    ("Main model", "providers.tier_default.triager", "Main model (triager)"),
    ("Main model", "providers.tier_default.B", "Tier B model"),
    ("Main model", "providers.tier_default.C", "Tier C model"),
    ("Main model", "providers.tier_default.D", "Tier D model"),
    ("Channels", "channels.telegram.enabled", "Telegram channel"),
    ("Channels", "channels.telegram.dm_policy", "Telegram DM policy"),
    ("Channels", "channels.webchat.enabled", "Webchat channel"),
    ("Sandbox", "sandbox.mode", "Sandbox mode"),
    ("Public access", "infrastructure.tunnel.mode", "Public access mode"),
)

_MODEL_SLOT_PATHS: tuple[str, ...] = (
    "providers.tier_default.C.sub_lm",
    "providers.tier_default.D.sub_lm",
    "providers.tier_default.C.lambda_leaf",
    "providers.tier_default.D.lambda_leaf",
    "lcm.summary_model",
    "memory.pre_compaction_flush.model",
    "memory.dreaming.scoring.llm_ranker.model",
    "memory.user_model.extractor_model",
    "security.scanner.model",
)

_MODEL_SLOT_LABELS: dict[str, str] = {
    "providers.tier_default.C.sub_lm": "C sub-LM model",
    "providers.tier_default.D.sub_lm": "D sub-LM model",
    "providers.tier_default.C.lambda_leaf": "C λ-leaf model",
    "providers.tier_default.D.lambda_leaf": "D λ-leaf model",
    "lcm.summary_model": "LCM summary model",
    "memory.pre_compaction_flush.model": "Pre-compaction model",
    "memory.dreaming.scoring.llm_ranker.model": "Dreaming ranker model",
    "memory.user_model.extractor_model": "User-model extractor",
    "security.scanner.model": "Scanner model",
}


def get_config_at_path(doc: dict[str, Any], path: str) -> Any:
    """Return a dotted config path from a nested document.

    Args:
        doc (dict[str, Any]): Merged workspace preview.
        path (str): Dot-separated path (e.g. ``gateway.queue_mode``).

    Returns:
        Any: Resolved value or ``None`` when the path is absent.

    Examples:
        >>> get_config_at_path({"gateway": {"port": 3001}}, "gateway.port")
        3001
        >>> get_config_at_path({"gateway": {"port": 3001}}, "missing.path") is None
        True
    """
    cur: Any = doc
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def format_inspector_value(value: Any) -> str:
    """Format a merged config or capability value for the inspector table.

    Args:
        value (Any): Raw JSON value.

    Returns:
        str: Human-readable cell text.

    Examples:
        >>> format_inspector_value(True)
        'on'
        >>> format_inspector_value(False)
        'off'
        >>> format_inspector_value("steer")
        'steer'
    """
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "on" if value else "off"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        text = value.strip()
        return text if text else "—"
    if isinstance(value, list):
        return ", ".join(format_inspector_value(item) for item in value) or "—"
    return str(value)


def _catalog_row(profile_id: str) -> dict[str, Any] | None:
    """Return catalog metadata for ``profile_id``.

    Args:
        profile_id (str): Preset id.

    Returns:
        dict[str, Any] | None: Catalog row or ``None``.

    Examples:
        >>> row = _catalog_row("good_value_osx")
        >>> row is not None and bool(row.get("model"))
        True
    """
    pid = profile_id.strip()
    for row in load_profile_catalog():
        if str(row.get("profile_id", "")).strip() == pid:
            return row
    return None


def _explanation_for_path(path: str, field_help: dict[str, dict[str, str]]) -> str:
    """Resolve long description for a config path.

    Args:
        path (str): Dotted config path.
        field_help (dict[str, dict[str, str]]): Packaged field-help map.

    Returns:
        str: Explanation text (may be empty).

    Examples:
        >>> _explanation_for_path("gateway.port", {})
        ''
    """
    entry = field_help.get(path)
    if isinstance(entry, dict):
        text = entry.get("long_description", "")
        if isinstance(text, str) and text.strip():
            return text.strip()
    return ""


def _capability_explanation(cap: CapabilityEntry, field_help: dict[str, dict[str, str]]) -> str:
    """Combine manifest and schema long descriptions for a capability row.

    Args:
        cap (CapabilityEntry): Manifest capability row.
        field_help (dict[str, dict[str, str]]): Packaged field-help map.

    Returns:
        str: Combined explanation text.

    Examples:
        >>> m = load_manifest()
        >>> cap = next(c for c in m.capabilities if c.capability_id == "gateway.queue_mode")
        >>> isinstance(_capability_explanation(cap, {}), str)
        True
    """
    parts: list[str] = []
    if cap.description.strip():
        parts.append(cap.description.strip())
    for path in cap.config_paths:
        extra = _explanation_for_path(path, field_help)
        if extra and extra not in parts:
            parts.append(extra)
    return " ".join(parts)


def _capability_tab(cap: CapabilityEntry) -> str:
    """Map a capability row to a wizard tab label.

    Args:
        cap (CapabilityEntry): Manifest capability row.

    Returns:
        str: Tab label for grouping.

    Examples:
        >>> m = load_manifest()
        >>> cap = next(c for c in m.capabilities if c.capability_id == "my_sevn.sync")
        >>> _capability_tab(cap)
        'My Sevn.bot'
    """
    if cap.wizard_tab:
        return cap.wizard_tab
    return "Capabilities"


def _format_capability_value(cap: CapabilityEntry, merged_default: bool | str) -> str:
    """Format a capability default for the inspector table.

    Args:
        cap (CapabilityEntry): Manifest capability row.
        merged_default (bool | str): Profile-aware default.

    Returns:
        str: Display value.

    Examples:
        >>> m = load_manifest()
        >>> cap = next(c for c in m.capabilities if c.capability_id == "gateway.queue_mode")
        >>> _format_capability_value(cap, "cancel")
        'cancel'
    """
    if cap.control == "select":
        return format_inspector_value(merged_default)
    return format_inspector_value(bool(merged_default))


def _row(
    *,
    tab: str,
    field_id: str,
    field: str,
    value: str,
    explanation: str,
) -> dict[str, str]:
    """Build one inspector table row.

    Args:
        tab (str): Wizard tab label.
        field_id (str): Stable field identifier.
        field (str): Human label for the Field column.
        value (str): Display value.
        explanation (str): Explanation column text.

    Returns:
        dict[str, str]: Row payload for the API.

    Examples:
        >>> _row(tab="Profile", field_id="profile.title", field="Preset", value="Good value", explanation="")
        {'tab': 'Profile', 'field_id': 'profile.title', 'field': 'Preset', 'value': 'Good value', 'explanation': ''}
    """
    return {
        "tab": tab,
        "field_id": field_id,
        "field": field,
        "value": value,
        "explanation": explanation,
    }


def _sort_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Sort inspector rows by tab order then field label.

    Args:
        rows (list[dict[str, str]]): Unordered rows.

    Returns:
        list[dict[str, str]]: Sorted rows.

    Examples:
        >>> _sort_rows([_row(tab="Workspace", field_id="a", field="B", value="1", explanation="")])
        [{'tab': 'Workspace', 'field_id': 'a', 'field': 'B', 'value': '1', 'explanation': ''}]
    """
    tab_rank = {name: idx for idx, name in enumerate(TAB_ORDER)}

    def _key(row: dict[str, str]) -> tuple[int, str, str]:
        return (tab_rank.get(row["tab"], 99), row["field"].lower(), row["field_id"])

    return sorted(rows, key=_key)


def build_profile_inspector_payload(
    profile_id: str,
    *,
    manifest: CapabilityManifest | None = None,
) -> dict[str, Any]:
    """Build read-only inspector rows for a packaged onboarding profile.

    Args:
        profile_id (str): Catalog preset id (not ``skip``).
        manifest (CapabilityManifest | None): Optional pre-loaded manifest.

    Returns:
        dict[str, Any]: ``profile_id``, ``title``, and sorted ``rows``.

    Raises:
        FileNotFoundError: When the profile fragment is missing.
        ValueError: When ``profile_id`` is empty or ``skip``.

    Examples:
        >>> payload = build_profile_inspector_payload("good_value_osx")
        >>> payload["profile_id"] == "good_value_osx"
        True
        >>> cap_rows = [r for r in payload["rows"] if r["field_id"] == "gateway.queue_mode"]
        >>> len(cap_rows) == 1 and cap_rows[0]["value"] in ("cancel", "steer")
        True
    """
    pid = profile_id.strip()
    if not pid or pid == "skip":
        msg = "profile_id is required and cannot be 'skip'"
        raise ValueError(msg)
    load_profile_fragment(pid)
    catalog = _catalog_row(pid)
    title = str(catalog.get("title", pid)) if catalog else pid
    from sevn.onboarding.web_app import (
        _DEFAULT_BASE,
        _load_field_help_paths,
        _merge_wizard_payload,
    )

    merged = _merge_wizard_payload({"fields": {}}, profile_id=pid)
    field_help = _load_field_help_paths()
    doc_manifest = manifest or load_manifest()
    cap_defaults = merged_capability_defaults(
        profile_fragment=load_profile_fragment(pid),
        manifest=doc_manifest,
    )

    rows: list[dict[str, str]] = []
    rows.append(
        _row(
            tab="Profile",
            field_id="onboarding.applied_profile",
            field="Preset",
            value=title,
            explanation="Starting profile applied before operator overrides on later wizard steps.",
        )
    )
    if catalog:
        model = catalog.get("model")
        if isinstance(model, str) and model.strip():
            rows.append(
                _row(
                    tab="Profile",
                    field_id="profile.catalog_model",
                    field="Catalog model",
                    value=model.strip(),
                    explanation="Default triager model advertised on the profile card.",
                )
            )
        host = catalog.get("host")
        if isinstance(host, str) and host.strip():
            rows.append(
                _row(
                    tab="Profile",
                    field_id="profile.catalog_host",
                    field="Host target",
                    value=host.strip(),
                    explanation="Packaged host hint (macOS vs Docker) for sandbox defaults.",
                )
            )
        short = catalog.get("short_description")
        if isinstance(short, str) and short.strip():
            rows.append(
                _row(
                    tab="Profile",
                    field_id="profile.short_description",
                    field="Summary",
                    value=short.strip(),
                    explanation="One-line profile description from the catalog.",
                )
            )

    for tab, path, label in _WIZARD_CONFIG_ROWS:
        value = get_config_at_path(merged, path)
        if value is None and get_config_at_path(_DEFAULT_BASE, path) is None:
            continue
        rows.append(
            _row(
                tab=tab,
                field_id=path,
                field=label,
                value=format_inspector_value(value),
                explanation=_explanation_for_path(path, field_help),
            )
        )

    for path in _MODEL_SLOT_PATHS:
        value = get_config_at_path(merged, path)
        if value is None:
            continue
        rows.append(
            _row(
                tab="Main model",
                field_id=path,
                field=_MODEL_SLOT_LABELS.get(path, path),
                value=format_inspector_value(value),
                explanation=_explanation_for_path(path, field_help),
            )
        )

    for cap in sorted(doc_manifest.capabilities, key=lambda c: c.capability_id):
        merged_default = cap_defaults.get(cap.capability_id, cap.default)
        rows.append(
            _row(
                tab=_capability_tab(cap),
                field_id=cap.capability_id,
                field=cap.label,
                value=_format_capability_value(cap, merged_default),
                explanation=_capability_explanation(cap, field_help),
            )
        )

    return {
        "profile_id": pid,
        "title": title,
        "rows": _sort_rows(rows),
    }


__all__ = [
    "build_profile_inspector_payload",
    "format_inspector_value",
    "get_config_at_path",
]
