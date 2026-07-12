"""MYCODE scan digest cache (`specs/28-code-understanding.md` §11).

Exports:
    cache_path_for_root — resolve cache path for a repository root.
    scan_repo_cached — return cached digest when the tree fingerprint matches.
    save_scan_cache — persist digest + fingerprint after a full scan.
"""

from __future__ import annotations

import json
import os
from pathlib import Path  # noqa: TC003 — runtime cache paths
from typing import TYPE_CHECKING

from sevn.code_understanding.models import MycodeFileEntry, MycodeScanDigest
from sevn.code_understanding.mycode_scan import scan_repo

if TYPE_CHECKING:
    from collections.abc import Iterable

MYCODE_CACHE_FILENAME = "mycode-scan.cache.json"
_CACHE_VERSION = 1


def cache_path_for_root(root: Path) -> Path:
    """Return ``<root>/.sevn/mycode-scan.cache.json``.

    Args:
        root (Path): Repository root.

    Returns:
        Path: Cache file path.

    Examples:
        >>> cache_path_for_root(Path("/repo")).name
        'mycode-scan.cache.json'
    """
    return root.resolve() / ".sevn" / MYCODE_CACHE_FILENAME


def _fingerprint(root: Path, ignore: list[str]) -> dict[str, object]:
    """Build a deterministic map of relative path → (mtime_ns, size).

    Enumerates the same gitignore-aware file set as ``scan_repo`` (tracked files only
    for a git checkout), so the cache fingerprint changes exactly when the scanned set
    changes — gitignored files on disk never invalidate the cache.

    Args:
        root (Path): Repository root.
        ignore (list[str]): Ignore patterns passed to ``scan_repo``.

    Returns:
        dict[str, object]: Serializable fingerprint payload.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path as _P
        >>> d = _P(tempfile.mkdtemp())
        >>> _ = (d / "z.py").write_text("1\\n", encoding="utf-8")
        >>> fp = _fingerprint(d, [])
        >>> "z.py" in fp["files"]
        True
    """
    root = root.resolve()
    files: dict[str, list[int]] = {}
    from sevn.code_understanding.mycode_scan import _enumerate_files, _looks_ignored

    for path in _enumerate_files(root):
        rel = path.relative_to(root).as_posix()
        if _looks_ignored(rel, ignore):
            continue
        try:
            st = path.stat()
        except OSError:
            continue
        files[rel] = [st.st_mtime_ns, st.st_size]
    return {"ignore": list(ignore), "files": files}


def _digest_from_json(payload: dict[str, object]) -> MycodeScanDigest | None:
    """Rehydrate a ``MycodeScanDigest`` from a cache JSON document.

    Args:
        payload (dict[str, object]): Parsed cache file body.

    Returns:
        MycodeScanDigest | None: Digest when fields validate; else ``None``.

    Examples:
        >>> _digest_from_json({"root": "/r", "ignored": [], "digest_files": []}) is not None
        True
    """
    raw_files = payload.get("digest_files")
    if not isinstance(raw_files, list):
        return None
    files: list[MycodeFileEntry] = []
    for item in raw_files:
        if not isinstance(item, dict):
            continue
        files.append(MycodeFileEntry.model_validate(item))
    root = payload.get("root")
    ignored = payload.get("ignored")
    if not isinstance(root, str):
        return None
    ign_list = [str(x) for x in ignored] if isinstance(ignored, list) else []
    return MycodeScanDigest(root=root, files=files, ignored=ign_list)


def scan_repo_cached(root: Path, ignore: Iterable[str]) -> MycodeScanDigest:
    """Scan ``root`` or return a cached digest when the fingerprint is unchanged.

    Args:
        root (Path): Repository root.
        ignore (Iterable[str]): Ignore patterns for ``scan_repo``.

    Returns:
        MycodeScanDigest: Fresh or cached scan result.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path as _P
        >>> d = _P(tempfile.mkdtemp())
        >>> _ = (d / "a.py").write_text("x = 1\\n", encoding="utf-8")
        >>> digest = scan_repo_cached(d, [])
        >>> digest.files[0].path
        'a.py'
    """
    ignore_list = [str(p) for p in ignore]
    if ".sevn" not in ignore_list and ".sevn/**" not in ignore_list:
        ignore_list = [*ignore_list, ".sevn", ".sevn/**"]
    root = root.resolve()
    cache_path = cache_path_for_root(root)
    fp = _fingerprint(root, ignore_list)
    if cache_path.is_file():
        try:
            doc = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            doc = None
        if (
            isinstance(doc, dict)
            and doc.get("version") == _CACHE_VERSION
            and doc.get("fingerprint") == fp
        ):
            digest = _digest_from_json(doc)
            if digest is not None:
                return digest
    digest = scan_repo(root, ignore_list)
    save_scan_cache(root, ignore_list, digest)
    return digest


def save_scan_cache(root: Path, ignore: Iterable[str], digest: MycodeScanDigest) -> Path:
    """Write digest + tree fingerprint atomically under ``.sevn/``.

    Args:
        root (Path): Repository root.
        ignore (Iterable[str]): Ignore patterns used for the scan.
        digest (MycodeScanDigest): Scan result to persist.

    Returns:
        Path: Cache file path.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path as _P
        >>> from sevn.code_understanding.models import MycodeScanDigest
        >>> d = _P(tempfile.mkdtemp())
        >>> p = save_scan_cache(d, [], MycodeScanDigest(root=str(d), files=[], ignored=[]))
        >>> p.exists()
        True
    """
    ignore_list = [str(p) for p in ignore]
    if ".sevn" not in ignore_list and ".sevn/**" not in ignore_list:
        ignore_list = [*ignore_list, ".sevn", ".sevn/**"]
    root = root.resolve()
    cache_path = cache_path_for_root(root)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "version": _CACHE_VERSION,
        "fingerprint": _fingerprint(root, ignore_list),
        "root": digest.root,
        "ignored": list(digest.ignored),
        "digest_files": [f.model_dump() for f in digest.files],
    }
    tmp = cache_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, cache_path)
    return cache_path


__all__ = [
    "MYCODE_CACHE_FILENAME",
    "cache_path_for_root",
    "save_scan_cache",
    "scan_repo_cached",
]
