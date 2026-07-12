"""Pure helpers for Graphify profile resolution and Triager prefix text.

Module: sevn.code_understanding.graphify
Depends: pathlib, sevn.code_understanding.models

The module-level ``BOOTSTRAP_OUTPUT_REL`` constant names the default Graphify
output subpath used when bootstrap creates the ``default`` profile.

Exports:
    Functions:
        resolve_profiles — return profiles after applying bootstrap rule.
        graph_report_path — locate ``GRAPH_REPORT.md`` for a profile.
        graph_json_path — locate ``graph.json`` for a profile.
        profile_covers — test whether a query path is under a profile root.
        search_tool_prefix — Triager/executor prefix text per §2.5.
        active_profiles_with_report — filter to profiles with an on-disk report.
        resolve_active_profiles_cached — TTL-cached resolve + active-report filter.
        clear_resolve_active_profiles_cache — test helper to reset the TTL cache.
"""

from __future__ import annotations

import time
from pathlib import Path

from sevn.code_understanding.models import GraphifyProfile, GraphifySettings
from sevn.config.defaults import (
    DEFAULT_GRAPHIFY_SEVN_OUTPUT_REL,
    DEFAULT_GRAPHIFY_SEVN_PROFILE_ID,
)
from sevn.config.sevn_repo import try_resolve_sevn_repo_root

BOOTSTRAP_OUTPUT_REL: str = ".index/graphify"

_PREFIX_TEMPLATE: str = (
    "Graphify profile {id}: knowledge graph present. "
    "Read {output_dir}/GRAPH_REPORT.md for god nodes and community structure "
    "before expanding raw search."
)


def resolve_profiles(
    settings: GraphifySettings,
    primary_repo_root: Path,
) -> list[GraphifyProfile]:
    """Return the active Graphify profile list, applying the bootstrap rule.

    When ``settings.enabled`` is True and ``settings.profiles`` is empty,
    a single ``default`` profile is created rooted at ``primary_repo_root``
    with output under ``<primary_repo_root>/.index/graphify``.
    When ``settings.enabled`` is False the function returns an empty list
    regardless of declared profiles.

    Args:
        settings (GraphifySettings): Parsed ``graphify`` subtree.
        primary_repo_root (Path): Workspace primary repo root for bootstrap.

    Returns:
        list[GraphifyProfile]: Profiles to consider for orientation + prefix.

    Examples:
        >>> from sevn.code_understanding.models import GraphifySettings
        >>> from pathlib import Path as _P
        >>> resolve_profiles(GraphifySettings(), _P("/r"))
        []
        >>> profiles = resolve_profiles(
        ...     GraphifySettings(enabled=True), _P("/r")
        ... )
        >>> profiles[0].id
        'default'
    """
    if not settings.enabled:
        return []
    if settings.profiles:
        return list(settings.profiles)
    sevn_root = try_resolve_sevn_repo_root(primary_repo_root)
    if sevn_root is not None:
        out_dir = sevn_root / DEFAULT_GRAPHIFY_SEVN_OUTPUT_REL
        return [
            GraphifyProfile(
                id=DEFAULT_GRAPHIFY_SEVN_PROFILE_ID,
                label="sevn.bot",
                root_path=str(sevn_root),
                output_dir=str(out_dir),
            )
        ]
    root_abs = primary_repo_root.resolve()
    out_dir = root_abs / BOOTSTRAP_OUTPUT_REL
    return [
        GraphifyProfile(
            id="default",
            label="default",
            root_path=str(root_abs),
            output_dir=str(out_dir),
        )
    ]


def graph_report_path(profile: GraphifyProfile) -> Path:
    """Return the ``GRAPH_REPORT.md`` path for ``profile``.

    Args:
        profile (GraphifyProfile): One resolved profile.

    Returns:
        Path: ``<output_dir>/GRAPH_REPORT.md``.

    Examples:
        >>> from sevn.code_understanding.models import GraphifyProfile
        >>> graph_report_path(
        ...     GraphifyProfile(id="d", root_path="/r", output_dir="/o")
        ... ).as_posix()
        '/o/GRAPH_REPORT.md'
    """
    return Path(profile.output_dir) / "GRAPH_REPORT.md"


def graph_json_path(profile: GraphifyProfile) -> Path:
    """Return the ``graph.json`` path for ``profile``.

    Args:
        profile (GraphifyProfile): One resolved profile.

    Returns:
        Path: ``<output_dir>/graph.json``.

    Examples:
        >>> from sevn.code_understanding.models import GraphifyProfile
        >>> graph_json_path(
        ...     GraphifyProfile(id="d", root_path="/r", output_dir="/o")
        ... ).as_posix()
        '/o/graph.json'
    """
    return Path(profile.output_dir) / "graph.json"


def profile_covers(profile: GraphifyProfile, query_path: Path) -> bool:
    """Return True iff ``query_path`` resolves under ``profile.root_path``.

    Path comparison uses absolute resolution so symlinks and relative inputs
    behave predictably. The profile root itself is considered covered.

    Args:
        profile (GraphifyProfile): One resolved profile.
        query_path (Path): Filesystem path (file or directory).

    Returns:
        bool: Whether the profile covers the query.

    Examples:
        >>> from sevn.code_understanding.models import GraphifyProfile
        >>> from pathlib import Path as _P
        >>> p = GraphifyProfile(id="d", root_path="/r", output_dir="/o")
        >>> profile_covers(p, _P("/r/sub/x.py"))
        True
        >>> profile_covers(p, _P("/other"))
        False
    """
    try:
        root = Path(profile.root_path).resolve()
        query = query_path.resolve()
    except OSError:
        return False
    try:
        query.relative_to(root)
    except ValueError:
        return False
    return True


def search_tool_prefix(profile: GraphifyProfile) -> str:
    """Return the executor search-tool prefix string for ``profile`` (§2.5).

    Args:
        profile (GraphifyProfile): Profile whose report text should be cited.

    Returns:
        str: Prefix text with ``id`` and ``output_dir`` substituted.

    Examples:
        >>> from sevn.code_understanding.models import GraphifyProfile
        >>> text = search_tool_prefix(
        ...     GraphifyProfile(id="default", root_path="/r", output_dir="/o")
        ... )
        >>> "Graphify profile default" in text
        True
    """
    return _PREFIX_TEMPLATE.format(id=profile.id, output_dir=profile.output_dir)


_ProfileCacheEntry = tuple[list[GraphifyProfile], float]

_profile_cache: dict[tuple[str, str], _ProfileCacheEntry] = {}


def _settings_fingerprint(settings: GraphifySettings) -> str:
    """Return a stable cache key fragment for ``GraphifySettings``.

    Args:
        settings (GraphifySettings): Parsed ``graphify`` subtree.

    Returns:
        str: Sorted ``model_dump`` repr for key separation.

    Examples:
        >>> from sevn.code_understanding.models import GraphifySettings
        >>> isinstance(_settings_fingerprint(GraphifySettings()), str)
        True
    """
    return repr(sorted(settings.model_dump().items()))


def clear_resolve_active_profiles_cache() -> None:
    """Clear the module-level Graphify profile TTL cache (tests only).

    Returns:
        None

    Examples:
        >>> clear_resolve_active_profiles_cache() is None
        True
    """
    _profile_cache.clear()


def resolve_active_profiles_cached(
    settings: GraphifySettings,
    profile_root: Path,
    *,
    ttl_s: float = 60.0,
) -> list[GraphifyProfile]:
    """Resolve profiles with on-disk reports, memoized for ``ttl_s`` seconds.

    Wraps :func:`active_profiles_with_report` ∘ :func:`resolve_profiles` with a
    module-level TTL keyed by ``(profile_root.resolve(), settings fingerprint)``.

    Args:
        settings (GraphifySettings): Parsed ``graphify`` subtree.
        profile_root (Path): Workspace checkout or content root for bootstrap.
        ttl_s (float): Cache lifetime in seconds (monotonic clock).

    Returns:
        list[GraphifyProfile]: Profiles whose ``GRAPH_REPORT.md`` exists.

    Examples:
        >>> from sevn.code_understanding.models import GraphifySettings
        >>> from pathlib import Path as _P
        >>> resolve_active_profiles_cached(GraphifySettings(), _P("/r"))
        []
    """
    key = (str(profile_root.resolve()), _settings_fingerprint(settings))
    now = time.monotonic()
    cached = _profile_cache.get(key)
    if cached is not None and now < cached[1]:
        return list(cached[0])
    profiles = active_profiles_with_report(resolve_profiles(settings, profile_root))
    _profile_cache[key] = (profiles, now + ttl_s)
    return profiles


def active_profiles_with_report(
    profiles: list[GraphifyProfile],
) -> list[GraphifyProfile]:
    """Filter ``profiles`` to those whose ``GRAPH_REPORT.md`` exists on disk.

    Args:
        profiles (list[GraphifyProfile]): Resolved profile list.

    Returns:
        list[GraphifyProfile]: Subset with a readable report file.

    Examples:
        >>> active_profiles_with_report([])
        []
    """
    out: list[GraphifyProfile] = []
    for profile in profiles:
        if graph_report_path(profile).is_file():
            out.append(profile)
    return out
