"""Context pack builder for self-improve patch author (`specs/33-self-improvement.md` §3.5).

Module: sevn.self_improve.proposer.context_loader
Depends: hashlib, json, pathlib, sevn.self_improve.spec_kit_stage

Exports:
    build_context_pack_payload — assemble v2 context pack dict.
    write_context_pack — persist ``context_pack.json`` under a job bundle.
    load_context_pack — read context pack from a job bundle.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path  # noqa: TC003 — runtime job bundle paths
from typing import TYPE_CHECKING, Any

from sevn.self_improve.spec_kit_stage import improve_spec_kit_dir

if TYPE_CHECKING:
    from sevn.workspace.layout import WorkspaceLayout

CONTEXT_PACK_SCHEMA_VERSION = 2
_SKILL_EXCERPT_MAX_CHARS = 2000
_MAX_SKILL_FILES = 5
_MAX_TURN_EXCERPTS = 5


def _triager_prompt_hash_placeholder() -> str:
    """Return a stable placeholder hash until triager prompt versioning lands.

    Returns:
        str: ``sha256:`` prefixed digest of the placeholder label.

    Examples:
        >>> _triager_prompt_hash_placeholder().startswith("sha256:")
        True
    """
    digest = hashlib.sha256(b"triager_prompt_version:placeholder").hexdigest()
    return f"sha256:{digest}"


def _turn_excerpts(shortlist: dict[str, Any]) -> list[dict[str, str]]:
    """Summarise shortlist candidates as turn excerpt rows.

    Args:
        shortlist (dict[str, Any]): Parsed ``shortlist.json`` body.

    Returns:
        list[dict[str, str]]: Up to five excerpt dicts with ``turn_id`` and ``bucket``.

    Examples:
        >>> _turn_excerpts({"candidates": [{"turn_id": "t1", "bucket": "explicit_feedback"}]})
        [{'turn_id': 't1', 'bucket': 'explicit_feedback'}]
    """
    raw = shortlist.get("candidates")
    if not isinstance(raw, list):
        return []
    excerpts: list[dict[str, str]] = []
    for row in raw[:_MAX_TURN_EXCERPTS]:
        if not isinstance(row, dict):
            continue
        turn_id = row.get("turn_id")
        if not isinstance(turn_id, str) or not turn_id.strip():
            continue
        bucket = row.get("bucket")
        excerpt: dict[str, str] = {"turn_id": turn_id}
        if isinstance(bucket, str) and bucket.strip():
            excerpt["bucket"] = bucket
        excerpts.append(excerpt)
    return excerpts


def _skill_excerpts(content_root: Path) -> list[dict[str, str]]:
    """Collect short SKILL.md excerpts from ``workspace/skills/**``.

    Args:
        content_root (Path): Workspace content root.

    Returns:
        list[dict[str, str]]: ``path`` + ``excerpt`` rows for prompt context.

    Examples:
        >>> _skill_excerpts(Path("/nonexistent")) == []
        True
    """
    skills_root = content_root / "workspace" / "skills"
    if not skills_root.is_dir():
        return []
    rows: list[dict[str, str]] = []
    for skill_path in sorted(skills_root.rglob("SKILL.md"))[:_MAX_SKILL_FILES]:
        try:
            rel = skill_path.relative_to(content_root).as_posix()
        except ValueError:
            rel = skill_path.as_posix()
        text = skill_path.read_text(encoding="utf-8", errors="replace")
        rows.append({"path": rel, "excerpt": text[:_SKILL_EXCERPT_MAX_CHARS]})
    return rows


def build_context_pack_payload(
    *,
    job_id: str,
    shortlist: dict[str, Any],
    layout: WorkspaceLayout | None = None,
) -> dict[str, Any]:
    """Assemble schema v2 ``context_pack.json`` payload.

    Args:
        job_id (str): Improve job id.
        shortlist (dict[str, Any]): Parsed ``shortlist.json`` body.
        layout (WorkspaceLayout | None): Optional layout for skill excerpts.

    Returns:
        dict[str, Any]: JSON-serialisable context pack.

    Examples:
        >>> payload = build_context_pack_payload(job_id="j1", shortlist={"candidates": []})
        >>> payload["schema_version"] == 2
        True
    """
    skill_rows: list[dict[str, str]] = []
    if layout is not None:
        skill_rows = _skill_excerpts(layout.content_root)
    return {
        "schema_version": CONTEXT_PACK_SCHEMA_VERSION,
        "job_id": job_id,
        "shortlist": shortlist,
        "turn_excerpts": _turn_excerpts(shortlist),
        "triager_prompt_hash": _triager_prompt_hash_placeholder(),
        "skill_excerpts": skill_rows,
    }


def write_context_pack(
    job_bundle: Path,
    *,
    job_id: str,
    shortlist: dict[str, Any],
    layout: WorkspaceLayout | None = None,
) -> Path:
    """Write ``context_pack.json`` beside the shortlist for spec-kit / patch author.

    Args:
        job_bundle (Path): Per-job artefact directory.
        job_id (str): Improve job id.
        shortlist (dict[str, Any]): Parsed ``shortlist.json`` body.
        layout (WorkspaceLayout | None): Optional layout for skill excerpts.

    Returns:
        Path: Written ``context_pack.json`` path.

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> with tempfile.TemporaryDirectory() as td:
        ...     bundle = Path(td)
        ...     path = write_context_pack(
        ...         bundle,
        ...         job_id="j1",
        ...         shortlist={"candidates": [], "schema_version": 1},
        ...     )
        ...     path.name == "context_pack.json"
        True
    """
    job_bundle.mkdir(parents=True, exist_ok=True)
    pack_path = job_bundle / "context_pack.json"
    payload = build_context_pack_payload(job_id=job_id, shortlist=shortlist, layout=layout)
    pack_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    spec_dir = improve_spec_kit_dir(job_bundle)
    spec_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / "context_pack.json").write_text(
        pack_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return pack_path


def load_context_pack(job_bundle: Path) -> dict[str, Any]:
    """Load ``context_pack.json`` when present, else return an empty v2 shell.

    Args:
        job_bundle (Path): Per-job artefact directory.

    Returns:
        dict[str, Any]: Parsed context pack or minimal fallback dict.

    Examples:
        >>> load_context_pack(Path("/nonexistent")).get("schema_version") == 2
        True
    """
    pack_path = job_bundle / "context_pack.json"
    if not pack_path.is_file():
        return {
            "schema_version": CONTEXT_PACK_SCHEMA_VERSION,
            "turn_excerpts": [],
            "skill_excerpts": [],
        }
    loaded = json.loads(pack_path.read_text(encoding="utf-8"))
    if isinstance(loaded, dict):
        return loaded
    return {
        "schema_version": CONTEXT_PACK_SCHEMA_VERSION,
        "turn_excerpts": [],
        "skill_excerpts": [],
    }


__all__ = [
    "CONTEXT_PACK_SCHEMA_VERSION",
    "build_context_pack_payload",
    "load_context_pack",
    "write_context_pack",
]
