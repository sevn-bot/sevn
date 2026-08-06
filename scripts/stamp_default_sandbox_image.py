#!/usr/bin/env python3
"""Stamp ``DEFAULT_SANDBOX_IMAGE`` digest into ``sandbox_runtime.py`` (W7.4 / C4.1).

Release / publish pipelines run this after the sandbox image is built and its
registry digest is known. Replaces the ``sha256:UNSTAMPED`` literal assigned to
``_SANDBOX_IMAGE_DIGEST_STAMP``. An unstamped tree never falls back to a mutable
tag — spawn fails closed via ``SandboxConfigurationError``.

Usage::

    uv run python scripts/stamp_default_sandbox_image.py sha256:<64-hex>
    SEVN_SANDBOX_IMAGE_DIGEST=sha256:<64-hex> uv run python scripts/stamp_default_sandbox_image.py

Module: scripts.stamp_default_sandbox_image
Depends: argparse, os, pathlib, re, sys

Exports:
    stamp_file — rewrite the digest stamp literal in a source file.
    main — CLI entry.

Examples:
    >>> from pathlib import Path
    >>> isinstance(RUNTIME_MODULE, Path)
    True
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_MODULE = REPO_ROOT / "src" / "sevn" / "security" / "sandbox_runtime.py"

_STAMP_ASSIGN_RE = re.compile(
    r'^(_SANDBOX_IMAGE_DIGEST_STAMP:\s*str\s*=\s*)"sha256:[^"]+"(\s*)$',
    re.MULTILINE,
)
_DIGEST_RE = re.compile(r"^(?:sha256:)?(?P<hex>[a-fA-F0-9]{64})$")


def _normalize_digest(raw: str) -> str:
    """Return ``sha256:<64-hex>`` or raise ``ValueError``.

    Args:
        raw (str): Digest with or without ``sha256:`` prefix.

    Returns:
        str: Canonical ``sha256:…`` form.

    Raises:
        ValueError: When ``raw`` is not a 64-hex digest.

    Examples:
        >>> _normalize_digest("a" * 64).startswith("sha256:")
        True
    """
    text = raw.strip()
    match = _DIGEST_RE.fullmatch(text)
    if match is None:
        msg = f"expected sha256:<64-hex> digest, got {raw!r}"
        raise ValueError(msg)
    return f"sha256:{match.group('hex').lower()}"


def stamp_file(path: Path, digest: str) -> None:
    """Replace ``_SANDBOX_IMAGE_DIGEST_STAMP`` assignment with ``digest``.

    Args:
        path (Path): ``sandbox_runtime.py`` path.
        digest (str): Canonical ``sha256:…`` digest.

    Returns:
        None: Always ``None``.

    Raises:
        ValueError: When the stamp assignment is missing.
        OSError: When the file cannot be read or written.

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> p = Path(tempfile.mkdtemp()) / "sandbox_runtime.py"
        >>> _ = p.write_text(
        ...     '_SANDBOX_IMAGE_DIGEST_STAMP: str = "sha256:UNSTAMPED"\\n',
        ...     encoding="utf-8",
        ... )
        >>> stamp_file(p, "sha256:" + ("ab" * 32))
        >>> 'UNSTAMPED' in p.read_text(encoding="utf-8")
        False
    """
    text = path.read_text(encoding="utf-8")
    replacement = rf'\1"{digest}"\2'
    new_text, count = _STAMP_ASSIGN_RE.subn(replacement, text, count=1)
    if count != 1:
        msg = f"could not find _SANDBOX_IMAGE_DIGEST_STAMP assignment in {path}"
        raise ValueError(msg)
    path.write_text(new_text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """Stamp the default sandbox image digest into source.

    Args:
        argv (list[str] | None): CLI args; defaults to ``sys.argv[1:]``.

    Returns:
        int: ``0`` on success; ``1`` on usage/IO errors.

    Examples:
        >>> main(["--help"])  # doctest: +SKIP
        0
    """
    parser = argparse.ArgumentParser(
        description="Stamp DEFAULT_SANDBOX_IMAGE digest (replaces sha256:UNSTAMPED).",
    )
    parser.add_argument(
        "digest",
        nargs="?",
        default="",
        help="sha256:<64-hex> (or set SEVN_SANDBOX_IMAGE_DIGEST)",
    )
    parser.add_argument(
        "--file",
        type=Path,
        default=RUNTIME_MODULE,
        help="Path to sandbox_runtime.py (default: src/sevn/security/sandbox_runtime.py)",
    )
    args = parser.parse_args(argv)

    raw = (args.digest or os.environ.get("SEVN_SANDBOX_IMAGE_DIGEST", "")).strip()
    if not raw:
        print(
            "stamp_default_sandbox_image: pass a digest argument or set SEVN_SANDBOX_IMAGE_DIGEST",
            file=sys.stderr,
        )
        return 1
    try:
        digest = _normalize_digest(raw)
        stamp_file(args.file, digest)
    except (OSError, ValueError) as exc:
        print(f"stamp_default_sandbox_image: FAIL — {exc}", file=sys.stderr)
        return 1
    print(f"stamp_default_sandbox_image: stamped {digest} into {args.file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
