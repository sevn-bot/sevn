"""``second_brain_query`` — index-first then body grep (`specs/27-second-brain.md` section 2.2).

Exports:
    second_brain_query — combine ``index.md`` hints with ranked wiki search.
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
) -> list[dict[str, object]]:
    """Read ``wiki/index.md`` first, then match bodies; union overlay semantics.

    Args:
        q (str): Query text for index and body matching.
        user_wiki (Path): Resolved ``wiki/`` directory for the user scope.
        shared_wiki (Path | None): Optional shared wiki root for overlay reads.
        include_shared (bool): When false, do not scan ``shared_wiki``.
        use_witchcraft (bool): When true and integration allows, blend semantic scores.
        limit (int): Maximum rows returned (clamped to ``[1, 50]``).
        witchcraft_cfg (WitchcraftConfig | None): Parsed Witchcraft config for probe + dispatch.
        workspace_path (Path | None): Workspace root for relative db path resolution.

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
    index_path = user_wiki / "index.md"
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
        root = user_wiki if origin == "user" else shared_wiki
        if root is None:
            return
        fp = (root / rel).resolve()
        if not fp.is_file() or not str(fp).startswith(str(root.resolve())):
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
