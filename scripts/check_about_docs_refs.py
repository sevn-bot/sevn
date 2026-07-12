"""Reference guard for about-docs published under ``about-sevn.bot/{prd,specs}/``.

Thin CLI/pre-commit wrapper around :mod:`sevn.docs.about.refs`.

Module: scripts.check_about_docs_refs
Depends: argparse, sys, pathlib, sevn.docs.about.refs

Exports:
    main — scan files passed on the CLI and exit non-zero on violations.

Examples:
    >>> from sevn.docs.about.refs import load_allowlist
    >>> load_allowlist.__name__
    'load_allowlist'
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sevn.docs.about.refs import find_violations, is_allowed, load_allowlist

__all__ = ["find_violations", "is_allowed", "load_allowlist", "main"]


def main(argv: list[str] | None = None) -> int:
    """Scan files passed by pre-commit; exit 1 when any reference violation is found.

    Args:
        argv (list[str] | None): CLI args; defaults to ``sys.argv[1:]``.

    Returns:
        int: ``0`` when all files are clean, ``1`` when violations exist.

    Examples:
        >>> main([])
        0
    """
    parser = argparse.ArgumentParser(
        description="Reject disallowed about-docs file-path references."
    )
    parser.add_argument(
        "--allowlist",
        type=Path,
        default=None,
        help="Path to allowed-refs.txt (default: about-sevn.bot/_docsys/allowed-refs.txt).",
    )
    parser.add_argument(
        "--repo",
        type=Path,
        default=None,
        help="Repository root for must-resolve checks (default: parent of scripts/).",
    )
    parser.add_argument("files", nargs="*", help="Markdown files to scan.")
    args = parser.parse_args(argv)

    repo_dir = (args.repo or Path(__file__).resolve().parents[1]).resolve()
    allowlist_file = args.allowlist or (
        repo_dir / "about-sevn.bot" / "_docsys" / "allowed-refs.txt"
    )

    failed = False
    for name in args.files:
        doc_path = Path(name)
        for lineno, ref in find_violations(doc_path, allowlist_file, repo_dir):
            failed = True
            print(f"{name}:{lineno}: disallowed or missing file-path reference: {ref}")
    if failed:
        print(
            "\nFile-path references in about-docs must match allowed-refs.txt and resolve "
            "under the repo root. Doc-id links and https:// URLs are always allowed.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
