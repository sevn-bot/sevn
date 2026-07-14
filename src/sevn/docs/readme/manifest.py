"""Parse ``manifest.toml`` — curated README set for generation and gate.

Module: sevn.docs.readme.manifest
Depends: pathlib, tomllib, sevn.docs.readme.profiles

Exports:
    ReadmeEntry — one manifest row (slug, profile, source_globs, …).
    ReadmeManifest — parsed manifest with version and entries.
    load_manifest — read and validate ``manifest.toml``.
    get_entry — lookup one entry by slug.

Examples:
    >>> from pathlib import Path
    >>> m = load_manifest(Path("docs/readmes/manifest.toml"))
    >>> any(e.slug == "gateway" for e in m.entries)
    True
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from sevn.docs.readme.profiles import PROFILE_TEMPLATES

_VALID_PROFILES = frozenset(PROFILE_TEMPLATES)
_VALID_CATALOG_KINDS = frozenset({"modules", "skills"})


@dataclass(frozen=True)
class ReadmeEntry:
    """One README row from ``manifest.toml``."""

    slug: str
    title: str
    summary: str
    profile: str
    tier_owner: str
    output: str
    source_globs: tuple[str, ...]
    specs: tuple[str, ...]
    curated: bool = False
    turn_spine: bool = False
    catalog: str = "modules"
    template: str = ""


@dataclass(frozen=True)
class ReadmeManifest:
    """Parsed README manifest."""

    version: int
    entries: tuple[ReadmeEntry, ...]


def load_manifest(path: Path) -> ReadmeManifest:
    """Load and validate the README manifest at ``path``.

        Args:
    path (Path): Path to ``manifest.toml``.

        Returns:
            ReadmeManifest: Parsed entries with validated profile names.

        Raises:
            FileNotFoundError: When ``path`` is missing.
            ValueError: When structure or profile names are invalid.

        Examples:
            >>> from pathlib import Path as _P
            >>> m = load_manifest(_P("docs/readmes/manifest.toml"))
            >>> m.version >= 1
            True
    """
    raw = path.read_bytes()
    data = tomllib.loads(raw.decode("utf-8"))
    version = int(data.get("version", 0))
    rows = data.get("readme")
    if not isinstance(rows, list) or not rows:
        msg = f"{path}: expected non-empty [[readme]] table array"
        raise ValueError(msg)

    entries: list[ReadmeEntry] = []
    seen_slugs: set[str] = set()
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            msg = f"{path}: readme[{idx}] must be a table"
            raise ValueError(msg)
        slug = str(row.get("slug", "")).strip()
        if not slug:
            msg = f"{path}: readme[{idx}] missing slug"
            raise ValueError(msg)
        if slug in seen_slugs:
            msg = f"{path}: duplicate slug {slug!r}"
            raise ValueError(msg)
        seen_slugs.add(slug)

        profile = str(row.get("profile", "")).strip()
        if profile not in _VALID_PROFILES:
            known = ", ".join(sorted(_VALID_PROFILES))
            msg = f"{path}: readme[{idx}] profile={profile!r}; expected one of: {known}"
            raise ValueError(msg)

        source_globs = _as_str_tuple(row.get("source_globs"))
        if not source_globs:
            msg = f"{path}: readme[{idx}] slug={slug!r} missing source_globs"
            raise ValueError(msg)

        curated = _parse_curated(row.get("curated"), path=path, idx=idx)
        turn_spine = _parse_turn_spine(row.get("turn_spine"), path=path, idx=idx)
        catalog = _parse_catalog(row.get("catalog"), path=path, idx=idx)
        template = _parse_template(row.get("template"), path=path, idx=idx)

        entries.append(
            ReadmeEntry(
                slug=slug,
                title=str(row.get("title", slug)).strip(),
                summary=str(row.get("summary", "")).strip(),
                profile=profile,
                tier_owner=str(row.get("tier_owner", "")).strip(),
                output=str(row.get("output", f"docs/readmes/{slug}.md")).strip(),
                source_globs=source_globs,
                specs=_as_str_tuple(row.get("specs")),
                curated=curated,
                turn_spine=turn_spine,
                catalog=catalog,
                template=template,
            )
        )

    return ReadmeManifest(version=version, entries=tuple(entries))


def get_entry(manifest: ReadmeManifest, slug: str) -> ReadmeEntry:
    """Return the manifest entry for ``slug``.

        Args:
    manifest (ReadmeManifest): Loaded manifest.
    slug (str): Entry slug (e.g. ``gateway``).

        Returns:
            ReadmeEntry: Matching row.

        Raises:
            KeyError: When ``slug`` is absent.

        Examples:
            >>> from pathlib import Path as _P
            >>> m = load_manifest(_P("docs/readmes/manifest.toml"))
            >>> get_entry(m, "gateway").profile
            'subsystem'
    """
    for entry in manifest.entries:
        if entry.slug == slug:
            return entry
    msg = f"manifest entry not found: {slug!r}"
    raise KeyError(msg)


def _parse_curated(value: object, *, path: Path, idx: int) -> bool:
    """Parse optional ``curated`` manifest key (defaults to false).

        Args:
    value (object): Raw TOML value or ``None`` when omitted.
    path (Path): Manifest path for error messages.
    idx (int): Row index for error messages.

        Returns:
            bool: Parsed curated flag.

        Raises:
            ValueError: When ``curated`` is present but not a boolean.

        Examples:
            >>> _parse_curated(None, path=Path("m.toml"), idx=0)
            False
            >>> _parse_curated(True, path=Path("m.toml"), idx=0)
            True
    """
    if value is None:
        return False
    if not isinstance(value, bool):
        msg = f"{path}: readme[{idx}] curated must be a boolean"
        raise ValueError(msg)
    return value


def _parse_turn_spine(value: object, *, path: Path, idx: int) -> bool:
    """Parse optional ``turn_spine`` manifest key (defaults to false).

        Args:
    value (object): Raw TOML value or ``None`` when omitted.
    path (Path): Manifest path for error messages.
    idx (int): Row index for error messages.

        Returns:
            bool: Parsed turn-spine flag.

        Raises:
            ValueError: When ``turn_spine`` is present but not a boolean.

        Examples:
            >>> _parse_turn_spine(None, path=Path("m.toml"), idx=0)
            False
            >>> _parse_turn_spine(True, path=Path("m.toml"), idx=0)
            True
    """
    if value is None:
        return False
    if not isinstance(value, bool):
        msg = f"{path}: readme[{idx}] turn_spine must be a boolean"
        raise ValueError(msg)
    return value


def _parse_catalog(value: object, *, path: Path, idx: int) -> str:
    """Parse optional ``catalog`` manifest key (defaults to ``modules``).

        Args:
    value (object): Raw TOML value or ``None`` when omitted.
    path (Path): Manifest path for error messages.
    idx (int): Row index for error messages.

        Returns:
            str: Parsed catalog kind.

        Raises:
            ValueError: When ``catalog`` is present but not a valid enum member.

        Examples:
            >>> _parse_catalog(None, path=Path("m.toml"), idx=0)
            'modules'
            >>> _parse_catalog("skills", path=Path("m.toml"), idx=0)
            'skills'
    """
    if value is None:
        return "modules"
    if not isinstance(value, str):
        msg = f"{path}: readme[{idx}] catalog must be a string"
        raise ValueError(msg)
    kind = value.strip()
    if kind not in _VALID_CATALOG_KINDS:
        known = ", ".join(sorted(_VALID_CATALOG_KINDS))
        msg = f"{path}: readme[{idx}] catalog={kind!r}; expected one of: {known}"
        raise ValueError(msg)
    return kind


def _parse_template(value: object, *, path: Path, idx: int) -> str:
    """Parse optional ``template`` manifest key (repo-relative path, defaults to empty).

        Args:
    value (object): Raw TOML value or ``None`` when omitted.
    path (Path): Manifest path for error messages.
    idx (int): Row index for error messages.

        Returns:
            str: Repo-relative template path, or ``""`` to use the slug convention.

        Raises:
            ValueError: When ``template`` is present but not a string.

        Examples:
            >>> _parse_template(None, path=Path("m.toml"), idx=0)
            ''
            >>> _parse_template("docs/readmes/_templates/gateway.md", path=Path("m.toml"), idx=0)
            'docs/readmes/_templates/gateway.md'
    """
    if value is None:
        return ""
    if not isinstance(value, str):
        msg = f"{path}: readme[{idx}] template must be a string"
        raise ValueError(msg)
    return value.strip()


def _as_str_tuple(value: object) -> tuple[str, ...]:
    """Coerce a TOML list value to a tuple of non-empty strings.

        Args:
    value (object): Raw TOML value.

        Returns:
            tuple[str, ...]: Normalized strings.

        Examples:
            >>> _as_str_tuple(["a", ""])
            ('a',)
    """
    if not isinstance(value, list):
        return ()
    out: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            out.append(text)
    return tuple(out)
