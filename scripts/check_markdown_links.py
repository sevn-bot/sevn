#!/usr/bin/env python3
"""Advisory markdown link checker for tracked docs outside about-sevn.bot.

Scans git-tracked ``*.md`` files (excluding ``about-sevn.bot/`` and
``.ignorelocal/``) and reports unresolved relative links via
``sevn.docs.readme.links.validate_markdown_links``. Advisory only — wired into
``make md-links-check`` / ``ci-quality``, not blocking ``make ci``.

Module: scripts.check_markdown_links
Depends: argparse, subprocess, sys, pathlib, sevn.docs.readme.links

Exports:
    collect_markdown_paths — discover markdown files to scan.
    check_file — return link errors for one markdown file.
    main — scan paths and exit non-zero when any link is broken.

Examples:
    >>> main([])
    0
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from sevn.docs.readme.links import validate_markdown_links  # noqa: E402

_SKIP_PREFIXES = (
    "about-sevn.bot/",
    ".ignorelocal/",
    "docs/readmes/_archive/",
    "docs/readmes/_mock",
    "docs/brand/",
    "src/sevn/data/bundled_skills/",
    "src/sevn/data/second_brain/",
    "tests/",
)

_FENCED_CODE = re.compile(r"```[^\n]*\n.*?```", re.DOTALL)

# Gitignored or operator-local targets that may be absent on CI clones.
_IGNORE_LINK_FRAGMENTS = (
    "CLAUDE.md",
    ".cursor/",
    "graphify-out/",
)


def _markdown_without_fenced_code(text: str) -> str:
    """Return ``text`` with fenced code blocks removed for link validation.

    Args:
        text (str): Markdown source.

    Returns:
        str: Markdown without fenced code blocks.

    Examples:
        >>> _markdown_without_fenced_code("a\\n```md\\n[x](missing.md)\\n```\\nb")
        'a\\n\\nb'
    """
    return _FENCED_CODE.sub("", text)


def _ignorable_error(error: str) -> bool:
    """Return True when a link error targets a known local-only path.

    Args:
        error (str): Error string from ``validate_markdown_links``.

    Returns:
        bool: True when the error should not fail the advisory gate.

    Examples:
        >>> _ignorable_error("broken link: '../../../../CLAUDE.md'")
        True
    """
    return any(fragment in error for fragment in _IGNORE_LINK_FRAGMENTS)


def collect_markdown_paths(repo_root: Path) -> list[Path]:
    """Return sorted markdown paths to scan under ``repo_root``.

    Args:
        repo_root (Path): Repository root.

    Returns:
        list[Path]: Absolute paths for tracked ``*.md`` outside skip prefixes.

    Examples:
        >>> isinstance(collect_markdown_paths(REPO), list)
        True
    """
    repo_root = repo_root.resolve()
    result = subprocess.run(
        ["git", "ls-files", "--", "*.md"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    paths: list[Path] = []
    for line in result.stdout.splitlines():
        rel = line.strip().replace("\\", "/")
        if not rel or rel.endswith("/"):
            continue
        if any(rel.startswith(prefix) for prefix in _SKIP_PREFIXES):
            continue
        paths.append(repo_root / rel)
    return sorted(paths)


def check_file(path: Path, *, repo_root: Path) -> list[str]:
    """Return human-readable link errors for ``path``.

    Args:
        path (Path): Markdown file to validate.
        repo_root (Path): Repository root.

    Returns:
        list[str]: Errors prefixed with the file path; empty when clean.

    Examples:
        >>> import tempfile
        >>> td = Path(tempfile.mkdtemp())
        >>> doc = td / "docs" / "ok.md"
        >>> doc.parent.mkdir(parents=True)
        >>> _ = doc.write_text("[x](x.md)\\n", encoding="utf-8")
        >>> check_file(doc, repo_root=td)
        []
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [f"{path}: unreadable ({exc})"]
    rel = path.resolve().relative_to(repo_root.resolve()).as_posix()
    errors = validate_markdown_links(
        _markdown_without_fenced_code(text),
        path.resolve(),
        repo_root.resolve(),
    )
    return [f"{rel}: {err}" for err in errors if not _ignorable_error(err)]


def main(argv: list[str] | None = None, *, repo_root: Path | None = None) -> int:
    """Scan markdown files and exit 1 when any relative link is broken.

    Args:
        argv (list[str] | None): Optional repo-relative markdown paths; when
            omitted, scans all tracked ``*.md`` outside skip prefixes.
        repo_root (Path | None): Repository root; defaults to the parent of
            ``scripts/``.

    Returns:
        int: ``0`` when all links resolve, ``1`` when any error is found.

    Examples:
        >>> main([])
        0
    """
    root = (repo_root or REPO).resolve()
    parser = argparse.ArgumentParser(description="Advisory markdown link checker.")
    parser.add_argument(
        "files",
        nargs="*",
        help="Markdown paths relative to the repo root (default: all tracked).",
    )
    args = parser.parse_args(argv)

    if args.files:
        paths = [root / name.replace("\\", "/") for name in args.files]
    else:
        paths = collect_markdown_paths(root)

    failures: list[str] = []
    for path in paths:
        failures.extend(check_file(path, repo_root=root))

    if failures:
        print("md-links-check: broken links found:", file=sys.stderr)
        for line in failures:
            print(line, file=sys.stderr)
        return 1

    print(f"md-links-check: ok ({len(paths)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
