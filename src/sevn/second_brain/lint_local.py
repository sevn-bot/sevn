"""Local wiki lint rules (`specs/27-second-brain.md` §2.2).

Exports:
    LintIssue — one structured lint finding.
    lint_wiki_tree — scan wiki tree and collect issues.
    issues_to_json — serialise issues for tool envelopes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sevn.second_brain.frontmatter import missing_okf_type, okf_type_required, split_frontmatter
from sevn.second_brain.links import iter_internal_link_targets, resolve_wiki_target


@dataclass(frozen=True)
class LintIssue:
    """Single lint finding."""

    severity: str
    path: str
    message: str


def _parse_iso_date(s: str) -> datetime | None:
    """Parse ISO-8601 date/datetime strings for freshness linting.

    Args:
        s (str): ``last_verified`` (or similar) string from frontmatter YAML.

    Returns:
        datetime | None: Parsed aware or naive datetime, or ``None`` when parsing fails.

    Examples:
        >>> from datetime import datetime
        >>> isinstance(_parse_iso_date("2024-01-15"), datetime)
        True
        >>> _parse_iso_date("not-a-date") is None
        True
    """
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


_INDEX_MD_WARN_BYTES = 512 * 1024


def lint_wiki_tree(wiki_root: Path, *, stale_days: int = 90) -> list[LintIssue]:
    """Scan ``wiki_root`` for orphans, missing sources, stale freshness.

    Args:
        wiki_root (Path): Root ``wiki/`` directory for a scope.
        stale_days (int): Age threshold (days) for ``sevn_freshness`` staleness hints.

    Returns:
        list[LintIssue]: Collected findings (empty when ``wiki_root`` is missing).

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> lint_wiki_tree(Path(tempfile.mkdtemp()) / "missing")
        []
    """

    issues: list[LintIssue] = []
    if not wiki_root.is_dir():
        return issues

    index = wiki_root / "index.md"
    if index.is_file():
        idx_sz = index.stat().st_size
        if idx_sz > _INDEX_MD_WARN_BYTES:
            issues.append(
                LintIssue(
                    severity="low",
                    path="index.md",
                    message=(f"index.md large ({idx_sz} bytes); consider splitting the catalog"),
                ),
            )

    files = sorted(wiki_root.rglob("*.md"))
    by_rel = {p.relative_to(wiki_root).as_posix(): p for p in files}

    now = datetime.now(tz=UTC)
    for rel, fp in by_rel.items():
        text = fp.read_text(encoding="utf-8", errors="replace")
        fm, body, _ = split_frontmatter(text)
        for kind, target in iter_internal_link_targets(body):
            if resolve_wiki_target(kind, target, source_rel=rel, by_rel=by_rel) is not None:
                continue
            if kind == "wikilink":
                msg = f"orphan wikilink target missing: [[{target}]]"
            else:
                msg = f"orphan OKF link target missing: [{target}]"
            issues.append(
                LintIssue(
                    severity="medium",
                    path=rel,
                    message=msg,
                ),
            )

        if okf_type_required(rel) and missing_okf_type(fm):
            issues.append(
                LintIssue(
                    severity="low",
                    path=rel,
                    message="missing OKF type frontmatter",
                ),
            )

        if rel.endswith(("index.md", "log.md")):
            continue
        if len(body) > 400 and not re.search(r"\[Source:", body, flags=re.IGNORECASE):
            issues.append(
                LintIssue(
                    severity="low",
                    path=rel,
                    message="missing [Source: …] attribution on long body",
                ),
            )

        fresh = fm.get("sevn_freshness") or fm.get("freshness")
        if isinstance(fresh, dict):
            lv = fresh.get("last_verified")
            if isinstance(lv, str):
                dt = _parse_iso_date(lv)
                if dt:
                    dt_utc = dt if dt.tzinfo else dt.replace(tzinfo=UTC)
                    if (now - dt_utc).days > stale_days:
                        issues.append(
                            LintIssue(
                                severity="medium",
                                path=rel,
                                message=f"stale sevn_freshness.last_verified ({lv})",
                            ),
                        )

    return issues


def issues_to_json(issues: list[LintIssue]) -> list[dict[str, str]]:
    """Convert lint issues to JSON-serialisable dict rows.

    Args:
        issues (list[LintIssue]): Findings from :func:`lint_wiki_tree`.

    Returns:
        list[dict[str, str]]: Rows with ``severity``, ``path``, and ``message`` keys.

    Examples:
        >>> issues_to_json([])
        []
    """
    return [{"severity": i.severity, "path": i.path, "message": i.message} for i in issues]


__all__ = ["LintIssue", "issues_to_json", "lint_wiki_tree"]
