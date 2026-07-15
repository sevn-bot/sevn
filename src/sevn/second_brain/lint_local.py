"""Local wiki lint rules (`specs/27-second-brain.md` §2.2).

Exports:
    LintIssue — one structured lint finding.
    lint_vault_tree — layout-aware vault scan (legacy | PARA).
    lint_wiki_tree — legacy single-wiki-root shim.
    issues_to_json — serialise issues for tool envelopes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from sevn.second_brain.frontmatter import (
    missing_okf_type,
    okf_type_required,
    reserved_basenames_for_layout,
    split_frontmatter,
)
from sevn.second_brain.links import (
    collect_vault_md_by_rel,
    index_line_targets,
    iter_internal_link_targets,
    resolve_wiki_target,
)
from sevn.second_brain.paths import VaultLayout


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


def _collect_incoming_links(
    by_rel: dict[str, Path],
    *,
    index_rel: str | None,
) -> set[str]:
    """Build the set of vault-relative paths referenced by internal links.

    Args:
        by_rel (dict[str, Path]): Vault-relative markdown path map.
        index_rel (str | None): Relative path of the index/home note, if present.

    Returns:
        set[str]: Referenced vault-relative ``.md`` paths.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> with tempfile.TemporaryDirectory() as td:
        ...     root = Path(td)
        ...     page = root / "a.md"
        ...     _ = page.write_text("See [[b]].\\n", encoding="utf-8")
        ...     target = root / "b.md"
        ...     _ = target.write_text("# b\\n", encoding="utf-8")
        ...     by = {"a.md": page, "b.md": target}
        ...     "b.md" in _collect_incoming_links(by, index_rel=None)
        True
    """
    incoming: set[str] = set()
    for rel, fp in by_rel.items():
        text = fp.read_text(encoding="utf-8", errors="replace")
        _, body, _ = split_frontmatter(text)
        if rel == index_rel:
            for line in body.splitlines():
                incoming.update(index_line_targets(line))
        for kind, target in iter_internal_link_targets(body):
            resolved = resolve_wiki_target(kind, target, source_rel=rel, by_rel=by_rel)
            if resolved:
                incoming.add(resolved)
    return incoming


def _staleness_issues(
    rel: str,
    fm: dict[str, Any],
    *,
    stale_days: int,
    now: datetime,
    layout_kind: Literal["legacy", "para"],
) -> list[LintIssue]:
    """Return staleness findings for one page's frontmatter.

    Args:
        rel (str): Vault-relative path of the page.
        fm (dict[str, Any]): Parsed frontmatter mapping.
        stale_days (int): Age threshold in days.
        now (datetime): Current UTC timestamp.
        layout_kind (Literal["legacy", "para"]): Active layout for key selection.

    Returns:
        list[LintIssue]: Staleness findings (may be empty).

    Examples:
        >>> from datetime import UTC, datetime, timedelta
        >>> old = (datetime.now(tz=UTC) - timedelta(days=120)).date().isoformat()
        >>> issues = _staleness_issues(
        ...     "note.md",
        ...     {"updated": old},
        ...     stale_days=90,
        ...     now=datetime.now(tz=UTC),
        ...     layout_kind="para",
        ... )
        >>> issues[0].message.startswith("stale updated")
        True
    """
    issues: list[LintIssue] = []
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
    if layout_kind == "para":
        updated = fm.get("updated")
        if isinstance(updated, str):
            dt = _parse_iso_date(updated)
            if dt:
                dt_utc = dt if dt.tzinfo else dt.replace(tzinfo=UTC)
                if (now - dt_utc).days > stale_days:
                    issues.append(
                        LintIssue(
                            severity="medium",
                            path=rel,
                            message=f"stale updated ({updated})",
                        ),
                    )
    return issues


def _lint_collected_tree(
    *,
    path_base: Path,
    by_rel: dict[str, Path],
    layout_kind: Literal["legacy", "para"],
    reserved_basenames: frozenset[str],
    index_note: Path,
    log_note: Path,
    exempt_dir_prefixes: tuple[str, ...],
    stale_days: int,
) -> list[LintIssue]:
    """Run shared lint rules over a collected vault-relative markdown map.

    Args:
        path_base (Path): Base for issue ``path`` keys (wiki root or vault scope root).
        by_rel (dict[str, Path]): Vault-relative path map keyed from ``path_base``.
        layout_kind (Literal["legacy", "para"]): Active layout (type severity + rules).
        reserved_basenames (frozenset[str]): Index/log basenames exempt from type/orphan.
        index_note (Path): Resolved index/home note path.
        log_note (Path): Resolved log note path.
        exempt_dir_prefixes (tuple[str, ...]): Directory prefixes skipped for orphan/staleness.
        stale_days (int): Freshness age threshold in days.

    Returns:
        list[LintIssue]: Collected findings.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> with tempfile.TemporaryDirectory() as td:
        ...     wiki = Path(td)
        ...     _ = (wiki / "note.md").write_text("# n\\n", encoding="utf-8")
        ...     by = {"note.md": wiki / "note.md"}
        ...     out = _lint_collected_tree(
        ...         path_base=wiki,
        ...         by_rel=by,
        ...         layout_kind="legacy",
        ...         reserved_basenames=frozenset({"index.md", "log.md"}),
        ...         index_note=wiki / "index.md",
        ...         log_note=wiki / "log.md",
        ...         exempt_dir_prefixes=(),
        ...         stale_days=90,
        ...     )
        ...     any("orphan page" in i.message for i in out)
        False
    """
    issues: list[LintIssue] = []
    base = path_base.resolve()
    index_rel = index_note.resolve().relative_to(base).as_posix() if index_note.is_file() else None
    log_rel = log_note.resolve().relative_to(base).as_posix() if log_note.is_file() else None

    if index_note.is_file():
        idx_sz = index_note.stat().st_size
        if idx_sz > _INDEX_MD_WARN_BYTES:
            idx_path = index_rel or index_note.name
            issues.append(
                LintIssue(
                    severity="low",
                    path=idx_path,
                    message=(f"index.md large ({idx_sz} bytes); consider splitting the catalog"),
                ),
            )

    incoming = _collect_incoming_links(by_rel, index_rel=index_rel)
    now = datetime.now(tz=UTC)
    type_severity = "error" if layout_kind == "legacy" else "warning"
    type_message = (
        "missing OKF type frontmatter"
        if layout_kind == "legacy"
        else "missing advisory type frontmatter"
    )

    for rel, fp in sorted(by_rel.items()):
        if any(
            rel == prefix or rel.startswith(f"{prefix}/")
            for prefix in exempt_dir_prefixes
            if prefix
        ):
            continue

        text = fp.read_text(encoding="utf-8", errors="replace")
        fm, body, _ = split_frontmatter(text)

        for kind, target in iter_internal_link_targets(body):
            if resolve_wiki_target(kind, target, source_rel=rel, by_rel=by_rel) is not None:
                continue
            if kind == "wikilink":
                msg = f"orphan wikilink target missing: [[{target}]]"
            else:
                msg = f"orphan OKF link target missing: [{target}]"
            issues.append(LintIssue(severity="medium", path=rel, message=msg))

        if okf_type_required(rel, reserved_basenames=reserved_basenames) and missing_okf_type(fm):
            issues.append(
                LintIssue(
                    severity=type_severity,
                    path=rel,
                    message=type_message,
                ),
            )

        if rel.endswith(tuple(reserved_basenames)):
            continue

        if (
            layout_kind == "legacy"
            and len(body) > 400
            and not re.search(r"\[Source:", body, flags=re.IGNORECASE)
        ):
            issues.append(
                LintIssue(
                    severity="low",
                    path=rel,
                    message="missing [Source: …] attribution on long body",
                ),
            )

        issues.extend(
            _staleness_issues(rel, fm, stale_days=stale_days, now=now, layout_kind=layout_kind),
        )

        if rel in {index_rel, log_rel}:
            continue
        if layout_kind == "para" and rel not in incoming:
            issues.append(
                LintIssue(
                    severity="medium",
                    path=rel,
                    message="orphan page: no incoming links",
                ),
            )

    return issues


def lint_vault_tree(layout: VaultLayout, *, stale_days: int = 90) -> list[LintIssue]:
    """Scan vault content roots for dangling links, orphan pages, and staleness.

    Legacy layout enforces OKF ``type`` as an error; PARA treats ``type`` as advisory
    (warning). Templates and archive directories are excluded from orphan/staleness scans.

    Args:
        layout (VaultLayout): Active vault layout resolver.
        stale_days (int): Age threshold (days) for freshness staleness hints.

    Returns:
        list[LintIssue]: Collected findings (empty when no content roots exist).

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> from sevn.config.workspace_config import SecondBrainWorkspaceConfig
        >>> ws = Path(tempfile.mkdtemp())
        >>> layout = VaultLayout(ws, SecondBrainWorkspaceConfig(), "owner")
        >>> lint_vault_tree(layout)
        []
    """
    vault_root = layout.scope_root
    layout_kind = layout.layout_kind
    content_roots = layout.content_roots()
    index_note = layout.index_note()
    log_note = layout.log_note()
    extra = tuple(p for p in (index_note, log_note) if p.is_file())
    by_rel = collect_vault_md_by_rel(content_roots, vault_root=vault_root, extra_files=extra)

    exempt: tuple[str, ...] = ()
    if layout_kind == "para":
        templates = layout.role_dir("templates").resolve().relative_to(vault_root).as_posix()
        archive = layout.role_dir("archive").resolve().relative_to(vault_root).as_posix()
        exempt = (templates, archive)

    return _lint_collected_tree(
        path_base=vault_root,
        by_rel=by_rel,
        layout_kind=layout_kind,
        reserved_basenames=reserved_basenames_for_layout(layout),
        index_note=index_note,
        log_note=log_note,
        exempt_dir_prefixes=exempt,
        stale_days=stale_days,
    )


def lint_wiki_tree(wiki_root: Path, *, stale_days: int = 90) -> list[LintIssue]:
    """Scan ``wiki_root`` for orphans, missing sources, stale freshness (legacy shim).

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
    if not wiki_root.is_dir():
        return []

    by_rel = {p.relative_to(wiki_root).as_posix(): p for p in sorted(wiki_root.rglob("*.md"))}
    index_note = wiki_root / "index.md"
    log_note = wiki_root / "log.md"

    return _lint_collected_tree(
        path_base=wiki_root,
        by_rel=by_rel,
        layout_kind="legacy",
        reserved_basenames=frozenset({"index.md", "log.md"}),
        index_note=index_note,
        log_note=log_note,
        exempt_dir_prefixes=(),
        stale_days=stale_days,
    )


def issues_to_json(issues: list[LintIssue]) -> list[dict[str, str]]:
    """Convert lint issues to JSON-serialisable dict rows.

    Args:
        issues (list[LintIssue]): Findings from :func:`lint_vault_tree` or :func:`lint_wiki_tree`.

    Returns:
        list[dict[str, str]]: Rows with ``severity``, ``path``, and ``message`` keys.

    Examples:
        >>> issues_to_json([])
        []
    """
    return [{"severity": i.severity, "path": i.path, "message": i.message} for i in issues]


__all__ = ["LintIssue", "issues_to_json", "lint_vault_tree", "lint_wiki_tree"]
