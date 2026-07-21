#!/usr/bin/env python3
"""Fail when an agent definition is malformed, mislinked, or silently inert.

Module: scripts.check_agents
Depends: pathlib, re, sys, yaml

Exports:
    main — exit 1 when any agent file under ``.claude/agents``, ``.cursor/agents``
        or ``spec-kit-wave/agents`` is structurally invalid or has a dead link.

Why this exists: agent definitions are hand-copied between three trees, and every
failure mode is silent. On 2026-07-21 an audit found 16 of 19 ``.claude`` agents had
no YAML frontmatter — Claude Code skips such files without warning, so they looked
installed while registering nothing. Four ``.cursor`` agents had invalid YAML (an
unquoted ``: `` inside a single-line ``description``), two had the description value
orphaned above its key, and 36 relative links were correct in their home tree but
broken in the copies. None of it surfaced until an agent failed to fire.

Errors (exit 1) are objective defects. Body drift between the two IDE trees is
reported but does NOT fail, because some divergence is deliberate; pass ``--strict``
to promote drift to an error. Trees are gitignored, so a missing tree is skipped
rather than failed.

Examples:
    >>> _split_frontmatter("---\\nname: x\\n---\\nbody")[0]
    'name: x'
    >>> _split_frontmatter("no frontmatter here")[0] is None
    True
    >>> sorted(_duplicate_keys("a: 1\\nb: 2\\na: 3"))
    ['a']
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]

#: Frontmatter keys each target understands. Unknown keys are usually a copy from
#: the other IDE's dialect and are silently ignored by the host, so they are errors.
ALLOWED: dict[str, set[str]] = {
    ".claude/agents": {"name", "description", "model", "tools", "color"},
    ".cursor/agents": {"name", "description", "model", "is_background", "color", "memory"},
}
#: ``spec-kit-wave/agents`` is kit prose: no frontmatter expected, links still checked.
KIT = "spec-kit-wave/agents"
VALID_MODELS = {"inherit", "sonnet", "opus", "haiku", "auto"}
LINK = re.compile(r"\[[^\]]*\]\((?!https?:|#)([^)]+)\)")
TOP_KEY = re.compile(r"^([A-Za-z_][\w-]*):", re.MULTILINE)
PLACEHOLDER = re.compile(r"…|NN-")


def _split_frontmatter(text: str) -> tuple[str | None, str]:
    """Split a YAML frontmatter block from the body.

    Args:
        text (str): Full file contents.

    Returns:
        tuple[str | None, str]: Raw frontmatter (without fences) and the body.
            Frontmatter is ``None`` when the file does not open with ``---``.

    Examples:
        >>> _split_frontmatter("---\\nname: x\\n---\\nbody")
        ('name: x', 'body')
        >>> _split_frontmatter("plain prose")
        (None, 'plain prose')
    """
    if not text.startswith("---\n"):
        return None, text
    end = text.find("\n---\n", 4)
    if end < 0:
        return None, text
    return text[4:end], text[end + 5 :]


def _duplicate_keys(raw: str) -> set[str]:
    """Return top-level frontmatter keys that appear more than once.

    Args:
        raw (str): Raw frontmatter block.

    Returns:
        set[str]: Keys seen at least twice. PyYAML silently keeps the last value.

    Examples:
        >>> sorted(_duplicate_keys("name: a\\nmodel: b\\nname: c"))
        ['name']
        >>> _duplicate_keys("name: a\\nmodel: b")
        set()
    """
    keys = TOP_KEY.findall(raw)
    return {k for k in keys if keys.count(k) > 1}


def _check_frontmatter(stem: str, text: str, allowed: set[str]) -> list[str]:
    """Validate one agent's frontmatter against its target's dialect.

    Args:
        stem (str): Filename without suffix; ``name`` must equal this.
        text (str): Full file contents.
        allowed (set[str]): Keys the host understands.

    Returns:
        list[str]: Human-readable problems; empty when the file is well formed.

    Examples:
        >>> _check_frontmatter("a", "# prose only", {"name"})
        ['no YAML frontmatter — the host will skip this file silently']
        >>> body = "x" * 200
        >>> ok = "---\\nname: a\\ndescription: " + "d" * 60 + "\\n---\\n" + body
        >>> _check_frontmatter("a", ok, {"name", "description"})
        []
        >>> _check_frontmatter("b", ok, {"name", "description"})
        ["name 'a' does not match filename 'b'"]
    """
    raw, body = _split_frontmatter(text)
    if raw is None:
        return ["no YAML frontmatter — the host will skip this file silently"]
    problems: list[str] = []
    if dupes := _duplicate_keys(raw):
        problems.append(f"duplicate frontmatter key(s): {', '.join(sorted(dupes))}")
    first = TOP_KEY.search(raw)
    if first and raw[: first.start()].strip():
        problems.append("orphaned text before the first key (a value split from its key)")
    try:
        data = yaml.safe_load(raw) or {}
    except yaml.YAMLError as exc:
        first_line = str(exc).splitlines()[0]
        return [*problems, f"invalid YAML: {first_line} (quote values containing ': ')"]
    if data.get("name") != stem:
        problems.append(f"name {data.get('name')!r} does not match filename {stem!r}")
    if not (data.get("description") or "").strip():
        problems.append("missing description — the host dispatches on this field")
    if (model := data.get("model")) and str(model) not in VALID_MODELS:
        problems.append(f"unknown model {model!r} (expected one of {sorted(VALID_MODELS)})")
    if unknown := set(data) - allowed:
        problems.append(f"key(s) not understood by this target: {', '.join(sorted(unknown))}")
    if len(body.strip()) < 100:
        problems.append("body is suspiciously short — the prompt may have been truncated")
    return problems


def _check_links(path: Path) -> list[str]:
    """Report relative markdown links that do not resolve from the file's location.

    Args:
        path (Path): Agent markdown file.

    Returns:
        list[str]: One entry per dead link. Placeholders (``NN-``, ``…``) are ignored.

    Examples:
        >>> LINK.findall("see [a](../x.md), [b](https://z), [c](#anchor)")
        ['../x.md']
        >>> _check_links(REPO / "scripts" / "check_agents.py") == [
        ...     "dead link: ../x.md"
        ... ]  # this docstring's own example link
        True
    """
    problems: list[str] = []
    for match in LINK.finditer(path.read_text()):
        target = match.group(1).split("#")[0]
        if not target or PLACEHOLDER.search(target):
            continue
        if not (path.parent / target).resolve().exists():
            problems.append(f"dead link: {target}")
    return problems


def _check_drift() -> list[str]:
    """Report agents whose body differs between the two IDE trees.

    Returns:
        list[str]: One entry per diverging agent. Informational unless ``--strict``.

    Examples:
        >>> isinstance(_check_drift(), list)
        True
    """
    claude, cursor = REPO / ".claude/agents", REPO / ".cursor/agents"
    if not (claude.is_dir() and cursor.is_dir()):
        return []
    problems: list[str] = []
    for path in sorted(claude.glob("*.md")):
        twin = cursor / path.name
        if not twin.exists():
            continue
        # Compare stripped bodies: leading/trailing blank lines differ purely by how
        # each file was written and are not drift worth reporting.
        if (
            _split_frontmatter(path.read_text())[1].strip()
            != _split_frontmatter(twin.read_text())[1].strip()
        ):
            problems.append(
                f"{path.name}: body differs between .claude ({path.stat().st_size}b) "
                f"and .cursor ({twin.stat().st_size}b)"
            )
    return problems


def main() -> int:
    """Check every agent tree and report findings.

    Returns:
        int: 1 when a structural defect or dead link was found (or drift under
            ``--strict``), else 0. Absent trees are skipped, not failed.

    Examples:
        >>> callable(main)  # invoking it here would print a full report
        True
    """
    strict = "--strict" in sys.argv
    errors = 0
    for tree, allowed in [*ALLOWED.items(), (KIT, set())]:
        directory = REPO / tree
        if not directory.is_dir():
            print(f"check-agents: skip {tree} (absent — gitignored tree)")
            continue
        files = sorted(directory.glob("*.md"))
        for path in files:
            problems = _check_links(path)
            if tree != KIT:
                problems = _check_frontmatter(path.stem, path.read_text(), allowed) + problems
            for problem in problems:
                print(f"  {tree}/{path.name}: {problem}")
                errors += 1
        print(f"check-agents: {tree} — {len(files)} file(s)")

    if drift := _check_drift():
        label = "ERROR" if strict else "note"
        for entry in drift:
            print(f"  [{label}] drift {entry}")
        if strict:
            errors += len(drift)

    print(f"check-agents: {'FAIL' if errors else 'OK'} ({errors} problem(s))")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
