"""Scan ``specs/*.md`` and emit incomplete Section 10 tasks as JSON.

Module: scripts.list_incomplete_spec_tasks
Depends: argparse, json, pathlib, re, sys

Each spec uses Section 10 (``## 10. Build Checklist``) as the merge-gate
list. This script collects every ``- [ ]`` bullet inside Section 10,
captures subsection headers, parent tasks, and ``specs/NN-name.md`` refs.

Exports:
    IncompleteTask — One incomplete checklist row.
    extract_spec_refs — Parse ``specs/NN-name.md`` references from text.
    parse_spec — Extract incomplete tasks from one spec file.
    collect — Scan all specs in a directory.
    main — CLI entry; writes timestamped JSON.

Examples:
    >>> extract_spec_refs("see specs/00-foundation.md")
    ['00-foundation']
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_DEFAULT_SPECS_DIR = _REPO / ".ignorelocal" / "design" / "specs"
SPEC_REF_RE = re.compile(r"specs/(\d+[A-Za-z0-9_-]*)\.md")
CHECKBOX_RE = re.compile(r"^(?P<indent>\s*)-\s+\[(?P<mark>[ xX])\]\s+(?P<body>.*)$")
SECTION_10_RE = re.compile(r"^##\s+10\b")
NEXT_SECTION_RE = re.compile(r"^##\s+\d+\b")
SUBSECTION_RE = re.compile(r"^###\s+(?P<title>10\.\d+.*)$")
TITLE_RE = re.compile(r"^#\s+(?P<title>.+)$")
DEPENDS_RE = re.compile(r"^\*\*Depends on \(specs\):\*\*\s*(?P<body>.+)$")


@dataclass
class IncompleteTask:
    """One incomplete Section 10 checklist row.

    Attributes:
        spec_file: Basename of the spec markdown file.
        spec_id: Stem of the spec file.
        spec_title: Title from the leading ``#`` heading.
        spec_depends_on: Spec IDs from the Depends-on header.
        subsection: Immediate ``### 10.x`` header, if any.
        indent: Indent level of the checkbox (spaces).
        parent_task: Nearest top-level parent bullet text.
        text: Checkbox body text.
        raw_line: Original markdown line.
        line_number: 1-based line number in the spec file.
        depends_on_inline: Spec refs parsed from the bullet body.
    """

    spec_file: str
    spec_id: str
    spec_title: str
    spec_depends_on: list[str]
    subsection: str | None
    indent: int
    parent_task: str | None
    text: str
    raw_line: str
    line_number: int
    depends_on_inline: list[str] = field(default_factory=list)


def extract_spec_refs(text: str) -> list[str]:
    """Return unique ``specs/NN-name`` stems referenced in ``text``.

    Args:
        text (str): Markdown fragment to scan.

    Returns:
        list[str]: Spec stems in first-seen order.

    Examples:
        >>> extract_spec_refs("see specs/00-foundation.md and specs/01-x.md")
        ['00-foundation', '01-x']
    """
    seen: list[str] = []
    for match in SPEC_REF_RE.finditer(text):
        ref = match.group(1)
        if ref not in seen:
            seen.append(ref)
    return seen


def parse_spec(path: Path) -> list[IncompleteTask]:
    """Parse one spec file and return incomplete Section 10 tasks.

    Args:
        path (Path): Spec markdown path.

    Returns:
        list[IncompleteTask]: Unchecked bullets inside Section 10.

    Examples:
        >>> import tempfile
        >>> p = Path(tempfile.mkdtemp()) / "99-test.md"
        >>> _ = p.write_text(
        ...     "# T\\n\\n## 10. Build Checklist\\n- [ ] task\\n",
        ...     encoding="utf-8",
        ... )
        >>> parse_spec(p)[0].text
        'task'
    """
    lines = path.read_text(encoding="utf-8").splitlines()

    spec_title = ""
    spec_depends: list[str] = []
    for line in lines[:40]:
        if not spec_title:
            t = TITLE_RE.match(line)
            if t:
                spec_title = t.group("title").strip()
        d = DEPENDS_RE.match(line)
        if d:
            spec_depends = extract_spec_refs(d.group("body"))
            break

    # Locate Section 10 boundaries.
    start: int | None = None
    end: int = len(lines)
    for idx, line in enumerate(lines):
        if SECTION_10_RE.match(line):
            start = idx
            break
    if start is None:
        return []
    for idx in range(start + 1, len(lines)):
        if NEXT_SECTION_RE.match(lines[idx]):
            end = idx
            break

    tasks: list[IncompleteTask] = []
    current_subsection: str | None = None
    last_top_level_task: str | None = None

    for offset, raw in enumerate(lines[start:end]):
        line_no = start + offset + 1
        sub = SUBSECTION_RE.match(raw)
        if sub:
            current_subsection = sub.group("title").strip()
            last_top_level_task = None
            continue

        m = CHECKBOX_RE.match(raw)
        if not m:
            continue

        indent_spaces = len(m.group("indent").expandtabs(4))
        body = m.group("body").strip()
        mark = m.group("mark").lower()

        if indent_spaces == 0:
            # Track parent task for any nested children that follow.
            last_top_level_task = body
            # Reset on every new top-level bullet, regardless of completion.

        if mark == "x":
            continue

        tasks.append(
            IncompleteTask(
                spec_file=path.name,
                spec_id=path.stem,
                spec_title=spec_title,
                spec_depends_on=spec_depends,
                subsection=current_subsection,
                indent=indent_spaces,
                parent_task=last_top_level_task if indent_spaces > 0 else None,
                text=body,
                raw_line=raw,
                line_number=line_no,
                depends_on_inline=extract_spec_refs(body),
            )
        )

    return tasks


def collect(specs_dir: Path) -> list[IncompleteTask]:
    """Collect incomplete tasks from every spec in ``specs_dir``.

    Args:
        specs_dir (Path): Directory containing ``*.md`` spec files.

    Returns:
        list[IncompleteTask]: Aggregated incomplete rows.

    Examples:
        >>> collect(Path(__file__).resolve().parent.parent / "specs")[:1]
        []
    """
    results: list[IncompleteTask] = []
    for path in sorted(specs_dir.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        results.extend(parse_spec(path))
    return results


def main(argv: list[str] | None = None) -> int:
    """Write incomplete Section 10 tasks to a timestamped JSON file.

    Args:
        argv (list[str] | None): Optional CLI args (defaults to ``sys.argv[1:]``).

    Returns:
        int: ``0`` on success, ``2`` when ``--specs-dir`` is missing.

    Examples:
        >>> import tempfile
        >>> d = Path(tempfile.mkdtemp())
        >>> specs = Path(__file__).resolve().parent.parent / "specs"
        >>> main(["--specs-dir", str(specs), "--output-dir", str(d)]) in (0, 2)
        True
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--specs-dir",
        type=Path,
        default=_DEFAULT_SPECS_DIR,
        help="Directory containing spec markdown files (default: <repo>/.ignorelocal/design/specs).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path.cwd(),
        help="Directory to write the timestamped JSON file (default: cwd).",
    )
    args = parser.parse_args(argv)

    if not args.specs_dir.is_dir():
        print(f"specs directory not found: {args.specs_dir}", file=sys.stderr)
        return 2

    tasks = collect(args.specs_dir)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")  # noqa: DTZ005
    out_path = args.output_dir / f"incomplete_tasks_{stamp}.json"
    out_path.write_text(
        json.dumps([asdict(t) for t in tasks], indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {len(tasks)} incomplete tasks to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
