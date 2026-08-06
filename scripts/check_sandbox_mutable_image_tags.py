#!/usr/bin/env python3
"""Reject mutable sandbox image tag literals under ``src/`` (C4.3 / W7).

Scans product Python for ``ghcr.io/sevn-bot/sevn/sandbox:<tag>`` where ``<tag>``
is not a digest pin. Release defaults must be ``…@sha256:…`` via
``DEFAULT_SANDBOX_IMAGE``; ``:dev`` and ``:latest`` are hard failures.

Optional ``--require-stamped`` fails when the digest stamp is still
``sha256:UNSTAMPED`` (release builds only).

Module: scripts.check_sandbox_mutable_image_tags
Depends: argparse, re, pathlib, sys

Exports:
    find_mutable_tag_hits — list ``path:line:match`` for mutable sandbox tags.
    main — CLI entry for Make / CI.

Examples:
    >>> from pathlib import Path
    >>> isinstance(REPO_ROOT, Path)
    True
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"

_MUTABLE_TAG_RE = re.compile(
    r"""ghcr\.io/sevn-bot/sevn/sandbox:(?!@)(?P<tag>dev|latest|[A-Za-z0-9._-]+)""",
)
_UNSTAMPED = "sha256:UNSTAMPED"
_STAMP_ASSIGN_RE = re.compile(
    r'^_SANDBOX_IMAGE_DIGEST_STAMP:\s*str\s*=\s*"(?P<digest>sha256:[^"]+)"\s*$',
    re.MULTILINE,
)
_RUNTIME_MODULE = REPO_ROOT / "src" / "sevn" / "security" / "sandbox_runtime.py"


def find_mutable_tag_hits(*, src_root: Path = SRC_ROOT) -> list[str]:
    """Return mutable ``sandbox:<tag>`` hits under ``src_root``.

    Args:
        src_root (Path): Tree to scan (defaults to repo ``src/``).

    Returns:
        list[str]: ``relative:lineno:match`` strings; empty when clean.

    Examples:
        >>> find_mutable_tag_hits(src_root=Path("/nonexistent"))
        []
    """
    if not src_root.is_dir():
        return []
    hits: list[str] = []
    for path in sorted(src_root.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for match in _MUTABLE_TAG_RE.finditer(text):
            try:
                rel = path.relative_to(REPO_ROOT)
            except ValueError:
                rel = path
            line_no = text.count("\n", 0, match.start()) + 1
            hits.append(f"{rel}:{line_no}:{match.group(0)}")
    return hits


def _stamp_is_missing() -> bool:
    """Return True when ``_SANDBOX_IMAGE_DIGEST_STAMP`` is still the release sentinel.

    Comments and the ``_UNSTAMPED_SANDBOX_DIGEST`` constant legitimately retain the
    ``sha256:UNSTAMPED`` substring after a successful stamp — only the assignment
    value decides whether the release digest was applied.

    Returns:
        bool: ``True`` when the stamp assignment is missing or still ``UNSTAMPED``.

    Examples:
        >>> isinstance(_stamp_is_missing(), bool)
        True
    """
    if not _RUNTIME_MODULE.is_file():
        return True
    text = _RUNTIME_MODULE.read_text(encoding="utf-8")
    match = _STAMP_ASSIGN_RE.search(text)
    if match is None:
        return True
    return match.group("digest") == _UNSTAMPED


def main(argv: list[str] | None = None) -> int:
    """Scan ``src/`` for mutable sandbox tags; optionally require a real stamp.

    Args:
        argv (list[str] | None): CLI args; defaults to ``sys.argv[1:]``.

    Returns:
        int: ``0`` when clean; ``1`` on mutable tags or missing stamp.

    Examples:
        >>> main(["--help"])  # doctest: +SKIP
        0
    """
    parser = argparse.ArgumentParser(
        description="Reject mutable sandbox image tag literals under src/ (C4.3).",
    )
    parser.add_argument(
        "--require-stamped",
        action="store_true",
        help="Fail when sha256:UNSTAMPED remains in sandbox_runtime.py (release).",
    )
    args = parser.parse_args(argv)

    hits = find_mutable_tag_hits()
    if hits:
        print(
            "check_sandbox_mutable_image_tags: FAIL — mutable sandbox tags under src/:",
            file=sys.stderr,
        )
        for hit in hits:
            print(f"  {hit}", file=sys.stderr)
        return 1

    if args.require_stamped and _stamp_is_missing():
        print(
            "check_sandbox_mutable_image_tags: FAIL — DEFAULT_SANDBOX_IMAGE still "
            f"uses {_UNSTAMPED!r}; run scripts/stamp_default_sandbox_image.py "
            "before a release build",
            file=sys.stderr,
        )
        return 1

    print("check_sandbox_mutable_image_tags: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
