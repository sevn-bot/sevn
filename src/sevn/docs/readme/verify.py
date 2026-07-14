"""Manifest summary verification against entry ``source_globs`` (D7 / C2).

Module: sevn.docs.readme.verify
Depends: dataclasses, pathlib, re, sevn.docs.readme.fingerprint, sevn.docs.readme.manifest

Exports:
    SummaryLintFinding — structured summary-lint row.
    lint_summaries — flag manifest summaries citing symbols absent from source globs.

Examples:
    >>> from pathlib import Path
    >>> from sevn.docs.readme.manifest import ReadmeEntry, ReadmeManifest
    >>> td = Path(".")
    >>> manifest = ReadmeManifest(
    ...     version=1,
    ...     entries=(
    ...         ReadmeEntry("x", "X", "Uses `Foo`.", "subsystem", "d", "x.md", ("Makefile",), ()),
    ...     ),
    ... )
    >>> isinstance(lint_summaries(manifest, td), list)
    True
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from sevn.docs.readme.fingerprint import expand_source_globs
from sevn.docs.readme.manifest import ReadmeEntry, ReadmeManifest
from sevn.docs.readme.symbol_refs import _symbol_defined_in_file

_BACKTICK = re.compile(r"`([^`]+)`")
_CONFIG_KEY = re.compile(r"\b[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+\b")
_PASCAL = re.compile(r"\b[A-Z][A-Za-z0-9_]+(?:\.[A-Za-z_][A-Za-z0-9_]*)*\b")
_AT_SYMBOL = re.compile(r"@[A-Za-z_][A-Za-z0-9_]*")
_AT_PHRASE = re.compile(r"(@[A-Za-z_][A-Za-z0-9_]*)\s+([a-z][a-z0-9_]{2,})")
_SLASH_COMPOUND = re.compile(r"\b([A-Za-z0-9]+(?:/[A-Za-z0-9]+)+)\b")
_SKIP_PASCAL = frozenset(
    {
        "Curated",
        "D1",
        "Entry",
        "GitHub",
        "JSONL",
        "MC",
        "MYCODE",
        "Obsidian",
        "OpenUI",
        "SQLite",
        "SPA",
        "STT",
        "Telegram",
        "Transport",
        "UI",
        "Web",
        "Webhooks",
        "Wiki",
        "Paired",
    }
)
_AUDIT_PHRASES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"voice\s+hooks", re.IGNORECASE), "voice hooks"),
    (
        re.compile(r"keys\s+never(?:\s+in\s+the\s+gateway\s+process)?", re.IGNORECASE),
        "keys never in the gateway process",
    ),
    (re.compile(r"session\s+tokens", re.IGNORECASE), "session tokens"),
    (re.compile(r"logfire/?otel", re.IGNORECASE), "Logfire/OTel"),
    (re.compile(r"\bActiveRunSnapshot\b"), "ActiveRunSnapshot"),
    (re.compile(r"obsidian\s+sync", re.IGNORECASE), "Obsidian sync"),
)


@dataclass(frozen=True)
class SummaryLintFinding:
    """One summary token absent from an entry's ``source_globs`` corpus."""

    slug: str
    token: str
    kind: str

    def format_error(self) -> str:
        """Return a gate-ready error string.

        Returns:
            str: ``slug: summary cites … not found in source_globs``.

        Examples:
            >>> SummaryLintFinding("tools", "@sevn_tool", "decorator").format_error()
            'tools: summary cites decorator @sevn_tool not found in source_globs'
        """
        return f"{self.slug}: summary cites {self.kind} {self.token!r} not found in source_globs"


def lint_summaries(manifest: ReadmeManifest, repo_root: Path) -> list[str]:
    """Flag manifest summaries that cite symbols absent from ``source_globs``.

        Args:
    manifest (ReadmeManifest): Loaded README manifest.
    repo_root (Path): Repository root for glob expansion.

        Returns:
            list[str]: Error strings for each absent cited token.

        Examples:
            >>> from pathlib import Path as _P
            >>> from sevn.docs.readme.manifest import load_manifest
            >>> m = load_manifest(_P("docs/readmes/manifest.toml"))
            >>> isinstance(lint_summaries(m, _P(".")), list)
            True
    """
    repo_root = repo_root.resolve()
    errors: list[str] = []
    for entry in manifest.entries:
        if entry.slug in {"index", "root"}:
            continue
        corpus = _load_corpus(repo_root, entry)
        for token, kind in _extract_summary_tokens(entry.summary):
            if not _token_present(token, kind, corpus):
                errors.append(
                    SummaryLintFinding(slug=entry.slug, token=token, kind=kind).format_error()
                )
    return errors


@dataclass
class _Corpus:
    """Expanded ``source_globs`` text and Python paths for summary grounding."""

    text: str
    py_files: list[Path]


def _load_corpus(repo_root: Path, entry: ReadmeEntry) -> _Corpus:
    """Load searchable text and Python paths for one manifest entry.

        Args:
    repo_root (Path): Repository root.
    entry (ReadmeEntry): Manifest row.

        Returns:
            _Corpus: Concatenated file text and ``.py`` paths under ``source_globs``.

        Examples:
            >>> from sevn.docs.readme.manifest import ReadmeEntry
            >>> c = _load_corpus(Path("."), ReadmeEntry("g", "G", "S", "subsystem", "g", "g.md", ("Makefile",), ()))
            >>> isinstance(c.text, str)
            True
    """
    parts: list[str] = []
    py_files: list[Path] = []
    for path in expand_source_globs(repo_root, entry.source_globs, tracked_only=False):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = path.relative_to(repo_root).as_posix()
        parts.append(rel)
        parts.append(text)
        if path.suffix == ".py":
            py_files.append(path)
    return _Corpus(text="\n".join(parts), py_files=py_files)


def _extract_summary_tokens(summary: str) -> list[tuple[str, str]]:
    """Extract cited symbols, config keys, and phrases from a manifest summary.

        Args:
    summary (str): Manifest ``summary`` field.

        Returns:
            list[tuple[str, str]]: ``(token, kind)`` pairs to verify in source globs.

        Examples:
            >>> _extract_summary_tokens("Entry `Real.exists` here.")
            [('Real.exists', 'symbol')]
    """
    found: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(token: str, kind: str) -> None:
        cleaned = token.strip()
        if not cleaned or cleaned in seen:
            return
        seen.add(cleaned)
        found.append((cleaned, kind))

    for match in _BACKTICK.finditer(summary):
        add(match.group(1), "symbol")

    for match in _AT_SYMBOL.finditer(summary):
        add(match.group(0), "decorator")

    for match in _AT_PHRASE.finditer(summary):
        add(f"{match.group(1)} {match.group(2)}", "phrase")

    for match in _CONFIG_KEY.finditer(summary):
        add(match.group(0), "config key")

    for match in _PASCAL.finditer(summary):
        token = match.group(0)
        if token in _SKIP_PASCAL or len(token) < 6 or token.isupper():
            continue
        add(token, "symbol")

    for match in _SLASH_COMPOUND.finditer(summary):
        for part in match.group(1).split("/"):
            if part and part[0].isupper():
                add(part, "symbol")

    for pattern, label in _AUDIT_PHRASES:
        if pattern.search(summary):
            add(label, "phrase")

    return found


def _token_present(token: str, kind: str, corpus: _Corpus) -> bool:
    """Return True when ``token`` appears in the entry source corpus.

        Args:
    token (str): Cited summary token.
    kind (str): Token class (``symbol``, ``config key``, ``phrase``, ``decorator``).
    corpus (_Corpus): Expanded ``source_globs`` text and Python paths.

        Returns:
            bool: True when the token is grounded in source.

        Examples:
            >>> c = _Corpus(text="class Real:\\n    def exists(self): pass", py_files=[])
            >>> _token_present("Real.exists", "symbol", c)
            False
    """
    if kind == "phrase":
        return token in corpus.text.lower()

    if kind == "decorator":
        return token in corpus.text

    if kind == "config key":
        return token in corpus.text

    if "." in token:
        return _dotted_symbol_present(token, corpus.py_files)

    if re.fullmatch(r"[A-Z][A-Za-z0-9_]*", token):
        return bool(re.search(rf"\b{re.escape(token)}\b", corpus.text))

    return token in corpus.text


def _dotted_symbol_present(symbol: str, py_files: list[Path]) -> bool:
    """Return True when ``Class.method`` is defined in one cited Python file.

        Args:
    symbol (str): Dotted symbol from the summary.
    py_files (list[Path]): Python files under the entry globs.

        Returns:
            bool: True when AST resolution finds the symbol.

        Examples:
            >>> _dotted_symbol_present("Real.exists", [])
            False
    """
    return any(_symbol_defined_in_file(py_file, symbol) for py_file in py_files)
