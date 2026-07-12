"""§C0 profile schemas for README structure validation (STANDARD.md).

Module: sevn.docs.readme.profile_schemas
Depends: dataclasses

Exports:
    ProfileSchema — one profile's checker contract.
    get_profile_schema — lookup with KeyError on unknown profile.

Examples:
    >>> from sevn.docs.readme.profile_schemas import get_profile_schema
    >>> schema = get_profile_schema("subsystem")
    >>> schema.needs_tiers
    True
    >>> get_profile_schema("root").requires_summary
    False
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProfileSchema:
    """Checker schema for one README profile (§C0)."""

    required_headings: tuple[str, ...]
    needs_tiers: bool
    verify_symbol_refs: bool
    allow_extra_headings: bool
    requires_summary: bool = True
    requires_table: bool = False
    requires_step_sections: bool = False
    verify_path_refs: bool = False


PROFILE_SCHEMAS: dict[str, ProfileSchema] = {
    "root": ProfileSchema(
        required_headings=(
            "Highlights",
            "Architecture at a glance",
            "Subsystem map",
            "Quick start",
            "Install",
            "License",
        ),
        needs_tiers=False,
        verify_symbol_refs=False,
        allow_extra_headings=True,
        requires_summary=False,
    ),
    "subsystem": ProfileSchema(
        required_headings=(
            "Level 1 — Overview",
            "Level 2 — How it works",
            "Level 3 — Deep dive",
            "References",
        ),
        needs_tiers=True,
        verify_symbol_refs=True,
        allow_extra_headings=True,
    ),
    "index": ProfileSchema(
        required_headings=(),
        needs_tiers=False,
        verify_symbol_refs=False,
        allow_extra_headings=True,
        requires_table=True,
    ),
    "catalog": ProfileSchema(
        required_headings=(),
        needs_tiers=False,
        verify_symbol_refs=False,
        allow_extra_headings=True,
        requires_table=True,
        verify_path_refs=True,
    ),
    "guide": ProfileSchema(
        required_headings=("References",),
        needs_tiers=False,
        verify_symbol_refs=False,
        allow_extra_headings=True,
        requires_step_sections=True,
    ),
    "freeform": ProfileSchema(
        required_headings=(),
        needs_tiers=False,
        verify_symbol_refs=False,
        allow_extra_headings=True,
    ),
}


def get_profile_schema(profile: str) -> ProfileSchema:
    """Return the §C0 schema for ``profile``.

        Args:
    profile (str): Manifest profile name.

        Returns:
            ProfileSchema: Checker contract for the profile.

        Raises:
            KeyError: When ``profile`` is not registered.

        Examples:
            >>> get_profile_schema("freeform").verify_symbol_refs
            False
    """
    try:
        return PROFILE_SCHEMAS[profile]
    except KeyError as exc:
        msg = f"unknown README profile: {profile!r}"
        raise KeyError(msg) from exc
