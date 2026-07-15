"""``second_brain_query`` — index-first then body grep (`specs/27-second-brain.md` section 2.2).

Exports:
    second_brain_query — combine ``index.md`` hints with ranked wiki search.

Callers pass ``user_wiki`` as the primary content root; optional ``content_roots`` scans
all layout content roots (PARA inbox/projects/areas/resources).
"""

from __future__ import annotations

import re
from pathlib import Path

from sevn.second_brain.frontmatter import split_frontmatter
from sevn.second_brain.links import index_line_targets
from sevn.second_brain.search import wiki_search
from sevn.second_brain.witchcraft_bridge import WitchcraftConfig, semantic_mode_allowed


def _extract_source_refs(body: str) -> list[str]:
    """Collect ``[Source: …]`` reference strings from markdown ``body``.

    Args:
        body (str): Wiki page body text (may include frontmatter already stripped).

    Returns:
        list[str]: Bracket contents after ``Source:`` for each match (stripped).

    Examples:
        >>> _extract_source_refs("See [Source: raw/x.md] and [SOURCE: y]")
        ['raw/x.md', 'y']
    """
    refs: list[str] = []
    for m in re.finditer(r"\[Source:\s*([^\]]+)\]", body, flags=re.IGNORECASE):
        refs.append(m.group(1).strip())
    return refs


def _resolve_index_path(
    user_wiki: Path,
    content_roots: tuple[Path, ...] | None,
    *,
    index_note: Path | None = None,
) -> Path:
    """Return the vault index note path for legacy or multi-root PARA layouts.

    Args:
        user_wiki (Path): Primary user wiki/content root.
        content_roots (tuple[Path, ...] | None): Optional layout content roots.
        index_note (Path | None): Explicit index note path from :class:`VaultLayout`.

    Returns:
        Path: Resolved ``index.md`` path for index-first query hints.

    Examples:
        >>> from pathlib import Path
        >>> _resolve_index_path(Path("/tmp/wiki"), None)
        PosixPath('/tmp/wiki/index.md')
    """
    if index_note is not None:
        return index_note
    if content_roots and len(content_roots) > 1:
        return content_roots[0].parent / "index.md"
    return user_wiki / "index.md"


def second_brain_query(
    *,
    q: str,
    user_wiki: Path,
    shared_wiki: Path | None,
    include_shared: bool = True,
    use_witchcraft: bool = False,
    limit: int = 20,
    witchcraft_cfg: WitchcraftConfig | None = None,
    workspace_path: Path | None = None,
    content_roots: tuple[Path, ...] | None = None,
    vault_root: Path | None = None,
    index_note: Path | None = None,
) -> list[dict[str, object]]:
    """Read the vault index note first, then match bodies; union overlay semantics.

    Args:
        q (str): Query text for index and body matching.
        user_wiki (Path): Resolved primary content root for the user scope.
        shared_wiki (Path | None): Optional shared wiki root for overlay reads.
        include_shared (bool): When false, do not scan ``shared_wiki``.
        use_witchcraft (bool): When true and integration allows, blend semantic scores.
        limit (int): Maximum rows returned (clamped to ``[1, 50]``).
        witchcraft_cfg (WitchcraftConfig | None): Parsed Witchcraft config for probe + dispatch.
        workspace_path (Path | None): Workspace root for relative db path resolution.
        content_roots (tuple[Path, ...] | None): When set, scan all layout content roots.
        vault_root (Path | None): Vault scope root for vault-relative path resolution.
        index_note (Path | None): Explicit index note path from :class:`VaultLayout`.

    Returns:
        list[dict[str, object]]: Rows with ``page``, ``snippet``, ``frontmatter``, ``origin``.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> w = Path(tempfile.mkdtemp()) / "wiki"
        >>> _ = w.mkdir()
        >>> _ = (w / "index.md").write_text("# i\\n- [[a.md]]\\n", encoding="utf-8")
        >>> out = second_brain_query(
        ...     q="a",
        ...     user_wiki=w,
        ...     shared_wiki=None,
        ...     include_shared=False,
        ...     limit=5,
        ... )
        >>> isinstance(out, list)
        True
    """

    lim = max(1, min(50, limit))
    index_path = _resolve_index_path(user_wiki, content_roots, index_note=index_note)
    candidates: list[str] = []
    if index_path.is_file():
        text = index_path.read_text(encoding="utf-8", errors="replace")
        _fm, body, _ = split_frontmatter(text)
        for line in body.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            candidates.extend(index_line_targets(line))

    hits = wiki_search(
        query=q,
        user_wiki=user_wiki,
        shared_wiki=shared_wiki if include_shared else None,
        limit=lim * 2,
        use_witchcraft=use_witchcraft and semantic_mode_allowed(witchcraft_cfg, workspace_path),
        witchcraft_cfg=witchcraft_cfg,
        workspace_path=workspace_path,
        content_roots=content_roots,
        vault_root=vault_root,
    )

    seen: set[tuple[str, str]] = set()
    out: list[dict[str, object]] = []
    # Prioritise index candidates
    index_set = {
        c
        for c in candidates
        if q.lower() in c.lower() or any(t in c.lower() for t in q.lower().split())
    }

    def add_from_path(origin: str, rel: str) -> None:
        key = (origin, rel)
        if key in seen:
            return
        fp: Path | None = None
        if content_roots and origin == "user":
            if vault_root is not None and "/" in rel:
                candidate = (vault_root / rel).resolve()
                try:
                    candidate.relative_to(vault_root.resolve())
                    if candidate.is_file():
                        fp = candidate
                except ValueError:
                    fp = None
            if fp is None:
                for root in content_roots:
                    candidate = (root / rel).resolve()
                    try:
                        candidate.relative_to(root.resolve())
                    except ValueError:
                        continue
                    if candidate.is_file():
                        fp = candidate
                        break
        else:
            if origin == "user":
                root = user_wiki
            else:
                shared_root = shared_wiki
                if shared_root is None:
                    return
                root = shared_root
            candidate = (root / rel).resolve()
            try:
                candidate.relative_to(root.resolve())
            except ValueError:
                return
            if candidate.is_file():
                fp = candidate
        if fp is None:
            return
        seen.add(key)
        full = fp.read_text(encoding="utf-8", errors="replace")
        fm, body, _ = split_frontmatter(full)
        snip = body.strip().replace("\n", " ")[:400]
        out.append(
            {
                "page": rel,
                "snippet": snip,
                "source_refs": _extract_source_refs(body),
                "frontmatter": fm,
                "origin": origin,
            },
        )

    for c in sorted(index_set):
        if len(out) >= lim:
            break
        add_from_path("user", c)

    for row in hits:
        if len(out) >= lim:
            break
        origin = str(row.get("origin", "user"))
        rel = str(row["path"])
        add_from_path(origin, rel)

    return out[:lim]


__all__ = ["second_brain_query"]
