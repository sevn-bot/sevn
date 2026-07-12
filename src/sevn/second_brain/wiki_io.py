"""Read/atomic write for wiki pages (`specs/27-second-brain.md` §2.2, §3.3).

Patch format: **full replacement** — ``patch`` is the complete new file text (UTF-8), including
frontmatter. ``base_hash`` is SHA-256 hex of the current on-disk file (full bytes).

Exports:
    file_sha256_hex — digest of on-disk file bytes.
    content_sha256_hex — digest of UTF-8 text.
    wiki_read — read full text plus split frontmatter and body.
    wiki_apply_atomic — compare-hash and replace file atomically.
"""

from __future__ import annotations

import hashlib
from contextlib import suppress
from pathlib import Path

from sevn.second_brain.errors import SecondBrainMergeNeededError, SecondBrainPathError
from sevn.second_brain.frontmatter import split_frontmatter
from sevn.security.llmignore import is_llmignored


def file_sha256_hex(path: Path) -> str:
    """SHA-256 hex digest of file bytes.

    Args:
        path (Path): Existing file to hash.

    Returns:
        str: Lowercase hex digest.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> p = Path(tempfile.mkdtemp()) / "f.bin"
        >>> _ = p.write_bytes(b"a")
        >>> len(file_sha256_hex(p)) == 64
        True
    """

    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def content_sha256_hex(text: str) -> str:
    """SHA-256 hex of UTF-8 encoded text.

    Args:
        text (str): Unicode string to digest.

    Returns:
        str: Lowercase hex digest of UTF-8 bytes.

    Examples:
        >>> len(content_sha256_hex("hello")) == 64
        True
    """

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def wiki_read(path: Path) -> tuple[str, dict[str, object], str]:
    """Read wiki file; return ``(full_text, frontmatter_dict, body)``.

    Args:
        path (Path): Markdown file on disk.

    Returns:
        tuple[str, dict[str, object], str]: Raw text, parsed frontmatter mapping, body only.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> p = Path(tempfile.mkdtemp()) / "p.md"
        >>> _ = p.write_text("# b\\n", encoding="utf-8")
        >>> full, fm, body = wiki_read(p)
        >>> body.strip().startswith("#")
        True
    """

    full = path.read_text(encoding="utf-8")
    fm, body, _raw = split_frontmatter(full)
    return full, fm, body


def wiki_apply_atomic(
    *,
    path: Path,
    patch: str,
    base_hash: str,
    workspace_root: Path,
) -> None:
    """Write ``patch`` if ``base_hash`` matches current SHA-256.

    Args:
        path (Path): Target wiki file path.
        patch (str): Full replacement file contents (UTF-8).
        base_hash (str): Expected SHA-256 hex of current file bytes (empty file digests ``""``).
        workspace_root (Path): Workspace root for containment and ``.llmignore`` checks.

    Raises:
        SecondBrainMergeNeededError: On mismatch (operator-visible merge-needed).
        SecondBrainPathError: If ``path`` is not under workspace or is llmignored.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> ws = Path(tempfile.mkdtemp())
        >>> p = ws / "w.md"
        >>> _ = p.write_text("a", encoding="utf-8")
        >>> bh = file_sha256_hex(p)
        >>> wiki_apply_atomic(path=p, patch="b", base_hash=bh, workspace_root=ws)
        >>> p.read_text(encoding="utf-8")
        'b'
    """

    wr = workspace_root.resolve()
    rp = path.resolve()
    try:
        rp.relative_to(wr)
    except ValueError as exc:
        msg = "wiki_apply refuses paths outside workspace content root"
        raise SecondBrainPathError(msg) from exc
    if is_llmignored(rp, wr):
        msg = "wiki_apply refuses quarantined paths under .llmignore/"
        raise SecondBrainPathError(msg)

    if not path.exists():
        digest = hashlib.sha256(b"").hexdigest()
    else:
        current_bytes = path.read_bytes()
        digest = hashlib.sha256(current_bytes).hexdigest()

    if digest != base_hash.lower().strip():
        raise SecondBrainMergeNeededError(
            f"base_hash mismatch for {path.name}: merge-needed (expected {digest}, got {base_hash})",
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(patch, encoding="utf-8")
        tmp.replace(path)
    except OSError:
        with suppress(FileNotFoundError):
            tmp.unlink()
        raise


__all__ = [
    "content_sha256_hex",
    "file_sha256_hex",
    "wiki_apply_atomic",
    "wiki_read",
]
