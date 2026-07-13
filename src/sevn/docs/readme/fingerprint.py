"""Source fingerprints for README staleness gate (STANDARD §F).

Module: sevn.docs.readme.fingerprint
Depends: hashlib, json, pathlib, datetime

Exports:
    expand_source_globs — expand manifest globs to fingerprinted files.
    compute_digest — sha256 aggregate digest for ``source_globs``.
    default_fingerprints_path — default ``docs/readmes/_fingerprints.json`` path.
    load_fingerprints — read stored fingerprint JSON.
    save_fingerprints — write fingerprint JSON atomically.
    upsert_entry — update one slug row in the fingerprint store.
    stamp_entry — recompute and persist one slug fingerprint (no README write).
    path_matches_source_glob — whether a repo-relative path matches one manifest glob.
    slugs_for_changed_paths — manifest slugs whose ``source_globs`` cover changed paths.

Examples:
    >>> from pathlib import Path
    >>> digest = compute_digest(Path("."), ("Makefile",))
    >>> len(digest) == 64
    True
"""

from __future__ import annotations

import hashlib
import json
import subprocess  # nosec B404 — fixed-argv `git ls-files` only, no shell
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

FINGERPRINTS_FILENAME = "_fingerprints.json"
_ALGORITHM = "sha256_glob_aggregate"
_SKIP_DIR_NAMES = frozenset(
    {"__pycache__", ".git", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".venv"}
)
_SKIP_SUFFIXES = frozenset({".pyc", ".pyo"})


def expand_source_globs(
    repo_root: Path,
    source_globs: Sequence[str],
    *,
    tracked_only: bool = True,
) -> list[Path]:
    """Expand ``source_globs`` to sorted, fingerprint-eligible files.

        Args:
    repo_root (Path): Repository root.
    source_globs (Sequence[str]): Manifest glob patterns (repo-relative).
    tracked_only (bool): When True (default), restrict to ``git ls-files`` paths
        for staleness fingerprints. When False, include all matching files on disk
        (used by the README scanner for content extraction).

        Returns:
            list[Path]: Absolute paths, sorted by repo-relative posix path.

        Examples:
            >>> from pathlib import Path as _P
            >>> import tempfile
            >>> td = _P(tempfile.mkdtemp())
            >>> pkg = td / "pkg"
            >>> pkg.mkdir()
            >>> _ = (pkg / "ok.py").write_text("1\\n", encoding="utf-8")
            >>> files = expand_source_globs(td, ("pkg/**",), tracked_only=False)
            >>> [p.name for p in files]
            ['ok.py']
    """
    repo_root = repo_root.resolve()
    tracked = _tracked_files(repo_root) if tracked_only else None
    by_rel: dict[str, Path] = {}
    for pattern in source_globs:
        for match in _expand_one_glob(repo_root, pattern):
            if not match.is_file():
                continue
            if not _should_fingerprint(repo_root, match):
                continue
            rel = match.relative_to(repo_root).as_posix()
            if tracked is not None and rel not in tracked:
                continue
            by_rel[rel] = match
    return [by_rel[key] for key in sorted(by_rel)]


def path_matches_source_glob(rel_posix: str, pattern: str) -> bool:
    """Return whether ``rel_posix`` matches one manifest ``source_globs`` pattern.

    Args:
        rel_posix (str): Repo-relative posix path.
        pattern (str): Manifest glob (supports trailing ``/**`` trees).

    Returns:
        bool: True when the path is covered by ``pattern``.

    Examples:
        >>> path_matches_source_glob("src/sevn/gateway/x.py", "src/sevn/gateway/**")
        True
        >>> path_matches_source_glob("Makefile", "Makefile")
        True
    """
    if pattern.endswith("/**"):
        base = pattern[:-3]
        return rel_posix == base or rel_posix.startswith(f"{base}/")
    return PurePosixPath(rel_posix).match(pattern)


def slugs_for_changed_paths(
    repo_root: Path,
    *,
    entries: Sequence[object],
    changed_paths: Sequence[str | Path],
) -> tuple[str, ...]:
    """Return manifest slugs whose ``source_globs`` include any changed path.

    Args:
        repo_root (Path): Repository root.
        entries (Sequence[object]): Manifest rows with ``slug`` and ``source_globs``.
        changed_paths (Sequence[str | Path]): Staged or passed-in file paths.

    Returns:
        tuple[str, ...]: Sorted unique slugs to regenerate.

    Examples:
        >>> from sevn.docs.readme.manifest import ReadmeEntry
        >>> from pathlib import Path as _P
        >>> entry = ReadmeEntry(
        ...     "gateway", "G", "S", "subsystem", "gateway", "docs/readmes/gateway.md",
        ...     ("src/sevn/gateway/**",), (),
        ... )
        >>> slugs = slugs_for_changed_paths(
        ...     _P("."),
        ...     entries=[entry],
        ...     changed_paths=["src/sevn/gateway/http_server.py"],
        ... )
        >>> slugs
        ('gateway',)
    """
    root = repo_root.resolve()
    rel_paths: set[str] = set()
    for raw in changed_paths:
        path = Path(raw)
        if not path.is_absolute():
            path = root / path
        try:
            rel_paths.add(path.resolve().relative_to(root).as_posix())
        except ValueError:
            continue

    affected: set[str] = set()
    for row in entries:
        slug = getattr(row, "slug", None)
        source_globs = getattr(row, "source_globs", None)
        if not isinstance(slug, str) or not source_globs:
            continue
        for rel in rel_paths:
            if any(path_matches_source_glob(rel, pattern) for pattern in source_globs):
                affected.add(slug)
                break
    return tuple(sorted(affected))


def _tracked_files(repo_root: Path) -> frozenset[str] | None:
    """Return git-tracked repo-relative paths, or None outside a git checkout.

        Args:
    repo_root (Path): Repository root.

        Returns:
            frozenset[str] | None: Tracked posix paths; None when git is unavailable.

        Examples:
            >>> from pathlib import Path as _P
            >>> import tempfile
            >>> _tracked_files(_P(tempfile.mkdtemp())) is None
            True
    """
    # Fingerprints must be reproducible on fresh clones and CI runners, where
    # only committed files exist. Local build artefacts matched by the globs
    # (e.g. `make styles-build` output under src/sevn/ui/style/) would
    # otherwise make locally computed digests diverge from runner digests.
    try:
        out = subprocess.run(  # nosec B603 B607 — fixed argv, `git` from PATH by design
            ["git", "-C", str(repo_root), "ls-files", "-z"],
            capture_output=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    return frozenset(p.decode("utf-8") for p in out.split(b"\0") if p)


def _expand_one_glob(repo_root: Path, pattern: str) -> list[Path]:
    """Expand one manifest glob pattern under ``repo_root``.

        Args:
    repo_root (Path): Repository root.
    pattern (str): Manifest glob (supports trailing ``/**`` trees).

        Returns:
            list[Path]: Matching file paths.

        Examples:
            >>> from pathlib import Path as _P
            >>> import tempfile
            >>> td = _P(tempfile.mkdtemp())
            >>> _ = (td / "Makefile").write_text("x\\n", encoding="utf-8")
            >>> _expand_one_glob(td, "Makefile")[0].name
            'Makefile'
    """
    if pattern.endswith("/**"):
        base = repo_root / pattern[:-3]
        if not base.is_dir():
            return []
        return [path for path in base.rglob("*") if path.is_file()]
    direct = repo_root / pattern
    if direct.is_file():
        return [direct]
    return [path for path in repo_root.glob(pattern) if path.is_file()]


def compute_digest(repo_root: Path, source_globs: Sequence[str]) -> str:
    """Compute the aggregate sha256 digest for ``source_globs``.

        Args:
    repo_root (Path): Repository root.
    source_globs (Sequence[str]): Manifest glob patterns.

        Returns:
            str: Lowercase 64-char hex digest.

        Examples:
            >>> from pathlib import Path as _P
            >>> d1 = compute_digest(_P("."), ("Makefile",))
            >>> d2 = compute_digest(_P("."), ("Makefile",))
            >>> d1 == d2
            True
    """
    lines: list[str] = []
    for path in expand_source_globs(repo_root, source_globs):
        rel = path.resolve().relative_to(repo_root.resolve()).as_posix()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{rel}\t{digest}")
    payload = "\n".join(lines)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def default_fingerprints_path(repo_root: Path) -> Path:
    """Return the default ``docs/readmes/_fingerprints.json`` path.

        Args:
    repo_root (Path): Repository root.

        Returns:
            Path: Fingerprint store location.

        Examples:
            >>> default_fingerprints_path(Path(".")).name
            '_fingerprints.json'
    """
    return repo_root / "docs" / "readmes" / FINGERPRINTS_FILENAME


def load_fingerprints(path: Path) -> dict[str, Any]:
    """Load fingerprint JSON from ``path``.

        Args:
    path (Path): ``_fingerprints.json`` location.

        Returns:
            dict[str, Any]: Parsed document; empty scaffold when missing.

        Examples:
            >>> load_fingerprints(Path("/nonexistent/_fingerprints.json"))["version"]
            1
    """
    if not path.is_file():
        return {"version": 1, "entries": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        msg = f"{path}: fingerprint document must be a JSON object"
        raise ValueError(msg)
    entries = data.get("entries")
    if entries is None:
        data["entries"] = {}
    elif not isinstance(entries, dict):
        msg = f"{path}: entries must be an object"
        raise ValueError(msg)
    if "version" not in data:
        data["version"] = 1
    return data


def save_fingerprints(path: Path, data: dict[str, Any]) -> None:
    """Write fingerprint JSON to ``path``.

        Args:
    path (Path): Destination ``_fingerprints.json``.
    data (dict[str, Any]): Document with ``version`` and ``entries``.

        Examples:
            >>> from pathlib import Path as _P
            >>> import tempfile
            >>> td = _P(tempfile.mkdtemp())
            >>> fp = td / "_fingerprints.json"
            >>> save_fingerprints(fp, {"version": 1, "entries": {}})
            >>> fp.is_file()
            True
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def stamp_entry(
    repo_root: Path,
    *,
    slug: str,
    source_globs: Sequence[str],
    fingerprints_path: Path,
) -> None:
    """Recompute and store one slug fingerprint without touching README bodies.

        Args:
    repo_root (Path): Repository root.
    slug (str): Manifest slug key.
    source_globs (Sequence[str]): Globs used for the digest.
    fingerprints_path (Path): ``_fingerprints.json`` location.

        Examples:
            >>> from pathlib import Path as _P
            >>> import tempfile
            >>> td = _P(tempfile.mkdtemp())
            >>> _ = (td / "Makefile").write_text("x\\n", encoding="utf-8")
            >>> fp = td / "_fingerprints.json"
            >>> stamp_entry(td, slug="gateway", source_globs=["Makefile"], fingerprints_path=fp)
            >>> fp.is_file()
            True
    """
    store = load_fingerprints(fingerprints_path)
    digest = compute_digest(repo_root, source_globs)
    upsert_entry(store, slug=slug, digest=digest, source_globs=source_globs)
    save_fingerprints(fingerprints_path, store)


def upsert_entry(
    store: dict[str, Any],
    *,
    slug: str,
    digest: str,
    source_globs: Sequence[str],
    computed_at: datetime | None = None,
) -> None:
    """Insert or replace one slug row in an in-memory fingerprint store.

        Args:
    store (dict[str, Any]): Mutable store from :func:`load_fingerprints`.
    slug (str): Manifest slug key.
    digest (str): Aggregate digest hex.
    source_globs (Sequence[str]): Globs used for the digest.
    computed_at (datetime | None): UTC timestamp; defaults to now.

        Examples:
            >>> store: dict[str, object] = {"version": 1, "entries": {}}
            >>> upsert_entry(store, slug="gateway", digest="a" * 64, source_globs=["src/**"])
            >>> store["entries"]["gateway"]["algorithm"]
            'sha256_glob_aggregate'
    """
    when = computed_at or datetime.now(tz=UTC)
    entries = store.setdefault("entries", {})
    if not isinstance(entries, dict):
        msg = "store entries must be a dict"
        raise TypeError(msg)
    entries[slug] = {
        "algorithm": _ALGORITHM,
        "digest": digest,
        "computed_at": when.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "source_globs": list(source_globs),
    }


def _should_fingerprint(repo_root: Path, path: Path) -> bool:
    """Return whether ``path`` should contribute to a fingerprint.

        Args:
    repo_root (Path): Repository root.
    path (Path): Candidate file path.

        Returns:
            bool: True when the file should be hashed.

        Examples:
            >>> from pathlib import Path as _P
            >>> import tempfile
            >>> td = _P(tempfile.mkdtemp())
            >>> path = td / "src/a.py"
            >>> path.parent.mkdir(parents=True)
            >>> _ = path.write_text("x\\n", encoding="utf-8")
            >>> _should_fingerprint(td, path)
            True
    """
    try:
        rel = path.resolve().relative_to(repo_root.resolve())
    except ValueError:
        return False
    if any(part in _SKIP_DIR_NAMES for part in rel.parts):
        return False
    return path.suffix.lower() not in _SKIP_SUFFIXES
