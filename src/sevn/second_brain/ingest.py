"""Deterministic raw→wiki ingest pipeline (`specs/27-second-brain.md` §2.2).

Exports:
    raw_content_hash — SHA-256 hex digest for idempotency checks.
    run_ingest — read sources and write a curated ingest page (layout-aware).
"""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, date, datetime
from pathlib import Path

from sevn.config.sections.features import SecondBrainPathsConfig
from sevn.config.workspace_config import SecondBrainWorkspaceConfig
from sevn.second_brain.bootstrap import detect_layout
from sevn.second_brain.frontmatter import compose_page, normalise_agent_keys, split_frontmatter
from sevn.second_brain.paths import (
    VaultLayout,
    effective_scope,
    resolve_raw_file,
    resolve_scope_root,
)

_MAX_EXCERPT_CHARS = 4000


def _resolve_ingest_cfg(
    *,
    workspace_root: Path,
    vault_users_scope: Path,
    sb_cfg: SecondBrainWorkspaceConfig | None,
    scope: str | None,
) -> SecondBrainWorkspaceConfig:
    """Return Second Brain config for ingest, inferring layout from the caller scope root.

    Args:
        workspace_root (Path): Workspace content root (``sevn.json`` directory).
        vault_users_scope (Path): Caller-resolved scope directory for this vault user.
        sb_cfg (SecondBrainWorkspaceConfig | None): Explicit config when supplied.
        scope (str | None): Scope id when resolving the default legacy layout.

    Returns:
        SecondBrainWorkspaceConfig: Config slice used for :class:`VaultLayout` resolution.

    Examples:
        >>> _resolve_ingest_cfg.__name__
        '_resolve_ingest_cfg'
    """
    if sb_cfg is not None:
        return sb_cfg
    ws_root = Path(os.path.realpath(workspace_root))
    vault_scope = Path(os.path.realpath(vault_users_scope))
    default_cfg = SecondBrainWorkspaceConfig()
    default_scope = Path(os.path.realpath(resolve_scope_root(ws_root, default_cfg, scope)))
    if vault_scope == default_scope:
        return default_cfg
    rel_vault = vault_scope.relative_to(ws_root).as_posix()
    layout = detect_layout(vault_users_scope) or "legacy"
    return SecondBrainWorkspaceConfig(
        layout=layout,
        paths=SecondBrainPathsConfig(vault=rel_vault),
    )


def raw_content_hash(data: bytes) -> str:
    """Return SHA-256 hex digest of raw file bytes.

    Args:
        data (bytes): Raw file contents.

    Returns:
        str: Lowercase hex digest used in ``sevn_raw_hash`` / ``source_hash`` frontmatter.

    Examples:
        >>> raw_content_hash(b"hello")
        '2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824'
    """

    return hashlib.sha256(data).hexdigest()


def _append_log(log_path: Path, line: str) -> None:
    """Append a dated line to the vault log note (create file when missing).

    Args:
        log_path (Path): Resolved log note path from :meth:`VaultLayout.log_note`.
        line (str): Markdown line to append under today's ``## [YYYY-MM-DD]`` section.

    Examples:
        >>> _append_log.__name__
        '_append_log'
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()  # noqa: DTZ011
    header = f"## [{today}]"
    if log_path.is_file():
        text = log_path.read_text(encoding="utf-8")
        if header not in text:
            text = text.rstrip() + f"\n\n{header}\n{line}\n"
        else:
            parts = text.split(header, maxsplit=1)
            rest = parts[1] if len(parts) > 1 else ""
            text = parts[0] + header + rest.rstrip() + f"\n{line}\n"
    else:
        text = f"# Log\n\n{header}\n{line}\n"
    log_path.write_text(text, encoding="utf-8")


def _ingest_page_path(layout: VaultLayout, stem: str) -> tuple[Path, str]:
    """Return the ingest page path and wiki-relative path for the active layout.

    Args:
        layout (VaultLayout): Active vault layout resolver.
        stem (str): Raw source filename stem.

    Returns:
        tuple[Path, str]: Absolute page path and relative path for tool responses.

    Examples:
        >>> _ingest_page_path.__name__
        '_ingest_page_path'
    """
    if layout.layout_kind == "para":
        capture = layout.role_dir("capture")
        capture.mkdir(parents=True, exist_ok=True)
        page = capture / f"{stem}.md"
        return page, page.relative_to(layout.scope_root).as_posix()
    wiki = layout.role_dir("curated")
    ingests = wiki / "ingests"
    ingests.mkdir(parents=True, exist_ok=True)
    page = ingests / f"{stem}.md"
    return page, page.relative_to(wiki).as_posix()


def _ensure_index_entry(
    layout: VaultLayout,
    *,
    title: str,
    stem: str,
    page_rel: str,
) -> None:
    """Ensure the vault index note lists the ingest wikilink for ``stem``.

    Args:
        layout (VaultLayout): Active vault layout resolver.
        title (str): Human-readable title shown in the index bullet.
        stem (str): Raw file stem used to build the wikilink target.
        page_rel (str): Relative ingest page path for legacy wikilink construction.

    Examples:
        >>> _ensure_index_entry.__name__
        '_ensure_index_entry'
    """
    idx = layout.index_note()
    idx.parent.mkdir(parents=True, exist_ok=True)
    if layout.layout_kind == "para":
        wikilink = f"{layout.role_dir('capture').name}/{stem}"
    else:
        wikilink = page_rel.removesuffix(".md") if page_rel.endswith(".md") else page_rel
        if not wikilink.startswith("ingests/"):
            wikilink = f"ingests/{stem}"
    bullet = f"- [[{wikilink}]] — {title}"
    if idx.is_file():
        body = idx.read_text(encoding="utf-8")
        if wikilink not in body:
            idx.write_text(body.rstrip() + f"\n{bullet}\n", encoding="utf-8")
    else:
        idx.write_text(
            compose_page(
                {"title": "Wiki index"},
                f"# Index\n\n{bullet}\n",
            ),
            encoding="utf-8",
        )


def _derive_title(stem: str, raw_text: str) -> str:
    """Pick a page title from the first markdown heading or the file stem.

    Args:
        stem (str): Raw filename stem.
        raw_text (str): Full raw file text.

    Returns:
        str: Title for the wiki page heading and frontmatter.

    Examples:
        >>> _derive_title("note", "# My Note\\nbody")
        'My Note'
    """
    for line in raw_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            heading = stripped.lstrip("#").strip()
            if heading:
                return heading
    return stem.replace("-", " ").replace("_", " ").title()


def _build_body(title: str, raw_relpath: str, raw_text: str, *, source_path: str) -> str:
    """Compose wiki body with summary, excerpt, and source citation.

    Args:
        title (str): Page title (also used as top-level heading).
        raw_relpath (str): Path relative to the sources role directory.
        raw_text (str): Full raw source text.
        source_path (str): Display path for the ingested source (may include role prefix).

    Returns:
        str: Markdown body without frontmatter fence.

    Examples:
        >>> body = _build_body("Note", "n.md", "content", source_path="raw/n.md")
        >>> "[Source: n.md]" in body
        True
    """
    excerpt = raw_text.strip()
    if len(excerpt) > _MAX_EXCERPT_CHARS:
        excerpt = excerpt[:_MAX_EXCERPT_CHARS] + "\n\n…"
    return (
        f"# {title}\n\n"
        f"## Summary\n\n"
        f"Ingested from `{source_path}`.\n\n"
        f"## Source excerpt\n\n"
        f"{excerpt}\n\n"
        f"[Source: {raw_relpath}]\n"
    )


def _stored_raw_hash(fm: dict[str, object]) -> object:
    """Return the stored content hash from legacy or PARA frontmatter keys.

    Args:
        fm (dict[str, object]): Parsed frontmatter mapping.

    Returns:
        object: Stored hash value, or ``None`` when absent.

    Examples:
        >>> _stored_raw_hash({"sevn_raw_hash": "abc"})
        'abc'
    """
    return fm.get("source_hash") or fm.get("sevn_raw_hash")


def run_ingest(
    *,
    workspace_root: Path,
    vault_users_scope: Path,
    raw_relpath: str,
    sevn_source: str,
    sb_cfg: SecondBrainWorkspaceConfig | None = None,
    scope: str | None = None,
) -> dict[str, object]:
    """Ingest one source file into a curated page idempotently (layout-aware).

    Legacy layout reads ``raw/`` and writes ``wiki/ingests/<stem>.md``. PARA layout
    reads ``<resources>/_sources/`` and writes ``<inbox>/<stem>.md``. Log lines append
    to the active layout's log note.

    Skips body overwrite when the page was human-promoted (``stub: false``) or when the
    stored content hash matches the current source bytes.

    Args:
        workspace_root (Path): Workspace content root (``sevn.json`` directory).
        vault_users_scope (Path): Resolved ``users/<scope>/`` directory for this vault user.
        raw_relpath (str): Path relative to the sources role directory.
        sevn_source (str): Provenance label stored in frontmatter.
        sb_cfg (SecondBrainWorkspaceConfig | None): Second Brain slice for layout resolution.
        scope (str | None): Scope id when ``sb_cfg`` is set.

    Returns:
        dict[str, object]: ``path``, ``promoted``, ``skipped``, ``raw``, and ``raw_hash`` keys.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> ws = Path(tempfile.mkdtemp())
        >>> scope = ws / "u"
        >>> raw = scope / "raw"
        >>> _ = raw.mkdir(parents=True)
        >>> _ = (raw / "n.md").write_text("# Title\\nbody", encoding="utf-8")
        >>> out = run_ingest(
        ...     workspace_root=ws,
        ...     vault_users_scope=scope,
        ...     raw_relpath="n.md",
        ...     sevn_source="doctest",
        ... )
        >>> out["skipped"]
        False
    """

    cfg = _resolve_ingest_cfg(
        workspace_root=workspace_root,
        vault_users_scope=vault_users_scope,
        sb_cfg=sb_cfg,
        scope=scope,
    )
    sc = effective_scope(scope, cfg)
    _ = vault_users_scope  # caller-resolved scope root; layout re-resolves via cfg + scope
    layout = VaultLayout(workspace_root, cfg, sc)
    raw_root = layout.role_dir("sources")
    log_path = layout.log_note()
    raw_file = resolve_raw_file(
        raw_root=raw_root, workspace_root=workspace_root, rel_path=raw_relpath
    )
    if not raw_file.is_file():
        msg = f"raw file missing: {raw_relpath}"
        raise FileNotFoundError(msg)

    raw_bytes = raw_file.read_bytes()
    digest = raw_content_hash(raw_bytes)
    raw_text = raw_bytes.decode("utf-8", errors="replace")

    stem = raw_file.stem
    page, rel_page = _ingest_page_path(layout, stem)
    source_relpath = raw_file.relative_to(layout.scope_root).as_posix()
    title = _derive_title(stem, raw_text)
    now_iso = datetime.now(tz=UTC).replace(microsecond=0).isoformat()
    layout_mode = cfg.layout

    if page.is_file():
        full = page.read_text(encoding="utf-8")
        fm, _body, _ = split_frontmatter(full)
        if fm.get("stub") is False:
            _append_log(
                log_path,
                f"ingest skipped body overwrite (promoted) for `{raw_relpath}`",
            )
            return {
                "path": rel_page,
                "promoted": True,
                "skipped": True,
                "raw": raw_relpath,
                "raw_hash": digest,
            }
        if _stored_raw_hash(fm) == digest:
            _append_log(
                log_path,
                f"ingest skipped unchanged raw for `{raw_relpath}`",
            )
            return {
                "path": rel_page,
                "promoted": False,
                "skipped": True,
                "raw": raw_relpath,
                "raw_hash": digest,
            }

    body = _build_body(title, raw_relpath, raw_text, source_path=source_relpath)
    if layout_mode == "para":
        fm_input: dict[str, object] = {
            "type": "Ingest",
            "title": title,
            "stub": False,
            "source": sevn_source,
            "source_hash": digest,
            "captured": now_iso,
        }
    else:
        fm_input = {
            "type": "Ingest",
            "title": title,
            "stub": False,
            "sevn_source": sevn_source,
            "sevn_evidence": [source_relpath],
            "sevn_raw_hash": digest,
            "sevn_freshness": {
                "first_seen": now_iso,
                "last_seen": now_iso,
            },
        }
    fm = normalise_agent_keys(fm_input, layout=layout_mode)
    page.write_text(compose_page(fm, body), encoding="utf-8")
    _ensure_index_entry(layout, title=title, stem=stem, page_rel=rel_page)
    _append_log(log_path, f"ingest | `{raw_relpath}` → `{rel_page}`")

    return {
        "path": rel_page,
        "promoted": False,
        "skipped": False,
        "raw": raw_relpath,
        "raw_hash": digest,
    }


__all__ = ["raw_content_hash", "run_ingest"]
