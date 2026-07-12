"""Validate onboarding profile catalog and fragment parity (`onboarding-comprehensive-setup` W10).

Module: scripts.check_onboarding_profiles
Depends: json, pathlib, sevn.onboarding.capabilities_manifest, sevn.onboarding.profiles

Exports:
    main — exit 1 on catalog / fragment / manifest drift.

Examples:
    >>> isinstance(REPO, Path)
    True
"""

from __future__ import annotations

import sys
from pathlib import Path

from sevn.onboarding.capabilities_manifest import load_manifest
from sevn.onboarding.profiles import load_profile_catalog, load_profile_fragment

REPO = Path(__file__).resolve().parents[1]
FRAGMENTS_DIR = REPO / "src" / "sevn" / "data" / "onboarding_profiles" / "fragments"


def _fragment_ids_on_disk() -> set[str]:
    """Return packaged fragment basenames without ``.json``.

    Returns:
        set[str]: Fragment profile ids present on disk.

    Examples:
        >>> ids = _fragment_ids_on_disk()
        >>> "good_value_osx" in ids
        True
    """
    return {path.stem for path in FRAGMENTS_DIR.glob("*.json")}


def main() -> int:
    """Run catalog ↔ fragment ↔ manifest parity checks.

    Returns:
        int: ``0`` when clean; ``1`` on drift.

    Examples:
        >>> main() in (0, 1)
        True
    """
    errors: list[str] = []
    manifest = load_manifest()
    cap_index = {c.capability_id: c for c in manifest.capabilities}
    catalog = load_profile_catalog()
    catalog_ids = {str(row.get("profile_id", "")).strip() for row in catalog}
    fragment_ids = _fragment_ids_on_disk()

    orphan_fragments = sorted(fragment_ids - catalog_ids)
    missing_fragments = sorted(catalog_ids - fragment_ids)
    if orphan_fragments:
        errors.append(f"fragments without catalog row: {', '.join(orphan_fragments)}")
    if missing_fragments:
        errors.append(f"catalog rows without fragment file: {', '.join(missing_fragments)}")

    for row in catalog:
        pid = str(row.get("profile_id", "")).strip()
        summary = str(row.get("capabilities_summary", "")).strip()
        if not summary:
            errors.append(f"{pid}: missing non-empty capabilities_summary in catalog")

    for pid in sorted(catalog_ids & fragment_ids):
        try:
            frag = load_profile_fragment(pid)
        except (FileNotFoundError, ValueError) as exc:
            errors.append(f"{pid}: fragment load failed: {exc}")
            continue
        raw_defaults = frag.get("capabilities_defaults")
        if not isinstance(raw_defaults, dict) or not raw_defaults:
            errors.append(f"{pid}: capabilities_defaults must be a non-empty object")
            continue
        for cap_id, value in raw_defaults.items():
            cap_key = str(cap_id)
            if cap_key not in cap_index:
                errors.append(f"{pid}: unknown capability_id {cap_key!r} in capabilities_defaults")
                continue
            cap = cap_index[cap_key]
            if not cap.profile_overridable:
                errors.append(f"{pid}: {cap_key!r} is not profile_overridable in manifest")
            if not isinstance(value, bool):
                errors.append(f"{pid}: capabilities_defaults[{cap_key!r}] must be boolean")

    if errors:
        for line in errors:
            print(f"check_onboarding_profiles: {line}", file=sys.stderr)
        return 1
    print(
        "check_onboarding_profiles: ok "
        f"({len(catalog)} catalog rows, {len(fragment_ids)} fragments)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
