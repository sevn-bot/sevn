"""Deterministic raw→wiki ingest pipeline (`specs/27-second-brain.md` §2.2).

Exports:
    raw_content_hash — SHA-256 hex digest for idempotency checks.
    run_ingest — read ``raw/`` source and write ``wiki/ingests/<stem>.md``.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime
from pathlib import Path

from sevn.second_brain.frontmatter import compose_page, normalise_agent_keys, split_frontmatter
from sevn.second_brain.paths import raw_dir_for_scope, resolve_raw_file, wiki_dir_for_scope

_MAX_EXCERPT_CHARS = 4000


def raw_content_hash(data: bytes) -> str:
    """Return SHA-256 hex digest of raw file bytes.

    Args:
        data (bytes): Raw file contents.

    Returns:
        str: Lowercase hex digest used in ``sevn_raw_hash`` frontmatter.

    Examples:
        >>> raw_content_hash(b"hello")
        '2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824'
    """

    return hashlib.sha256(data).hexdigest()


def _append_log(wiki: Path, line: str) -> None:
    """Append a dated line to ``wiki/log.md`` (create file when missing).

    Args:
        wiki (Path): Scope ``wiki/`` directory containing or receiving ``log.md``.
        line (str): Markdown line to append under today's ``## [YYYY-MM-DD]`` section.

    Examples:
        >>> _append_log.__name__
        '_append_log'
    """
    log = wiki / "log.md"
    today = date.today().isoformat()  # noqa: DTZ011
    header = f"## [{today}]"
    if log.is_file():
        text = log.read_text(encoding="utf-8")
        if header not in text:
            text = text.rstrip() + f"\n\n{header}\n{line}\n"
        else:
            parts = text.split(header, maxsplit=1)
            rest = parts[1] if len(parts) > 1 else ""
            text = parts[0] + header + rest.rstrip() + f"\n{line}\n"
    else:
        text = f"# Log\n\n{header}\n{line}\n"
    log.write_text(text, encoding="utf-8")


def _ensure_index_entry(wiki: Path, title: str, stem: str) -> None:
    """Ensure ``wiki/index.md`` lists the ingest wikilink for ``stem``.

    Args:
        wiki (Path): Scope ``wiki/`` directory (contains ``index.md`` or creates it).
        title (str): Human-readable title shown in the index bullet.
        stem (str): Raw file stem used to build ``[[ingests/{stem}]]``.

    Examples:
        >>> _ensure_index_entry.__name__
        '_ensure_index_entry'
    """
    idx = wiki / "index.md"
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


def _build_body(title: str, raw_relpath: str, raw_text: str) -> str:
    """Compose wiki body with summary, excerpt, and source citation.

    Args:
        title (str): Page title (also used as top-level heading).
        raw_relpath (str): Path relative to ``raw/``.
        raw_text (str): Full raw source text.

    Returns:
        str: Markdown body without frontmatter fence.

    Examples:
        >>> body = _build_body("Note", "n.md", "content")
        >>> "[Source: n.md]" in body
        True
    """
    excerpt = raw_text.strip()
    if len(excerpt) > _MAX_EXCERPT_CHARS:
        excerpt = excerpt[:_MAX_EXCERPT_CHARS] + "\n\n…"
    return (
        f"# {title}\n\n"
        f"## Summary\n\n"
        f"Ingested from `raw/{raw_relpath}`.\n\n"
        f"## Source excerpt\n\n"
        f"{excerpt}\n\n"
        f"[Source: {raw_relpath}]\n"
    )


def run_ingest(
    *,
    workspace_root: Path,
    vault_users_scope: Path,
    raw_relpath: str,
    sevn_source: str,
) -> dict[str, object]:
    """Ingest one ``raw/`` file into ``wiki/ingests/<stem>.md`` idempotently.

    Skips body overwrite when the page was human-promoted (``stub: false``) or when
    ``sevn_raw_hash`` matches the current raw bytes. Always updates ``wiki/log.md`` on
    skip paths with an explanatory note.

    Args:
        workspace_root (Path): Workspace content root (``sevn.json`` directory).
        vault_users_scope (Path): Resolved ``users/<scope>/`` directory for this vault user.
        raw_relpath (str): Path relative to ``raw/`` inside ``vault_users_scope``.
        sevn_source (str): Provenance label stored in frontmatter.

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

    raw_root = raw_dir_for_scope(vault_users_scope)
    wiki = wiki_dir_for_scope(vault_users_scope)
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
    ingests = wiki / "ingests"
    ingests.mkdir(parents=True, exist_ok=True)
    page = ingests / f"{stem}.md"
    rel_page = page.relative_to(wiki).as_posix()
    title = _derive_title(stem, raw_text)
    now_iso = datetime.now(tz=UTC).replace(microsecond=0).isoformat()

    if page.is_file():
        full = page.read_text(encoding="utf-8")
        fm, _body, _ = split_frontmatter(full)
        if fm.get("stub") is False:
            _append_log(
                wiki,
                f"ingest skipped body overwrite (promoted) for `{raw_relpath}`",
            )
            return {
                "path": rel_page,
                "promoted": True,
                "skipped": True,
                "raw": raw_relpath,
                "raw_hash": digest,
            }
        if fm.get("sevn_raw_hash") == digest:
            _append_log(
                wiki,
                f"ingest skipped unchanged raw for `{raw_relpath}`",
            )
            return {
                "path": rel_page,
                "promoted": False,
                "skipped": True,
                "raw": raw_relpath,
                "raw_hash": digest,
            }

    body = _build_body(title, raw_relpath, raw_text)
    fm = normalise_agent_keys(
        {
            "type": "Ingest",
            "title": title,
            "stub": False,
            "sevn_source": sevn_source,
            "sevn_evidence": [f"raw/{raw_relpath}"],
            "sevn_raw_hash": digest,
            "sevn_freshness": {
                "first_seen": now_iso,
                "last_seen": now_iso,
            },
        },
    )
    page.write_text(compose_page(fm, body), encoding="utf-8")
    _ensure_index_entry(wiki, title, stem)
    _append_log(wiki, f"ingest | `{raw_relpath}` → `{rel_page}`")

    return {
        "path": rel_page,
        "promoted": False,
        "skipped": False,
        "raw": raw_relpath,
        "raw_hash": digest,
    }


__all__ = ["raw_content_hash", "run_ingest"]
