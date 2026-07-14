"""Deterministic per-file validity scoring for spec-kit-wave docs (D5).

Exports:
    SCORE_THRESHOLD — minimum total score for ``done``/``ready`` docs.
    ScoreResult — per-file score breakdown.
    load_score_weights — read ``[score]`` weights from ``*-rules.toml``.
    score_doc — compute weighted 0-100 score for one markdown file.
    rollup_scores — aggregate scores across a folder.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from skw.prd_validate import H2_HEADING_RE, load_prd_rules, parse_frontmatter

SCORE_THRESHOLD = 80

SCORE_COMPONENTS: tuple[str, ...] = (
    "frontmatter_completeness",
    "required_sections",
    "no_scaffold_phrase",
    "status_honesty",
    "interfaces_sources_resolve",
    "link_id_hygiene",
)

_DEFAULT_SCORE_WEIGHTS: dict[str, int] = {
    "frontmatter_completeness": 20,
    "required_sections": 15,
    "no_scaffold_phrase": 25,
    "status_honesty": 15,
    "interfaces_sources_resolve": 15,
    "link_id_hygiene": 10,
}

_TERMINAL_STATUSES = frozenset({"done", "ready"})


def _default_kit_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


@dataclass(frozen=True)
class ScoreResult:
    """Weighted validity score for one markdown doc."""

    path: str
    total: int
    components: dict[str, int]


def load_score_weights(kind: str, *, kit_root: Path | None = None) -> dict[str, int]:
    """Load ``[score]`` component weights for ``kind`` (``spec`` or ``prd``)."""
    root = kit_root or _default_kit_root()
    if kind == "spec":
        from skw.spec_validate import load_spec_rules

        rules = load_spec_rules(root)
    elif kind == "prd":
        rules = load_prd_rules(root)
    else:
        msg = f"unsupported kind: {kind!r} (expected 'spec' or 'prd')"
        raise ValueError(msg)
    raw = rules.get("score", _DEFAULT_SCORE_WEIGHTS)
    weights = {key: int(raw[key]) for key in SCORE_COMPONENTS}
    return weights


def _h2_order(body: str) -> list[str]:
    return [match.group(1).strip() for match in H2_HEADING_RE.finditer(body)]


def _parse_doc(path: Path, kind: str) -> tuple[dict[str, Any], str, str | None]:
    text = path.read_text(encoding="utf-8")
    if kind == "spec":
        from skw.spec_validate import parse_spec_frontmatter

        return parse_spec_frontmatter(text)
    return parse_frontmatter(text)


def _score_frontmatter_completeness(
    meta: dict[str, Any], rules: dict[str, Any], weight: int
) -> int:
    required = rules["frontmatter"]["required"]
    for key in required:
        if key not in meta:
            return 0
    if rules["frontmatter"].get("kind") == "spec":
        if meta.get("sources") in (None, []):
            return 0
        if meta.get("fingerprint") in (None, ""):
            return 0
    return weight


def _score_required_sections(body: str, rules: dict[str, Any], weight: int) -> int:
    required: list[str] = rules["sections"]["required"]
    found = _h2_order(body)
    if not found:
        return 0
    req_index = 0
    for heading in found:
        if req_index >= len(required):
            break
        if heading.lower() == required[req_index].lower():
            req_index += 1
    return weight if req_index >= len(required) else 0


def _score_no_scaffold_phrase(body: str, rules: dict[str, Any], weight: int) -> int:
    forbidden = rules["scaffold"]["forbidden_when_ready"]
    for phrase in forbidden:
        if phrase in body:
            return 0
    return weight


def _score_status_honesty(
    body: str, meta: dict[str, Any], rules: dict[str, Any], weight: int
) -> int:
    status = meta.get("status")
    if status not in _TERMINAL_STATUSES:
        return weight
    forbidden = rules["scaffold"]["forbidden_when_ready"]
    for phrase in forbidden:
        if phrase in body:
            return 0
    return weight


def _glob_matches_repo(repo_root: Path, pattern: str) -> bool:
    if pattern.endswith("/**"):
        base = pattern[:-3]
        target = repo_root / base
        return target.is_dir() or target.is_file()
    matches = list(repo_root.glob(pattern))
    return bool(matches)


def _score_interfaces_sources_resolve(
    meta: dict[str, Any],
    *,
    kind: str,
    repo_root: Path,
    rules: dict[str, Any],
    weight: int,
) -> int:
    if kind == "spec":
        from skw.spec_validate import _symbol_exists

        sources = meta.get("sources")
        if sources in (None, []):
            return 0
        forbidden = set(rules["frontmatter"].get("forbidden_whole_repo_sources", []))
        if isinstance(sources, list):
            for item in sources:
                if not isinstance(item, str):
                    return 0
                if item in forbidden:
                    return 0
                if not _glob_matches_repo(repo_root, item):
                    return 0
        interfaces = meta.get("interfaces") or []
        if isinstance(interfaces, list):
            for row in interfaces:
                if not isinstance(row, dict):
                    return 0
                file_ref = row.get("file")
                symbol = row.get("symbol") or row.get("name")
                if not isinstance(file_ref, str) or not isinstance(symbol, str):
                    return 0
                resolved = repo_root / file_ref
                if not resolved.is_file() or not _symbol_exists(resolved, symbol):
                    return 0
        return weight

    sources = meta.get("sources")
    if sources in (None, []):
        return weight
    if isinstance(sources, list):
        for item in sources:
            if not isinstance(item, str):
                return 0
            if not _glob_matches_repo(repo_root, item):
                return 0
    return weight


def _score_link_id_hygiene(
    meta: dict[str, Any],
    *,
    path: Path,
    siblings: list[Path] | None,
    rules: dict[str, Any],
    kind: str,
    weight: int,
) -> int:
    fm = rules["frontmatter"]
    doc_id = meta.get("id")
    if not isinstance(doc_id, str) or not re.fullmatch(fm["id_pattern"], doc_id):
        return 0
    if kind == "spec" and siblings:
        from skw.spec_validate import _numeric_spec_id

        numeric = _numeric_spec_id(doc_id)
        if numeric:
            for sibling in siblings:
                if sibling == path or not sibling.is_file():
                    continue
                sib_meta, _, sib_err = _parse_doc(sibling, kind)
                if sib_err:
                    continue
                sib_id = sib_meta.get("id")
                if isinstance(sib_id, str) and _numeric_spec_id(sib_id) == numeric:
                    return 0
    return weight


def score_doc(
    path: Path,
    kind: str,
    *,
    repo_root: Path,
    siblings: list[Path] | None = None,
    kit_root: Path | None = None,
) -> ScoreResult:
    """Compute a deterministic 0-100 validity score for one doc file."""
    root = kit_root or _default_kit_root()
    if kind == "spec":
        from skw.spec_validate import load_spec_rules

        rules = load_spec_rules(root)
    elif kind == "prd":
        rules = load_prd_rules(root)
    else:
        msg = f"unsupported kind: {kind!r} (expected 'spec' or 'prd')"
        raise ValueError(msg)

    weights = load_score_weights(kind, kit_root=root)
    meta, body, fm_err = _parse_doc(path, kind)
    if fm_err:
        return ScoreResult(path=str(path), total=0, components={key: 0 for key in SCORE_COMPONENTS})

    components = {
        "frontmatter_completeness": _score_frontmatter_completeness(
            meta, rules, weights["frontmatter_completeness"]
        ),
        "required_sections": _score_required_sections(body, rules, weights["required_sections"]),
        "no_scaffold_phrase": _score_no_scaffold_phrase(body, rules, weights["no_scaffold_phrase"]),
        "status_honesty": _score_status_honesty(body, meta, rules, weights["status_honesty"]),
        "interfaces_sources_resolve": _score_interfaces_sources_resolve(
            meta,
            kind=kind,
            repo_root=repo_root,
            rules=rules,
            weight=weights["interfaces_sources_resolve"],
        ),
        "link_id_hygiene": _score_link_id_hygiene(
            meta,
            path=path,
            siblings=siblings,
            rules=rules,
            kind=kind,
            weight=weights["link_id_hygiene"],
        ),
    }
    total = sum(components.values())
    return ScoreResult(path=str(path), total=total, components=components)


def rollup_scores(results: list[ScoreResult]) -> dict[str, Any]:
    """Aggregate per-file scores into folder-level rollup statistics."""
    if not results:
        return {"file_count": 0, "average_total": 0, "below_threshold": []}
    below = [result.path for result in results if result.total < SCORE_THRESHOLD]
    average = round(sum(result.total for result in results) / len(results))
    return {
        "file_count": len(results),
        "average_total": average,
        "below_threshold": below,
    }
