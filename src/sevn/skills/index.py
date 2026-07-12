"""Executor / Triager index lines for skills (`specs/12-skills-system.md` §2.3 narrative).

Module: sevn.skills.index
Depends: pathlib, typing, sevn.skills.models (type-checking helpers only).

Exports:
    SkillsIndex — mapping skill id → one-line picker string + hints.
    SkillsIndexBuilder — materialise from scanned records dict.
    resolve_skill_alias — map transitional bundled alias ids to canonical skill ids.
    augment_index_with_aliases — duplicate index rows for alias ids.

Examples:
    >>> isinstance(SkillsIndex(lines={}), SkillsIndex)
    True
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sevn.skills.models import SkillRecord


@dataclass(frozen=True)
class SkillsIndex:
    """Name → description (~80-char executor hint) plus optional ``see_also``."""

    lines: dict[str, str]
    """``skill_id`` → one-line picker string (**name — description**, truncated ~80 chars)."""

    see_also: dict[str, tuple[str, ...]] = field(default_factory=dict)
    """``skill_id`` → cross-link hints."""

    def description_line_for(self, name: str) -> str | None:
        """Return the Triager-aligned description row if present.

        Args:
            name (str): Skill id to look up.

        Returns:
            str | None: Description line, or ``None`` when ``name`` is unknown.

        Examples:
            >>> ix = SkillsIndex(lines={"demo": "demo - hi"})
            >>> ix.description_line_for("demo")
            'demo - hi'
            >>> ix.description_line_for("missing") is None
            True
        """
        return self.lines.get(name)


_LINE_MAX: int = 80


def _clip(text: str) -> str:
    """Strip and truncate ``text`` to ``_LINE_MAX`` characters with an ellipsis.

    Args:
        text (str): Raw description row (may include leading/trailing whitespace).

    Returns:
        str: Trimmed text, ending with a Unicode ellipsis when over the limit.

    Examples:
        >>> _clip("  short  ")
        'short'
        >>> len(_clip("a" * 200)) == 80
        True
    """
    t = text.strip()
    if len(t) <= _LINE_MAX:
        return t
    return f"{t[: _LINE_MAX - 1]}…"


class SkillsIndexBuilder:
    """Build index snapshot from scanned ``SkillRecord`` map."""

    @staticmethod
    def from_records(records: dict[str, SkillRecord]) -> SkillsIndex:
        """Construct ordered description lines (**alphabetical** by id).

        Args:
            records (dict[str, SkillRecord]): Canonical merged registry.

        Returns:
            SkillsIndex: Description map with ``see_also`` hints preserved.

        Examples:
            >>> from pathlib import Path
            >>> from sevn.skills.manifest import SkillManifest
            >>> from sevn.skills.models import SkillRecord
            >>> m = SkillManifest(name="demo", description="hello", version="1.0.0")
            >>> sr = SkillRecord(
            ...     canonical_id="demo",
            ...     skill_dir=Path("/tmp/x"),
            ...     manifest=m,
            ...     provenance="user",
            ...     markdown_raw="",
            ... )
            >>> ix = SkillsIndexBuilder.from_records({"demo": sr})
            >>> "hello" in ix.lines["demo"]
            True
        """
        lines: dict[str, str] = {}
        see: dict[str, tuple[str, ...]] = {}
        for sid in sorted(records.keys()):
            rec = records[sid]
            man = rec.manifest
            row = _clip(f"{sid} — {man.description}")
            lines[sid] = row
            if man.see_also:
                see[sid] = tuple(man.see_also)
        return augment_index_with_aliases(SkillsIndex(lines=lines, see_also=see))


def resolve_skill_alias(name: str) -> str:
    """Map a transitional alias id to its canonical bundled skill id.

    Args:
        name (str): Skill id from ``load_skill`` / ``run_skill_script`` / Triager index.

    Returns:
        str: Canonical id when ``name`` is a known alias; otherwise ``name`` unchanged.

    Examples:
        >>> resolve_skill_alias("mycode_scan")
        'mycode'
        >>> resolve_skill_alias("lcm")
        'lcm'
    """
    from sevn.config.defaults import BUNDLED_SKILL_INDEX_ALIASES

    return BUNDLED_SKILL_INDEX_ALIASES.get(name, name)


def augment_index_with_aliases(index: SkillsIndex) -> SkillsIndex:
    """Add transitional alias rows that mirror canonical skill index lines.

    Args:
        index (SkillsIndex): Index built from merged ``SkillRecord`` map.

    Returns:
        SkillsIndex: Copy with alias ids present when their canonical target exists.

    Examples:
        >>> ix = SkillsIndex(lines={"mycode": "mycode — scan"})
        >>> augmented = augment_index_with_aliases(ix)
        >>> augmented.lines["mycode_scan"]
        'mycode — scan'
    """
    from sevn.config.defaults import BUNDLED_SKILL_INDEX_ALIASES

    lines = dict(index.lines)
    see = dict(index.see_also)
    for alias, canonical in BUNDLED_SKILL_INDEX_ALIASES.items():
        if canonical in lines and alias not in lines:
            lines[alias] = lines[canonical]
            if canonical in see:
                see[alias] = see[canonical]
    return SkillsIndex(lines=lines, see_also=see)
