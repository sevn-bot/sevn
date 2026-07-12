"""Migrate legacy root ``prd/``/``specs/`` seed docs into ``about-sevn.bot/``.

Module: sevn.docs.about.migrate
Depends: datetime, pathlib, re, sevn.docs.about.extract, sevn.docs.about.generate,
    sevn.docs.about.loader, sevn.docs.about.model, sevn.docs.about.registry,
    sevn.docs.readme.providers

Exports:
    migrate_all — port manifest entries from legacy seed paths to about-docs layout.
    parse_legacy_metadata — extract header fields from pre-migration markdown.
    rewrite_markdown_refs — rewrite cross-doc path links to stable doc ids.
    summary_from_legacy — derive a short summary from legacy body text.
    build_path_to_id_map — map legacy paths to stable doc ids.

Examples:
    >>> from sevn.docs.about.migrate import parse_legacy_metadata
    >>> meta = parse_legacy_metadata("**Status:** Done\\n\\n## Purpose\\n")
    >>> meta.get("status") == "done"
    True
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any

from sevn.docs.about.extract import extract_fields
from sevn.docs.about.generate import generate_body
from sevn.docs.about.loader import dump_doc
from sevn.docs.about.model import AboutDoc
from sevn.docs.about.registry import load_manifest_entries
from sevn.docs.readme.providers import OfflineProvider, ReadmeProviderConfig, build_provider

if TYPE_CHECKING:
    from pathlib import Path

_LEGACY_HEADER_RE = re.compile(r"^\*\*(?P<key>[^*]+):\*\*\s*(?P<value>.*)$")
_LINK_TARGET_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
_STATUS_MAP = {
    "draft": "draft",
    "scaffold": "scaffold",
    "ready": "ready",
    "done": "done",
    "rejected": "rejected",
}
_DEFAULT_OWNER = "Alex"
_DEFAULT_PARENT_PRD = "prd-00-main"


def parse_legacy_metadata(text: str) -> dict[str, Any]:
    """Parse legacy ``**Key:** value`` header lines from seed markdown.

    Args:
        text (str): Full legacy document text.

    Returns:
        dict[str, Any]: Normalised metadata keys (``status``, ``owner``, etc.).

    Examples:
        >>> parse_legacy_metadata("**Status:** Done\\n\\n## 1. Purpose\\n")["status"]
        'done'
    """
    metadata: dict[str, Any] = {}
    for line in text.splitlines():
        if line.startswith(("---", "# ")):
            break
        if line.strip() == "---":
            break
        match = _LEGACY_HEADER_RE.match(line.strip())
        if not match:
            if line.strip() == "" and metadata:
                break
            continue
        key = match.group("key").strip().lower().replace(" ", "_")
        value = match.group("value").strip()
        if key == "status":
            token = value.split()[0].rstrip("*").lower()
            metadata["status"] = _STATUS_MAP.get(token, "draft")
        elif key == "owner":
            metadata["owner"] = value or _DEFAULT_OWNER
        elif key == "last_updated":
            metadata["last_updated"] = value
        elif key == "parent_prd":
            if value.startswith(("—", "-")) or not value:
                metadata["parent_prd"] = None
            else:
                metadata["parent_prd"] = value
        elif key == "depends_on_(specs)":
            metadata["depends_on"] = _parse_legacy_id_list(value)
        elif key == "specs":
            metadata["specs"] = _parse_legacy_id_list(value)
    return metadata


def _parse_legacy_id_list(value: str) -> list[str]:
    """Return doc ids referenced from a legacy header list value.

    Args:
        value (str): Raw header value with markdown links.

    Returns:
        list[str]: Stable doc ids when mappable; empty when absent.

    Examples:
        >>> _parse_legacy_id_list("—")
        []
    """
    if value.startswith(("—", "-")) or not value.strip():
        return []
    ids: list[str] = []
    for match in _LINK_TARGET_RE.finditer(value):
        target = match.group(1).strip()
        doc_id = _path_target_to_id(target)
        if doc_id:
            ids.append(doc_id)
    return ids


def _path_target_to_id(target: str) -> str | None:
    """Map a legacy markdown link target to a stable about-doc id when possible.

    Args:
        target (str): Raw markdown link target.

    Returns:
        str | None: Doc id or ``None`` when not a legacy prd/spec path.

    Examples:
        >>> _path_target_to_id("../specs/17-gateway.md")
        'spec-17-gateway'
    """
    token = target.strip().split("#", 1)[0]
    if token.startswith(("https://", "http://")):
        return None
    name = token.replace("\\", "/").split("/")[-1]
    if not name.endswith(".md"):
        return None
    stem = name[:-3]
    if re.fullmatch(r"\d{2}-[a-z0-9-]+", stem):
        prefix = "spec" if "/specs/" in token or token.startswith("specs/") else "prd"
        if token.startswith("prd/"):
            prefix = "prd"
        return f"{prefix}-{stem}"
    return None


def summary_from_legacy(text: str, *, title: str, fallback: str) -> str:
    """Derive a frontmatter summary (≤ 200 chars) from legacy body text.

    Args:
        text (str): Legacy markdown body (headers stripped).
        title (str): Document title for fallback phrasing.
        fallback (str): Manifest-provided fallback summary seed.

    Returns:
        str: Summary string within 200 characters.

    Examples:
        >>> summary_from_legacy("## Purpose\\n\\nGateway turn spine overview.\\n", title="Gateway", fallback="")
        'Gateway turn spine overview.'
    """
    body = _strip_legacy_preamble(text)
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", ">")):
            continue
        if stripped.startswith(("|", "```")):
            continue
        candidate = _safe_summary(stripped, title=title)
        if len(candidate) >= 20:
            return candidate
    return _safe_summary(
        fallback.strip() or f"{title} — migrated from legacy seed doc.",
        title=title,
    )


def _plain_text_summary(text: str) -> str:
    """Strip markdown links and inline code from a candidate summary line.

    Args:
        text (str): Raw markdown fragment.

    Returns:
        str: Plain-text summary suitable for frontmatter.

    Examples:
        >>> _plain_text_summary("[x](../specs/17-gateway.md) routes turns.")
        'x routes turns.'
    """
    plain = re.sub(r"\[([^\]]*)\]\([^)]+\)", r"\1", text)
    plain = re.sub(r"`([^`]*)`", r"\1", plain)
    plain = re.sub(r"\*\*([^*]+)\*\*", r"\1", plain)
    plain = _rewrite_legacy_path_tokens(plain)
    return re.sub(r"\s+", " ", plain).strip()


def _rewrite_legacy_path_tokens(text: str) -> str:
    """Replace legacy ``prd/``/``specs/`` path tokens with stable doc ids.

    Args:
        text (str): Plain or markdown text.

    Returns:
        str: Text safe for published about-docs surfaces.

    Examples:
        >>> _rewrite_legacy_path_tokens("see prd/04-getting-things-done.md §5")
        'see prd-04-getting-things-done §5'
    """

    def _repl(match: re.Match[str]) -> str:
        tree = match.group(1)
        stem = match.group(2)
        prefix = "prd" if tree == "prd" else "spec"
        return f"{prefix}-{stem}"

    rewritten = re.sub(
        r"(?<![\w./-])(?:\.\./)?(prd|specs)/(\d{2}-[a-z0-9-]+)(?:\.md)?",
        _repl,
        text,
    )
    return re.sub(r"(?<![\w./-])plan/\S+", "the design docs", rewritten)


def _safe_summary(text: str, *, title: str) -> str:
    """Return summary text that avoids forbidden design-doc path tokens.

    Args:
        text (str): Candidate summary.
        title (str): Document title for fallback phrasing.

    Returns:
        str: Hook-safe summary within 200 characters.

    Examples:
        >>> _safe_summary("Gateway turn spine.", title="Gateway")[:20]
        'Gateway turn spine.'
    """
    cleaned = _plain_text_summary(text)
    if _FORBIDDEN_PATH_TOKEN.search(cleaned):
        cleaned = f"{title} — migrated from legacy seed doc."
    return cleaned[:200]


_FORBIDDEN_PATH_TOKEN = re.compile(r"(?<![\w./-])(plan|specs|prd)/")


def _strip_legacy_preamble(text: str) -> str:
    """Remove legacy title and ``**Key:**`` header block from markdown text.

    Args:
        text (str): Full legacy document.

    Returns:
        str: Body markdown after the preamble.

    Examples:
        >>> _strip_legacy_preamble("# Title\\n\\n**Status:** Done\\n\\nBody")
        'Body'
    """
    lines = text.splitlines()
    index = 0
    if index < len(lines) and lines[index].startswith("# "):
        index += 1
    while index < len(lines):
        line = lines[index].strip()
        if line == "" or _LEGACY_HEADER_RE.match(line) or line == "---":
            index += 1
            continue
        if line.startswith(">"):
            index += 1
            continue
        break
    return "\n".join(lines[index:]).lstrip("\n")


def build_path_to_id_map(entries: dict[str, dict[str, Any]]) -> dict[str, str]:
    """Build lookup tables from legacy paths and filenames to doc ids.

    Args:
        entries (dict[str, dict[str, Any]]): Manifest rows keyed by id.

    Returns:
        dict[str, str]: Legacy path variants → stable doc id.

    Examples:
        >>> build_path_to_id_map(
        ...     {"spec-17-gateway": {"old_path": "specs/17-gateway.md"}}
        ... )["specs/17-gateway.md"]
        'spec-17-gateway'
    """
    mapping: dict[str, str] = {}
    for doc_id, row in entries.items():
        old_path = str(row.get("old_path", "")).strip()
        if old_path:
            mapping[old_path] = doc_id
            mapping[old_path.replace("\\", "/")] = doc_id
            name = old_path.split("/")[-1]
            mapping[name] = doc_id
            mapping[f"../{old_path}"] = doc_id
    return mapping


def rewrite_markdown_refs(text: str, path_to_id: dict[str, str]) -> str:
    """Rewrite legacy prd/spec path links to stable doc-id link targets.

    Drops links to ``plan/``, root ``prd/``/``specs/`` paths that do not map,
    and private trees. Preserves ``https://`` URLs and already-valid doc ids.

    Args:
        text (str): Markdown body text.
        path_to_id (dict[str, str]): Legacy path → doc id map.

    Returns:
        str: Body with cross-doc path links rewritten to ids.

    Examples:
        >>> rewrite_markdown_refs(
        ...     "[gw](../specs/17-gateway.md)",
        ...     {"specs/17-gateway.md": "spec-17-gateway"},
        ... )
        '[gw](spec-17-gateway)'
    """

    def _replace(match: re.Match[str]) -> str:
        label = match.group(0).split("](", 1)[0] + "]"
        target = match.group(1).strip()
        if target.startswith(("https://", "http://")):
            return match.group(0)
        if re.fullmatch(r"^(prd|spec)-\d{2}-[a-z0-9-]+$", target):
            return match.group(0)
        normalised = target.replace("\\", "/").lstrip("./")
        if normalised.startswith(("plan/", "../plan/")):
            return label.replace("[", "").replace("]", "")
        mapped = (
            path_to_id.get(normalised)
            or path_to_id.get(normalised.split("#", 1)[0])
            or _path_target_to_id(normalised)
        )
        if mapped:
            return f"{label}({mapped})"
        if normalised.startswith(("prd/", "specs/", "../prd/", "../specs/")):
            return label.replace("[", "").replace("]", "")
        return match.group(0)

    return _LINK_TARGET_RE.sub(_replace, text)


def _resolve_seed_path(repo_root: Path, old_path: str) -> Path:
    """Resolve a manifest ``old_path`` under the repository root.

    Args:
        repo_root (Path): Repository root.
        old_path (str): Legacy relative path from manifest.

    Returns:
        Path: Absolute seed file path.

    Raises:
        FileNotFoundError: When the seed file cannot be located.

    Examples:
        >>> _resolve_seed_path.__name__
        '_resolve_seed_path'
    """
    candidate = (repo_root / old_path).resolve()
    if candidate.is_file():
        return candidate
    msg = f"legacy seed not found: {old_path}"
    raise FileNotFoundError(msg)


def _coerce_parent_prd(entry: dict[str, Any]) -> str | None:
    """Return a valid ``parent_prd`` for one manifest row.

    Args:
        entry (dict[str, Any]): Manifest row.

    Returns:
        str | None: Parent PRD id; ``None`` only for umbrella PRDs.

    Examples:
        >>> _coerce_parent_prd({"kind": "prd", "id": "prd-00-main"})
        >>> _coerce_parent_prd({"kind": "spec", "parent_prd": ""}) == "prd-00-main"
        True
    """
    kind = str(entry.get("kind", "spec"))
    raw = entry.get("parent_prd")
    parent = str(raw).strip() if raw is not None else ""
    if kind == "prd":
        if entry.get("id") == "prd-00-main" or not parent:
            return None
        return parent
    if not parent:
        return _DEFAULT_PARENT_PRD
    return parent


def _coerce_list_field(entry: dict[str, Any], key: str) -> list[str]:
    """Return a string list field from a manifest row.

    Args:
        entry (dict[str, Any]): Manifest row.
        key (str): Field name.

    Returns:
        list[str]: Normalised string list.

    Examples:
        >>> _coerce_list_field({"depends_on": ["spec-00-foundation"]}, "depends_on")
        ['spec-00-foundation']
    """
    raw = entry.get(key)
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    return [str(raw).strip()] if str(raw).strip() else []


def _build_about_doc(
    entry: dict[str, Any],
    legacy: dict[str, Any],
    legacy_text: str,
) -> AboutDoc:
    """Construct an :class:`AboutDoc` from manifest + legacy metadata.

    Args:
        entry (dict[str, Any]): Manifest row.
        legacy (dict[str, Any]): Parsed legacy header metadata.
        legacy_text (str): Full legacy markdown (for summary extraction).

    Returns:
        AboutDoc: Frontmatter model prior to extract/generate merge.

    Examples:
        >>> doc = _build_about_doc(
        ...     {
        ...         "id": "spec-17-gateway",
        ...         "kind": "spec",
        ...         "title": "Gateway",
        ...         "status": "done",
        ...         "sources": ["src/sevn/gateway/**"],
        ...         "parent_prd": "prd-01-conversational-experience",
        ...     },
        ...     {"owner": "Alex"},
        ...     "## Purpose\\nTurn spine.\\n",
        ... )
        >>> doc.id == "spec-17-gateway"
        True
    """
    doc_id = str(entry["id"])
    kind = str(entry["kind"])
    title = str(entry.get("title") or doc_id)
    status = str(entry.get("status") or legacy.get("status") or "draft")
    owner = str(legacy.get("owner") or entry.get("owner") or _DEFAULT_OWNER)
    summary = summary_from_legacy(
        legacy_text,
        title=title,
        fallback=str(entry.get("summary") or ""),
    )
    last_updated = datetime.now(tz=UTC).date()
    raw_updated = legacy.get("last_updated")
    if isinstance(raw_updated, str) and raw_updated:
        try:
            last_updated = date.fromisoformat(raw_updated)
        except ValueError:
            last_updated = datetime.now(tz=UTC).date()

    payload: dict[str, Any] = {
        "id": doc_id,
        "kind": kind,
        "title": title,
        "status": status,
        "owner": owner,
        "summary": summary,
        "last_updated": last_updated,
        "sources": _coerce_list_field(entry, "sources"),
        "related": _coerce_list_field(entry, "related"),
    }
    if kind == "spec":
        payload["parent_prd"] = _coerce_parent_prd(entry)
        payload["depends_on"] = _coerce_list_field(entry, "depends_on") or legacy.get(
            "depends_on", []
        )
        payload["build_phase"] = entry.get("build_phase") or legacy.get("build_phase")
    else:
        payload["parent_prd"] = _coerce_parent_prd(entry)
        payload["specs"] = _coerce_list_field(entry, "specs") or legacy.get("specs", [])
        payload["personas"] = _coerce_list_field(entry, "personas")
    return AboutDoc.model_validate(payload)


def migrate_all(
    repo_root: Path,
    *,
    offline: bool = True,
) -> list[str]:
    """Migrate every manifest entry from legacy seed paths to ``about-sevn.bot/``.

    Reads ``about-sevn.bot/_docsys/manifest.toml``, writes frontmatter + offline
    generated bodies under ``about-sevn.bot/{prd,specs}/``, and returns written
    relative paths.

    Args:
        repo_root (Path): Repository root containing seed ``prd/``/``specs/``.
        offline (bool): When ``True``, use deterministic offline body stubs.

    Returns:
        list[str]: Repo-relative paths written during migration.

    Examples:
        >>> migrate_all.__name__
        'migrate_all'
    """
    repo_root = repo_root.resolve()
    entries = load_manifest_entries(repo_root)
    provider = build_provider(ReadmeProviderConfig(offline=offline))
    if not isinstance(provider, OfflineProvider) and offline:
        provider = OfflineProvider()

    written: list[str] = []
    for doc_id in sorted(entries):
        row = entries[doc_id]
        old_path = str(row.get("old_path", "")).strip()
        new_path = str(row.get("new_path", "")).strip()
        if not old_path or not new_path:
            continue
        seed_text = _resolve_seed_path(repo_root, old_path).read_text(encoding="utf-8")
        legacy = parse_legacy_metadata(seed_text)
        doc = _build_about_doc(row, legacy, seed_text)
        body = generate_body(doc, provider)
        merged = doc.model_copy(update=extract_fields(repo_root, doc.model_dump(mode="json")))
        out_path = (repo_root / new_path).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(dump_doc(merged, body), encoding="utf-8")
        written.append(out_path.relative_to(repo_root).as_posix())
        _ = doc_id
    return written


__all__ = [
    "build_path_to_id_map",
    "migrate_all",
    "parse_legacy_metadata",
    "rewrite_markdown_refs",
    "summary_from_legacy",
]
