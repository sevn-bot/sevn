"""Substring search + simple TF ranking (`specs/27-second-brain.md` §2.2).

Optional ``mode: \"semantic\"`` merges Witchcraft scores only when integration reports a fresh
index (<5 min); otherwise keyword-only (`specs/27-second-brain.md` §6).

Exports:
    SearchHit — ranked hit row (path, title, score, snippet, origin).
    wiki_search — scan user (and optional shared) wiki trees and rank matches.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from sevn.second_brain.frontmatter import split_frontmatter
from sevn.second_brain.witchcraft_bridge import (
    WitchcraftConfig,
    maybe_semantic_scores,
    semantic_mode_allowed,
)


@dataclass(frozen=True)
class SearchHit:
    """One ranked wiki hit."""

    path: str
    title: str | None
    score: float
    snippet: str
    origin: str


def _tokenize(q: str) -> list[str]:
    """Split ``q`` into lowercase tokens for TF scoring.

    Args:
        q (str): Raw query string (whitespace-separated tokens).

    Returns:
        list[str]: Non-empty lowercase tokens after splitting on whitespace.

    Examples:
        >>> _tokenize("  Hello   World  ")
        ['hello', 'world']
    """
    return [t for t in re.split(r"\s+", q.lower().strip()) if t]


def _snippet(body: str, query: str, width: int = 120) -> str:
    """Return a short excerpt from ``body`` around the first query token hit.

    Args:
        body (str): Full page body text (newlines collapsed in the excerpt).
        query (str): User query; substring match preferred, else first token match.
        width (int): Maximum character width of the returned window.

    Returns:
        str: A trimmed slice of ``body`` centered near the first match (or start of ``body``).

    Examples:
        >>> _snippet("alpha beta", "alpha", width=20)
        'alpha beta'
    """
    lower = body.lower()
    qlow = query.lower().strip()
    idx = lower.find(qlow) if qlow else 0
    if idx < 0 and qlow:
        for tok in _tokenize(query):
            idx = lower.find(tok)
            if idx >= 0:
                break
    if idx < 0:
        idx = 0
    start = max(0, idx - width // 2)
    chunk = body[start : start + width].replace("\n", " ")
    return chunk.strip()


def _tf_score(body: str, tokens: list[str]) -> float:
    """Compute a naive term-frequency score for ``tokens`` inside ``body``.

    Args:
        body (str): Page body in which occurrences are counted (case-insensitive).
        tokens (list[str]): Lowercase tokens (typically from :func:`_tokenize`).

    Returns:
        float: Sum of per-token occurrence counts; ``0.0`` when ``tokens`` is empty.

    Examples:
        >>> _tf_score("foo bar foo", ["foo"])
        2.0
        >>> _tf_score("x", [])
        0.0
    """
    if not tokens:
        return 0.0
    lower = body.lower()
    return float(sum(lower.count(t) for t in tokens))


def _iter_wiki_files(wiki_root: Path) -> list[Path]:
    """List ``*.md`` files under ``wiki_root`` (empty when missing).

    Args:
        wiki_root (Path): Root ``wiki/`` directory for a scope.

    Returns:
        list[Path]: Sorted markdown files under ``wiki_root``; empty if not a directory.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> root = Path(tempfile.mkdtemp()) / "w"
        >>> _ = root.mkdir()
        >>> _ = (root / "a.md").write_text("x", encoding="utf-8")
        >>> [p.name for p in _iter_wiki_files(root)]
        ['a.md']
    """
    if not wiki_root.is_dir():
        return []
    return sorted(wiki_root.rglob("*.md"))


def wiki_search(
    *,
    query: str,
    user_wiki: Path,
    shared_wiki: Path | None,
    limit: int = 20,
    mode: str | None = None,
    use_witchcraft: bool = False,
    witchcraft_cfg: WitchcraftConfig | None = None,
    workspace_path: Path | None = None,
) -> list[dict[str, object]]:
    """Rank wiki pages by substring/TF; optional semantic blend when fresh.

    Args:
        query (str): Search string.
        user_wiki (Path): User-scope ``wiki/`` root.
        shared_wiki (Path | None): Optional shared wiki overlay root.
        limit (int): Maximum hits (clamped to ``[1, 50]``).
        mode (str | None): Pass ``semantic`` to request semantic blending when allowed.
        use_witchcraft (bool): Force semantic path when integration reports fresh index.
        witchcraft_cfg (WitchcraftConfig | None): Parsed Witchcraft config for probe + dispatch.
        workspace_path (Path | None): Workspace root for relative db path resolution.

    Returns:
        list[dict[str, object]]: Hit dicts with ``path``, ``title``, ``score``, ``snippet``, ``origin``.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> w = Path(tempfile.mkdtemp()) / "wiki"
        >>> _ = w.mkdir()
        >>> wiki_search(query="hi", user_wiki=w, shared_wiki=None, limit=5)
        []
    """

    q = query.strip()
    tokens = _tokenize(q)
    lim = max(1, min(50, limit))
    hits: list[SearchHit] = []

    def scan_root(root: Path, origin: str) -> None:
        for fp in _iter_wiki_files(root):
            rel = fp.relative_to(root).as_posix()
            text = fp.read_text(encoding="utf-8", errors="replace")
            fm, body, _ = split_frontmatter(text)
            title_o = fm.get("title")
            title = title_o if isinstance(title_o, str) else None
            sc = _tf_score(body, tokens) + body.lower().count(q.lower()) * 2.0
            if sc <= 0 and q:
                continue
            hits.append(
                SearchHit(
                    path=rel,
                    title=title,
                    score=sc,
                    snippet=_snippet(body, q),
                    origin=origin,
                ),
            )

    scan_root(user_wiki, "user")
    if shared_wiki and shared_wiki.is_dir():
        user_names = {p.name for p in _iter_wiki_files(user_wiki)}
        for fp in _iter_wiki_files(shared_wiki):
            if fp.name in user_names:
                continue
            rel = fp.relative_to(shared_wiki).as_posix()
            text = fp.read_text(encoding="utf-8", errors="replace")
            fm, body, _ = split_frontmatter(text)
            title_o = fm.get("title")
            title = title_o if isinstance(title_o, str) else None
            sc = _tf_score(body, tokens) + body.lower().count(q.lower()) * 2.0
            if sc <= 0 and q:
                continue
            hits.append(
                SearchHit(
                    path=rel,
                    title=title,
                    score=sc,
                    snippet=_snippet(body, q),
                    origin="shared",
                ),
            )

    want_sem = (mode or "").lower() == "semantic" or use_witchcraft
    if want_sem and semantic_mode_allowed(witchcraft_cfg, workspace_path):
        sem = maybe_semantic_scores(
            user_wiki,
            query=q,
            _shared_wiki=shared_wiki,
            witchcraft_cfg=witchcraft_cfg,
            workspace_path=workspace_path,
        )
        if sem:
            adjusted: list[SearchHit] = []
            for h in hits:
                boost = sem.get((h.origin, h.path), 0.0)
                adjusted.append(
                    SearchHit(
                        path=h.path,
                        title=h.title,
                        score=h.score + boost,
                        snippet=h.snippet,
                        origin=h.origin,
                    ),
                )
            hits = adjusted

    hits.sort(key=lambda h: h.score, reverse=True)

    out: list[dict[str, object]] = []
    for h in hits[:lim]:
        out.append(
            {
                "path": h.path,
                "title": h.title,
                "score": h.score,
                "snippet": h.snippet,
                "origin": h.origin,
            },
        )
    return out


__all__ = ["SearchHit", "wiki_search"]
