"""Schema upgrade + foreign import (`specs/22-onboarding.md` §2.3, §4.4-4.5).

Module: sevn.onboarding.migrate
Depends: difflib, json, os, pathlib, typing, sevn.config.defaults, sevn.config.errors

Exports:
    MigrationPlan — redactable import plan for ``--json`` / dry-run.
    describe_schema_upgrade — diff + targets without writing (CLI / dry-run).
    upgrade_schema_inplace — bump ``schema_version`` with backup + atomic write.
    import_foreign_workspace — detect foreign tree and build a plan.
"""

from __future__ import annotations

import difflib
import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Literal, cast

from sevn.config.defaults import SUPPORTED_SCHEMA_VERSIONS
from sevn.config.errors import UnsupportedSchemaVersionError
from sevn.onboarding.validate import validate_workspace_document

SourceKind = Literal["sevn", "legacy_agent_like", "openclaw_like", "unknown"]

# v1 optional SQLite import subset (`specs/22-onboarding.md` §4.5, `specs/03-storage.md`).
# Excludes ``schema_migrations`` (target workspace runs ``apply_migrations`` fresh) and
# gateway/dispatcher/session tables (stale runtime state). LCM + boot-resume snapshots only.
V1_SQLITE_IMPORT_TABLE_KEYS: Final[tuple[str, ...]] = (
    "active_run_snapshots",
    "lcm_conversations",
    "lcm_messages",
    "lcm_summaries",
    "lcm_summary_messages",
    "lcm_summary_parents",
    "lcm_context_items",
    "lcm_large_files",
)

_Transform = Callable[[dict[str, Any]], dict[str, Any]]


def _deep_copy_json_obj(doc: dict[str, Any]) -> dict[str, Any]:
    """Return a JSON-roundtripped deep copy of ``doc``.

    Args:
        doc (dict[str, Any]): Parsed ``sevn.json`` object.

    Returns:
        dict[str, Any]: Independent copy safe for in-place transforms.

    Examples:
        >>> _deep_copy_json_obj({"schema_version": 1, "x": {"y": 1}})["x"]["y"]
        1
    """
    return cast("dict[str, Any]", json.loads(json.dumps(doc)))


def _transform_v1_to_v2(doc: dict[str, Any]) -> dict[str, Any]:
    """Bump ``schema_version`` only (no key renames yet; `specs/22-onboarding.md` §4.4).

    Args:
        doc (dict[str, Any]): v1 workspace document.

    Returns:
        dict[str, Any]: Copy with ``schema_version`` set to ``2``.

    Examples:
        >>> _transform_v1_to_v2({"schema_version": 1})["schema_version"]
        2
    """
    out = _deep_copy_json_obj(doc)
    out["schema_version"] = 2
    return out


_SCHEMA_STEP_TRANSFORMS: dict[tuple[int, int], _Transform] = {
    (1, 2): _transform_v1_to_v2,
}


def _apply_transform_chain(doc: dict[str, Any], *, target_schema_version: int) -> dict[str, Any]:
    """Apply registered one-step transforms until ``schema_version`` reaches ``target``.

    Args:
        doc (dict[str, Any]): Starting document (mutated only via copied intermediates).
        target_schema_version (int): Inclusive upper bound for ``schema_version``.

    Returns:
        dict[str, Any]: Transformed document at ``target_schema_version``.

    Raises:
        UnsupportedSchemaVersionError: When no transform is registered for a step.

    Examples:
        >>> _apply_transform_chain({"schema_version": 1}, target_schema_version=2)[
        ...     "schema_version"
        ... ]
        2
    """
    work = _deep_copy_json_obj(doc)
    while work["schema_version"] < target_schema_version:
        cur = int(work["schema_version"])
        nxt = cur + 1
        step = (cur, nxt)
        fn = _SCHEMA_STEP_TRANSFORMS.get(step)
        if fn is None:
            msg = (
                f"no transform registered for schema_version {cur}→{nxt} "
                f"(`specs/22-onboarding.md` §4.4)"
            )
            raise UnsupportedSchemaVersionError(msg)
        work = fn(work)
    return work


def _stable_json_lines(doc: dict[str, Any]) -> list[str]:
    """Return sorted-key JSON lines (with trailing newline split) for diffing.

    Args:
        doc (dict[str, Any]): Document to serialise.

    Returns:
        list[str]: Lines including line endings where ``splitlines(keepends=True)`` applies.

    Examples:
        >>> lines = _stable_json_lines({"b": 1, "a": 0})
        >>> lines[0].startswith("{")
        True
    """
    text = json.dumps(doc, indent=2, sort_keys=True) + "\n"
    return text.splitlines(keepends=True)


def _unified_diff(before: dict[str, Any], after: dict[str, Any]) -> str:
    """Return a unified diff string between stable JSON serialisations.

    Args:
        before (dict[str, Any]): Document before transforms.
        after (dict[str, Any]): Document after transforms.

    Returns:
        str: Unified diff text (possibly empty when equal).

    Examples:
        >>> "-" in _unified_diff({"a": 1}, {"a": 2})
        True
    """
    a = _stable_json_lines(before)
    b = _stable_json_lines(after)
    return "".join(
        difflib.unified_diff(
            a,
            b,
            fromfile="sevn.json (before)",
            tofile="sevn.json (after)",
            lineterm="",
        )
    )


def _atomic_write_sevn_json_with_optional_backup(
    sevn_json_path: Path,
    new_doc: dict[str, Any],
    *,
    backup_previous: bool,
) -> Path | None:
    """Write ``new_doc`` to ``sevn.json`` via temp + fsync; optionally move prior file to ``sevn.json.vN``.

    Args:
        sevn_json_path (Path): Target ``sevn.json`` path.
        new_doc (dict[str, Any]): Serialised workspace document.
        backup_previous (bool): When True and a file exists, rename it aside first.

    Returns:
        Path | None: Backup path when a prior ``sevn.json`` was moved aside, else ``None``.

    Raises:
        OSError: Disk or rename failures.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> td = Path(tempfile.mkdtemp())
        >>> p = td / "sevn.json"
        >>> _ = p.write_text('{"schema_version": 1}\\n', encoding="utf-8")
        >>> bak = _atomic_write_sevn_json_with_optional_backup(
        ...     p, {"schema_version": 2}, backup_previous=True
        ... )
        >>> bak is not None and p.read_text(encoding="utf-8").strip().startswith("{")
        True
    """
    sevn_json_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = sevn_json_path.with_suffix(".json.tmp")
    payload = json.dumps(new_doc, indent=2, sort_keys=True) + "\n"
    tmp.write_text(payload, encoding="utf-8")
    tmp_fd = os.open(str(tmp), os.O_RDWR)
    try:
        os.fsync(tmp_fd)
    finally:
        os.close(tmp_fd)

    backup_written: Path | None = None
    if sevn_json_path.is_file() and backup_previous:
        try:
            old_doc = json.loads(sevn_json_path.read_text(encoding="utf-8"))
            old_schema = int(old_doc.get("schema_version", 1))
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
            old_schema = 1
        backup = sevn_json_path.parent / f"sevn.json.v{old_schema}"
        target_backup = backup
        suffix = 0
        while target_backup.is_file():
            suffix += 1
            target_backup = sevn_json_path.parent / f"sevn.json.v{old_schema}.{suffix}"
        os.replace(sevn_json_path, target_backup)
        backup_written = target_backup

    os.replace(tmp, sevn_json_path)
    return backup_written


@dataclass
class MigrationPlan:
    """Structured import plan (paths only — no secret values, `specs/22-onboarding.md` §4.5)."""

    source_kind: SourceKind
    source_root: Path
    narrative_paths: list[str] = field(default_factory=list)
    skills_buckets: dict[str, list[str]] = field(
        default_factory=lambda: {"core": [], "user": [], "generated": []}
    )
    config_merge_hints: list[str] = field(default_factory=list)
    sqlite_subset_keys: list[str] = field(default_factory=list)
    dry_run: bool = False

    def to_json_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dict with redaction-safe strings only.

        Returns:
            dict[str, Any]: Summary fields safe for ``--json`` output.

        Examples:
            >>> from pathlib import Path
            >>> MigrationPlan(source_kind="unknown", source_root=Path("/tmp")).to_json_dict()[
            ...     "source_kind"
            ... ]
            'unknown'
        """
        return {
            "source_kind": self.source_kind,
            "source_root": str(self.source_root),
            "narrative_paths": list(self.narrative_paths),
            "skills_buckets": {k: list(v) for k, v in self.skills_buckets.items()},
            "config_merge_hints": list(self.config_merge_hints),
            "sqlite_subset_keys": list(self.sqlite_subset_keys),
            "dry_run": self.dry_run,
        }


def _detect_source(root: Path) -> SourceKind:
    """Infer workspace flavour from on-disk markers.

    Args:
        root (Path): Workspace root directory.

    Returns:
        SourceKind: Detected family label.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> td = Path(tempfile.mkdtemp())
        >>> _detect_source(td)
        'unknown'
    """
    sevn_json = root / "sevn.json"
    if sevn_json.is_file():
        return "sevn"
    skills = list(root.glob("skills/**/SKILL.md"))
    if skills:
        if (root / ".hermes").exists() or "hermes" in root.name.lower():
            return "legacy_agent_like"
        return "openclaw_like"
    return "unknown"


def import_foreign_workspace(source_root: Path, *, dry_run: bool = False) -> MigrationPlan:
    """Build a ``MigrationPlan`` for a foreign workspace tree (v1 heuristic).

    Args:
        source_root (Path): Root of the foreign checkout.
        dry_run (bool): When True, plan only.

    Returns:
        MigrationPlan: Candidate operations (no filesystem mutations here).

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> td = Path(tempfile.mkdtemp())
        >>> p = import_foreign_workspace(td)
        >>> p.source_root == td.resolve()
        True
    """
    root = source_root.resolve()
    kind = _detect_source(root)
    narratives = [
        "MEMORY.md",
        "SOUL.md",
        "USER.md",
        "TOOLS.md",
        "IDENTITY.md",
        "AGENTS.md",
        "sevn.bot.md",
    ]
    found = [n for n in narratives if (root / n).is_file()]
    buckets: dict[str, list[str]] = {"core": [], "user": [], "generated": []}
    for p in root.glob("skills/*/*"):
        if p.is_file() and p.name == "SKILL.md":
            rel = p.relative_to(root)
            parts = rel.parts
            if len(parts) >= 2:
                bucket = parts[1]
                if bucket in buckets:
                    buckets[bucket].append(str(rel))
    hints = ["merge providers.tier_default with operator review", "never bulk-copy secrets"]
    sqlite_keys: list[str] = list(V1_SQLITE_IMPORT_TABLE_KEYS) if kind == "sevn" else []
    return MigrationPlan(
        source_kind=kind,
        source_root=root,
        narrative_paths=[str(root / n) for n in found],
        skills_buckets=buckets,
        config_merge_hints=hints,
        sqlite_subset_keys=sqlite_keys,
        dry_run=dry_run,
    )


def describe_schema_upgrade(
    workspace_dir: Path,
    *,
    target_schema_version: int | None = None,
) -> dict[str, Any]:
    """Describe an in-place schema bump without mutating disk (`specs/22-onboarding.md` §4.4).

    Args:
        workspace_dir (Path): Directory holding ``sevn.json``.
        target_schema_version (int | None): Defaults to ``max(SUPPORTED_SCHEMA_VERSIONS)``.

    Returns:
        dict[str, Any]: Keys ``changed`` (bool), ``current``, ``target``, ``diff`` (str),
        ``detail`` (str). When ``changed`` is False, ``diff`` is empty.

    Raises:
        FileNotFoundError: When ``sevn.json`` is missing.
        UnsupportedSchemaVersionError: Unknown current version or blocked upgrade path.
        ValueError: When ``sevn.json`` is not a JSON object.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> td = Path(tempfile.mkdtemp())
        >>> _ = (td / "sevn.json").write_text(
        ...     '{"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        ...     encoding="utf-8",
        ... )
        >>> out = describe_schema_upgrade(td)
        >>> out["changed"] in (True, False)
        True
    """
    path = workspace_dir / "sevn.json"
    if not path.is_file():
        msg = f"missing {path}"
        raise FileNotFoundError(msg)
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        msg = "sevn.json must be an object"
        raise ValueError(msg)
    current = int(doc.get("schema_version", 0))
    if current not in SUPPORTED_SCHEMA_VERSIONS:
        raise UnsupportedSchemaVersionError(f"unsupported schema_version {current}")
    target = (
        target_schema_version
        if target_schema_version is not None
        else max(SUPPORTED_SCHEMA_VERSIONS)
    )
    if current > target:
        raise UnsupportedSchemaVersionError(
            f"schema_version {current} exceeds binary target {target}"
        )
    if current == target:
        return {
            "changed": False,
            "current": current,
            "target": target,
            "diff": "",
            "detail": "already at target schema_version",
        }
    new_doc = _apply_transform_chain(doc, target_schema_version=target)
    validate_workspace_document(new_doc)
    diff = _unified_diff(doc, new_doc)
    return {
        "changed": True,
        "current": current,
        "target": target,
        "diff": diff,
        "detail": f"schema_version {current}→{target}",
    }


def upgrade_schema_inplace(
    workspace_dir: Path,
    *,
    target_schema_version: int | None = None,
    consent: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Upgrade ``sevn.json`` ``schema_version`` in place when transforms exist.

    Args:
        workspace_dir (Path): Directory holding ``sevn.json``.
        target_schema_version (int | None): Defaults to ``max(SUPPORTED_SCHEMA_VERSIONS)``.
        consent (bool): Operator consent for mutating writes (non-interactive callers pass True).
        dry_run (bool): When True, no files are written.

    Returns:
        dict[str, Any]: Summary with keys ``changed``, ``backup`` (path str or null), ``diff``,
        ``detail``.

    Raises:
        FileNotFoundError: When ``sevn.json`` is missing.
        UnsupportedSchemaVersionError: When the file references an unknown schema or no transform.
        RuntimeError: When ``consent`` is False on a mutating path.
        pydantic.ValidationError: When the post-transform document fails validation.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> td = Path(tempfile.mkdtemp())
        >>> _ = (td / "sevn.json").write_text(
        ...     '{"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}',
        ...     encoding="utf-8",
        ... )
        >>> upgrade_schema_inplace(td, dry_run=True)["changed"]
        True
    """
    preview = describe_schema_upgrade(workspace_dir, target_schema_version=target_schema_version)
    if not preview["changed"]:
        return {
            "changed": False,
            "backup": None,
            "diff": "",
            "detail": preview["detail"],
        }
    if dry_run:
        return {
            "changed": True,
            "backup": None,
            "diff": preview["diff"],
            "detail": "dry-run only — no files written",
        }
    if not consent:
        msg = "upgrade_schema_inplace requires consent=True or dry_run=True"
        raise RuntimeError(msg)

    path = workspace_dir / "sevn.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        msg = "sevn.json must be an object"
        raise ValueError(msg)
    target = int(preview["target"])
    new_doc = _apply_transform_chain(doc, target_schema_version=target)
    validate_workspace_document(new_doc)
    backup_path = _atomic_write_sevn_json_with_optional_backup(
        path,
        new_doc,
        backup_previous=True,
    )
    return {
        "changed": True,
        "backup": str(backup_path) if backup_path is not None else None,
        "diff": preview["diff"],
        "detail": preview["detail"],
    }
