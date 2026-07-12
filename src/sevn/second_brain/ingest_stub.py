"""Idempotent stub ingest (`specs/27-second-brain.md` §2.2).

Exports:
    run_ingest_stub — create or refresh stub page under ``wiki/ingests/``.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from sevn.second_brain.frontmatter import compose_page, normalise_agent_keys, split_frontmatter
from sevn.second_brain.paths import raw_dir_for_scope, resolve_raw_file, wiki_dir_for_scope


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


def run_ingest_stub(
    *,
    workspace_root: Path,
    vault_users_scope: Path,
    raw_relpath: str,
    sevn_source: str,
) -> dict[str, object]:
    """Create or refresh stub under ``wiki/ingests/``; update index + log.

    Args:
        workspace_root (Path): Workspace content root (``sevn.json`` directory).
        vault_users_scope (Path): Resolved ``users/<scope>/`` directory for this vault user.
        raw_relpath (str): Path relative to ``raw/`` inside ``vault_users_scope``.
        sevn_source (str): Provenance label stored in frontmatter.

    Returns:
        dict[str, object]: ``path``, ``promoted``, and ``raw`` fields describing the outcome.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> ws = Path(tempfile.mkdtemp())
        >>> scope = ws / "u"
        >>> raw = scope / "raw"
        >>> _ = raw.mkdir(parents=True)
        >>> _ = (raw / "n.md").write_text("x", encoding="utf-8")
        >>> out = run_ingest_stub(
        ...     workspace_root=ws,
        ...     vault_users_scope=scope,
        ...     raw_relpath="n.md",
        ...     sevn_source="doctest",
        ... )
        >>> isinstance(out["path"], str)
        True
    """

    raw_root = raw_dir_for_scope(vault_users_scope)
    wiki = wiki_dir_for_scope(vault_users_scope)
    raw_file = resolve_raw_file(
        raw_root=raw_root, workspace_root=workspace_root, rel_path=raw_relpath
    )
    if not raw_file.is_file():
        msg = f"raw file missing: {raw_relpath}"
        raise FileNotFoundError(msg)

    stem = raw_file.stem
    ingests = wiki / "ingests"
    ingests.mkdir(parents=True, exist_ok=True)
    page = ingests / f"{stem}.md"
    title = f"Stub: {stem}"

    promoted = False
    if page.is_file():
        full = page.read_text(encoding="utf-8")
        fm, _body, _ = split_frontmatter(full)
        if fm.get("stub") is False:
            promoted = True

    if promoted:
        _append_log(
            wiki,
            f"ingest_stub skipped body overwrite (stub promoted) for `{raw_relpath}`",
        )
        return {
            "path": page.relative_to(wiki).as_posix(),
            "promoted": True,
            "raw": raw_relpath,
        }

    body = (
        f"# {title}\n\nStub page for raw source `raw/{raw_relpath}`.\n\n[Source: {raw_relpath}]\n"
    )
    fm = normalise_agent_keys(
        {
            "type": "Stub",
            "title": title,
            "stub": True,
            "sevn_source": sevn_source,
            "sevn_evidence": [f"raw/{raw_relpath}"],
        },
    )
    page.write_text(compose_page(fm, body), encoding="utf-8")
    _ensure_index_entry(wiki, title, stem)
    _append_log(wiki, f"stub ingest | `{raw_relpath}` → `{page.relative_to(wiki).as_posix()}`")

    return {
        "path": page.relative_to(wiki).as_posix(),
        "promoted": False,
        "raw": raw_relpath,
    }


__all__ = ["run_ingest_stub"]
