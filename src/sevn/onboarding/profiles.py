"""Preset profile catalogue (`specs/22-onboarding.md` §2.1, §3.1, §4.2).

Module: sevn.onboarding.profiles
Depends: importlib.resources, json, pathlib, typing

Exports:
    profile_catalog_path — packaged JSON path (for tests).
    load_profile_catalog — raw catalog rows.
    load_profile_catalog_for_wizard — catalog rows enriched for web UI.
    load_profile_fragment — merged fragment dict for ``profile_id``.
    profile_has_capabilities_defaults — whether fragment ships capability presets.
    profile_default_sandbox_mode — preset ``sandbox.mode`` from catalog ``host`` tag.

Examples:
    >>> frag = load_profile_fragment("full_free")
    >>> frag["schema_version"]
    1
"""

from __future__ import annotations

import json
from importlib import resources
from typing import Any, Final

from sevn.onboarding.validate import validate_workspace_document

FORBIDDEN_FRAGMENT_KEY_SUBSTRINGS: Final[tuple[str, ...]] = (
    "token",
    "secret",
    "password",
    "api_key",
    "credential",
)


def _reject_secretish_keys(obj: dict[str, Any], *, path: str) -> None:
    """Reject fragments that embed obvious secret material keys.

    Args:
        obj (dict[str, Any]): Fragment JSON object.
        path (str): JSON Pointer prefix for errors.

    Raises:
        ValueError: When a forbidden substring appears in a mapping key.

    Examples:
        >>> _reject_secretish_keys({"ok": 1}, path="")
        >>> try:
        ...     _reject_secretish_keys({"api_key": 1}, path="")
        ... except ValueError:
        ...     pass
    """
    for key, value in obj.items():
        lowered = key.lower()
        if any(s in lowered for s in FORBIDDEN_FRAGMENT_KEY_SUBSTRINGS):
            msg = f"{path}/{key}: preset fragments must not define secret fields (`specs/22-onboarding.md` §8)"
            raise ValueError(msg)
        if isinstance(value, dict):
            _reject_secretish_keys(value, path=f"{path}/{key}")


def profile_catalog_path() -> str:
    """Return the packaged catalog resource name.

    Returns:
        str: Resource path segment under ``sevn.data.onboarding_profiles``.

    Examples:
        >>> profile_catalog_path()
        'onboarding_profiles.json'
    """
    return "onboarding_profiles.json"


def load_profile_catalog() -> list[dict[str, Any]]:
    """Load ``onboarding_profiles.json`` rows.

    Returns:
        list[dict[str, Any]]: Catalog entries with ``profile_id``, ``title``, etc.

    Raises:
        FileNotFoundError: When packaged data is missing.
        ValueError: When JSON is malformed.

    Examples:
        >>> rows = load_profile_catalog()
        >>> isinstance(rows, list) and len(rows) >= 1
        True
    """
    ref = resources.files("sevn.data.onboarding_profiles") / profile_catalog_path()
    text = ref.read_text(encoding="utf-8")
    data = json.loads(text)
    if not isinstance(data, list):
        msg = "onboarding_profiles.json must be a JSON array"
        raise ValueError(msg)
    return [row for row in data if isinstance(row, dict)]


def profile_has_capabilities_defaults(profile_id: str) -> bool:
    """Return whether ``fragments/<profile_id>.json`` defines capability presets.

    Args:
        profile_id (str): Catalog identifier.

    Returns:
        bool: True when ``capabilities_defaults`` is a non-empty object.

    Examples:
        >>> profile_has_capabilities_defaults("good_value_osx")
        True
        >>> profile_has_capabilities_defaults("skip")
        False
    """
    pid = profile_id.strip()
    if not pid or pid == "skip":
        return False
    try:
        frag = load_profile_fragment(pid)
    except (FileNotFoundError, ValueError):
        return False
    raw = frag.get("capabilities_defaults")
    return isinstance(raw, dict) and bool(raw)


def load_profile_catalog_for_wizard() -> list[dict[str, Any]]:
    """Load catalog rows with wizard enablement flags for ``GET /api/meta``.

    Returns:
        list[dict[str, Any]]: Catalog entries plus ``capabilities_ready`` boolean.

    Examples:
        >>> rows = load_profile_catalog_for_wizard()
        >>> any(r.get("capabilities_ready") for r in rows)
        True
    """
    out: list[dict[str, Any]] = []
    for row in load_profile_catalog():
        pid = str(row.get("profile_id", "")).strip()
        enriched = dict(row)
        enriched["capabilities_ready"] = profile_has_capabilities_defaults(pid)
        out.append(enriched)
    return out


def load_profile_fragment(profile_id: str) -> dict[str, Any]:
    """Load and validate ``fragments/<profile_id>.json``.

    Args:
        profile_id (str): Catalog identifier.

    Returns:
        dict[str, Any]: Partial workspace document.

    Raises:
        FileNotFoundError: When the fragment file is missing.
        ValueError: When the fragment fails secret-key or schema checks.

    Examples:
        >>> frag = load_profile_fragment("full_free")
        >>> frag["schema_version"]
        1
    """
    ref = resources.files("sevn.data.onboarding_profiles") / "fragments" / f"{profile_id}.json"
    if not ref.is_file():
        msg = f"unknown onboarding profile_id={profile_id!r} (no packaged fragment)"
        raise FileNotFoundError(msg)
    raw = json.loads(ref.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        msg = f"fragment {profile_id} must be a JSON object"
        raise ValueError(msg)
    _reject_secretish_keys(raw, path="")
    merged_preview = dict(raw)
    merged_preview.setdefault("schema_version", 1)
    gw = merged_preview.setdefault("gateway", {})
    if isinstance(gw, dict):
        gw.setdefault("token", "${SECRET:keychain:sevn.gateway.token}")
    validate_workspace_document(merged_preview, check_provider_credentials=False)
    return raw


def profile_default_sandbox_mode(profile_id: str) -> str | None:
    """Return the packaged preset sandbox driver for ``profile_id``.

    macOS-oriented presets (``host: osx``) default to ``pyodide_deno``; Docker-oriented
    presets default to ``docker``. Callers should pass the result through
    :func:`~sevn.agent.runtimes.pyodide_deno.reconcile_sandbox_mode_document` so a
    missing runtime is not persisted.

    Args:
        profile_id (str): Catalog identifier (not ``skip``).

    Returns:
        str | None: ``pyodide_deno``, ``docker``, or ``None`` when the profile has no host tag.

    Examples:
        >>> profile_default_sandbox_mode("good_value_osx")
        'pyodide_deno'
        >>> profile_default_sandbox_mode("full_free") is None
        True
    """
    pid = profile_id.strip()
    if not pid or pid == "skip":
        return None
    for row in load_profile_catalog():
        if str(row.get("profile_id", "")).strip() == pid:
            host = str(row.get("host", "")).strip().lower()
            if host == "osx":
                return "pyodide_deno"
            if host == "docker":
                return "docker"
            return None
    return None
