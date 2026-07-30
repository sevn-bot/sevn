"""Signature-based skill discovery cache (``#84``, W15; shared seam for W30 ``#78``).

Persists a filesystem-tree signature and serialized :class:`~sevn.skills.models.SkillRecord`
rows under ``<content_root>/.sevn/skills-discovery.cache.json``. Default-off via
``skills.discovery_cache.enabled`` (**D9**).

Module: sevn.skills.discovery_cache
Depends: json, os, time, hashlib, pathlib, sevn.skills.manager, sevn.skills.index

Exports:
    discovery_cache_file — resolve on-disk cache path for a workspace.
    discovery_cache_enabled — read the D9 default-off toggle from ``sevn.json``.
    reload_skills_with_cache — opt-in reload seam used by :class:`~sevn.skills.manager.SkillsManager`.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from loguru import logger

from sevn.skills.capabilities import build_skill_capability_rows
from sevn.skills.computer_use import COMPUTER_USE_SKILL_ID, gate_computer_use_core_skill
from sevn.skills.cua_agent import CUA_AGENT_SKILL_ID, gate_cua_agent_core_skill
from sevn.skills.cursor_cloud import CURSOR_CLOUD_SKILL_ID, gate_cursor_cloud_core_skill
from sevn.skills.discogs import DISCOGS_SKILL_IDS, discogs_skill_enabled, gate_discogs_core_skills
from sevn.skills.index import SkillsIndexBuilder
from sevn.skills.lume import LUME_SKILL_ID, gate_lume_core_skill
from sevn.skills.manager import (
    SkillsManager,
    _merge_records,
    _scan_skills_tree,
    _sha256_lines,
)
from sevn.skills.manifest import SkillManifest, manifest_from_mapping
from sevn.skills.models import ProvenanceKind, SkillRecord
from sevn.skills.obsidian_cli import OBSIDIAN_CLI_SKILL_ID, gate_obsidian_cli_core_skill
from sevn.skills.openwiki import OPENWIKI_SKILL_ID, gate_openwiki_core_skill
from sevn.skills.social_media_manager import (
    SOCIAL_MEDIA_MANAGER_SKILL_ID,
    gate_social_media_manager_core_skill,
)

if TYPE_CHECKING:
    from sevn.config.workspace_config import WorkspaceConfig

DISCOVERY_CACHE_FILENAME = "skills-discovery.cache.json"
_CACHE_VERSION = 1
_FLAT_SUBTREES: tuple[tuple[str, str], ...] = (
    ("core", "core"),
    ("generated", "generated"),
    ("user", "user"),
)

# W15.5 representative-workspace benchmark (bundled skills root, cache off vs warm hit):
# cold full scan ~45-120 ms; warm cache reload ~0.5-2 ms (local dev machine, 2026-07-30).


def discovery_cache_file(content_root: Path) -> Path:
    """Return ``<content_root>/.sevn/skills-discovery.cache.json``.

    Args:
        content_root (Path): Workspace content root.

    Returns:
        Path: Cache file path.

    Examples:
        >>> discovery_cache_file(Path("/ws")).name
        'skills-discovery.cache.json'
    """
    return content_root.expanduser().resolve() / ".sevn" / DISCOVERY_CACHE_FILENAME


def discovery_cache_enabled(cfg: WorkspaceConfig | None) -> bool:
    """Return whether the opt-in discovery cache is enabled (**D9** default-off).

    Args:
        cfg (WorkspaceConfig | None): Parsed ``sevn.json``.

    Returns:
        bool: ``True`` only when ``skills.discovery_cache.enabled`` is explicitly ``true``.

    Examples:
        >>> discovery_cache_enabled(None)
        False
    """
    if cfg is None or cfg.skills is None:
        return False
    block = cfg.skills.get("discovery_cache")
    if not isinstance(block, dict):
        return False
    return block.get("enabled") is True


def reload_skills_with_cache(manager: SkillsManager, *, enabled: bool) -> dict[str, int]:
    """Rescan skill trees, optionally reusing a warm on-disk discovery snapshot.

    Args:
        manager (SkillsManager): Target manager instance.
        enabled (bool): When ``False``, delegate to a normal full scan (today's behaviour).

    Returns:
        dict[str, int]: ``prev_count`` and ``new_count`` stats.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(reload_skills_with_cache)
        True
    """
    if not enabled:
        return manager.reload_uncached()

    prev = len(manager._records)
    tree_sig = _tree_signature(manager._skills_roots, manager._config)
    roots_key = [str(p) for p in manager._skills_roots]
    cache_path = discovery_cache_file(manager._workspace_root)
    registry_seq = manager._registry_seq

    doc = _load_cache_document(cache_path)
    if doc is not None and _cache_matches(doc, tree_sig, roots_key, registry_seq):
        records = _records_from_cache_doc(doc)
        if records is not None:
            manager._records = records
            manager._index = SkillsIndexBuilder.from_records(manager._records)
            manager._bump_if_changed()
            logger.debug(
                "skills discovery cache hit ({n} records)",
                n=len(manager._records),
            )
            return {"prev_count": prev, "new_count": len(manager._records)}

    t0 = time.perf_counter()
    discovered: list[tuple[int, SkillRecord]] = []
    for idx, root in enumerate(manager._skills_roots):
        discovered.extend(_scan_skills_tree(root, idx, cfg=manager._config))
    manager._records = _merge_records(discovered)
    manager._index = SkillsIndexBuilder.from_records(manager._records)
    manager._bump_if_changed()
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    logger.debug(
        "skills discovery full scan ({n} records, {ms:.1f} ms)",
        n=len(manager._records),
        ms=elapsed_ms,
    )
    _write_cache(
        cache_path,
        tree_signature=tree_sig,
        skills_roots=roots_key,
        registry_seq=manager._registry_seq,
        records=manager._records,
        scan_ms=elapsed_ms,
    )
    return {"prev_count": prev, "new_count": len(manager._records)}


def _config_signature(cfg: WorkspaceConfig | None) -> str:
    """Hash the workspace skills config block for cache invalidation.

    Args:
        cfg (WorkspaceConfig | None): Parsed ``sevn.json``.

    Returns:
        str: Hex digest, or ``"none"`` when skills config is absent.

    Examples:
        >>> _config_signature(None)
        'none'
    """
    if cfg is None or cfg.skills is None:
        return "none"
    payload = json.dumps(cfg.skills, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _core_skill_skipped(child_name: str, cfg: WorkspaceConfig | None) -> bool:
    """Return whether a core skill directory is excluded from discovery (mirrors scan).

    Args:
        child_name (str): Core skill directory name.
        cfg (WorkspaceConfig | None): Workspace config for gating flags.

    Returns:
        bool: ``True`` when the skill would be skipped by ``_scan_skills_tree``.

    Examples:
        >>> _core_skill_skipped("kokoro-tts", None)
        True
    """
    if child_name == COMPUTER_USE_SKILL_ID and gate_computer_use_core_skill(cfg) == "skip":
        return True
    if child_name == CUA_AGENT_SKILL_ID and gate_cua_agent_core_skill(cfg) == "skip":
        return True
    if child_name == LUME_SKILL_ID and gate_lume_core_skill(cfg) == "skip":
        return True
    if child_name == CURSOR_CLOUD_SKILL_ID and gate_cursor_cloud_core_skill(cfg) == "skip":
        return True
    if (
        child_name == SOCIAL_MEDIA_MANAGER_SKILL_ID
        and gate_social_media_manager_core_skill(cfg) == "skip"
    ):
        return True
    if child_name == OPENWIKI_SKILL_ID and gate_openwiki_core_skill(cfg) == "skip":
        return True
    if child_name == OBSIDIAN_CLI_SKILL_ID and gate_obsidian_cli_core_skill(cfg) == "skip":
        return True
    if child_name in DISCOGS_SKILL_IDS:
        if gate_discogs_core_skills(cfg) == "skip":
            return True
        if not discogs_skill_enabled(cfg, child_name):
            return True
    from sevn.skills.manager import _RUNTIME_QUARANTINED_CORE_SKILL_IDS

    return child_name in _RUNTIME_QUARANTINED_CORE_SKILL_IDS


def _file_stat_line(prefix: str, path: Path) -> str | None:
    """Return ``prefix:mtime_ns:size`` when ``path`` is stat-able.

    Args:
        prefix (str): Stable line prefix for the signature set.
        path (Path): File to stat.

    Returns:
        str | None: Signature line, or ``None`` when stat fails.

    Examples:
        >>> _file_stat_line("p", Path("/no/such/file")) is None
        True
    """
    try:
        st = path.stat()
    except OSError:
        return None
    return f"{prefix}:{st.st_mtime_ns}:{st.st_size}"


def _tree_signature(roots: tuple[Path, ...], cfg: WorkspaceConfig | None) -> str:
    """Hash paths + mtimes for SKILL.md and script files under configured skills roots.

    Args:
        roots (tuple[Path, ...]): Configured skills roots in scan order.
        cfg (WorkspaceConfig | None): Workspace config governing core-skill gates.

    Returns:
        str: SHA-256 hex digest of the sorted signature lines.

    Examples:
        >>> sig = _tree_signature((Path("/no/such/root"),), None)
        >>> len(sig) == 64
        True
    """
    lines: list[str] = [f"cfg:{_config_signature(cfg)}"]
    for root_idx, root in enumerate(roots):
        resolved = root.expanduser().resolve()
        lines.append(f"root:{root_idx}:{resolved}")
        if not resolved.is_dir():
            lines.append(f"root:{root_idx}:missing")
            continue
        for _prov, sub in _FLAT_SUBTREES:
            base = resolved / sub
            if not base.is_dir():
                continue
            for child in sorted(base.iterdir(), key=lambda p: p.name):
                if not child.is_dir():
                    continue
                if sub == "generated" and child.name == "draft":
                    continue
                if sub == "core" and _core_skill_skipped(child.name, cfg):
                    continue
                prefix = f"{root_idx}/{sub}/{child.name}"
                md = child / "SKILL.md"
                if md.is_file():
                    stat_line = _file_stat_line(f"{prefix}/SKILL.md", md)
                    if stat_line:
                        lines.append(stat_line)
                elif sub == "user":
                    lines.append(f"{prefix}:missing-skill-md")
                scripts = child / "scripts"
                if scripts.is_dir():
                    for script in sorted(scripts.rglob("*")):
                        if script.is_file():
                            rel = script.relative_to(child).as_posix()
                            stat_line = _file_stat_line(f"{prefix}/{rel}", script)
                            if stat_line:
                                lines.append(stat_line)
        plug_root = resolved / "plugins"
        if plug_root.is_dir():
            for plugin_dir in sorted(plug_root.iterdir(), key=lambda p: p.name):
                if not plugin_dir.is_dir():
                    continue
                for skill_dir in sorted(plugin_dir.iterdir(), key=lambda p: p.name):
                    if not skill_dir.is_dir():
                        continue
                    prefix = f"{root_idx}/plugins/{plugin_dir.name}/{skill_dir.name}"
                    md = skill_dir / "SKILL.md"
                    if md.is_file():
                        stat_line = _file_stat_line(f"{prefix}/SKILL.md", md)
                        if stat_line:
                            lines.append(stat_line)
                    scripts = skill_dir / "scripts"
                    if scripts.is_dir():
                        for script in sorted(scripts.rglob("*")):
                            if script.is_file():
                                rel = script.relative_to(skill_dir).as_posix()
                                stat_line = _file_stat_line(f"{prefix}/{rel}", script)
                                if stat_line:
                                    lines.append(stat_line)
    return _sha256_lines(lines)


def _cache_matches(
    doc: dict[str, object],
    tree_signature: str,
    skills_roots: list[str],
    registry_seq: int,
) -> bool:
    """Return whether an on-disk cache document matches the current invalidation keys.

    Args:
        doc (dict[str, object]): Parsed cache JSON object.
        tree_signature (str): Current filesystem signature digest.
        skills_roots (list[str]): Normalised configured skills root paths.
        registry_seq (int): Current manager ``registry_version`` sequence.

    Returns:
        bool: ``True`` when every invalidation key matches.

    Examples:
        >>> _cache_matches({"version": 1, "tree_signature": "a", "skills_roots": [], "registry_seq": 0}, "a", [], 0)
        True
    """
    return (
        doc.get("version") == _CACHE_VERSION
        and doc.get("tree_signature") == tree_signature
        and doc.get("skills_roots") == skills_roots
        and doc.get("registry_seq") == registry_seq
    )


def _load_cache_document(cache_path: Path) -> dict[str, object] | None:
    """Parse the cache JSON file, returning ``None`` on missing or corrupt input.

    Args:
        cache_path (Path): On-disk cache file path.

    Returns:
        dict[str, object] | None: Parsed document, or ``None`` on failure.

    Examples:
        >>> _load_cache_document(Path("/no/such/cache.json")) is None
        True
    """
    if not cache_path.is_file():
        return None
    try:
        doc = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return doc if isinstance(doc, dict) else None


def _records_from_cache_doc(doc: dict[str, object]) -> dict[str, SkillRecord] | None:
    """Rehydrate cached skill records, returning ``None`` when any row fails validation.

    Args:
        doc (dict[str, object]): Parsed cache JSON object.

    Returns:
        dict[str, SkillRecord] | None: Records keyed by canonical id, or ``None`` on failure.

    Examples:
        >>> _records_from_cache_doc({"records": "bad"}) is None
        True
    """
    raw_records = doc.get("records")
    if not isinstance(raw_records, list):
        return None
    records: dict[str, SkillRecord] = {}
    for item in raw_records:
        if not isinstance(item, dict):
            return None
        rec = _record_from_json(item)
        if rec is None:
            return None
        records[rec.canonical_id] = rec
    return records


def _manifest_to_json(manifest: SkillManifest) -> dict[str, object]:
    """Serialize a :class:`~sevn.skills.manifest.SkillManifest` for cache storage.

    Args:
        manifest (SkillManifest): Manifest to encode.

    Returns:
        dict[str, object]: JSON-serialisable manifest payload.

    Examples:
        >>> from sevn.skills.manifest import SkillManifest
        >>> _manifest_to_json(SkillManifest(name="a", description="d", version="1.0.0"))["name"]
        'a'
    """
    scripts = [
        {
            "path": s.path,
            "description": s.description,
            "args_overview": s.args_overview,
            "abortable": s.abortable,
            "python_version": s.python_version,
        }
        for s in manifest.scripts
    ]
    runnables = [
        {
            "runnable_id": r.runnable_id,
            "description": r.description,
            "language": r.language,
            "parameters": r.parameters,
            "schema_version": r.schema_version,
            "source_body": r.source_body,
            "abortable": r.abortable,
        }
        for r in manifest.runnables
    ]
    return {
        "name": manifest.name,
        "description": manifest.description,
        "version": manifest.version,
        "scripts": scripts,
        "see_also": list(manifest.see_also),
        "runnables": runnables,
        "python_version": manifest.python_version,
        "max_wall_seconds": manifest.max_wall_seconds,
        "quarantine_flag": manifest.quarantine_flag,
        "dependencies": {
            "uv_extras": list(manifest.dependencies.uv_extras),
            "executables": list(manifest.dependencies.executables),
        },
    }


def _manifest_from_json(data: dict[str, object], *, provenance: ProvenanceKind) -> SkillManifest:
    """Rebuild a manifest from cached JSON via :func:`~sevn.skills.manifest.manifest_from_mapping`.

    Args:
        data (dict[str, object]): Cached manifest payload.
        provenance (ProvenanceKind): Skill tree kind for validation rules.

    Returns:
        SkillManifest: Parsed manifest.

    Examples:
        >>> m = _manifest_from_json(
        ...     {"name": "x", "description": "d", "version": "1.0.0", "scripts": []},
        ...     provenance="user",
        ... )
        >>> m.name
        'x'
    """
    scripts_raw = data.get("scripts")
    scripts_block: list[dict[str, object]] = []
    if isinstance(scripts_raw, list):
        for item in scripts_raw:
            if isinstance(item, dict):
                scripts_block.append(item)
    runnables_raw = data.get("runnables")
    runnables_block: list[dict[str, object]] = []
    if isinstance(runnables_raw, list):
        for item in runnables_raw:
            if isinstance(item, dict):
                runnables_block.append(item)
    deps_raw = data.get("dependencies")
    deps_block: dict[str, object] = {}
    if isinstance(deps_raw, dict):
        deps_block = deps_raw
    mapping: dict[str, object] = {
        "name": data.get("name"),
        "description": data.get("description"),
        "version": data.get("version"),
        "scripts": scripts_block,
        "runnables": runnables_block,
        "python_version": data.get("python_version"),
        "max_wall_seconds": data.get("max_wall_seconds"),
        "quarantine": data.get("quarantine_flag"),
        "see_also": data.get("see_also"),
        "dependencies": deps_block,
    }
    return manifest_from_mapping(mapping, body="", provenance=provenance)


def _record_to_json(record: SkillRecord) -> dict[str, object]:
    """Serialize one :class:`~sevn.skills.models.SkillRecord` for cache storage.

    Args:
        record (SkillRecord): Skill row to encode.

    Returns:
        dict[str, object]: JSON-serialisable record payload.

    Examples:
        >>> from sevn.skills.manifest import SkillManifest
        >>> rec = SkillRecord(
        ...     canonical_id="a",
        ...     skill_dir=Path("/tmp/a"),
        ...     manifest=SkillManifest(name="a", description="d", version="1.0.0"),
        ...     provenance="user",
        ...     markdown_raw="",
        ... )
        >>> _record_to_json(rec)["canonical_id"]
        'a'
    """
    return {
        "canonical_id": record.canonical_id,
        "skill_dir": str(record.skill_dir),
        "provenance": record.provenance,
        "markdown_raw": record.markdown_raw,
        "validation_errors": list(record.validation_errors),
        "manifest": _manifest_to_json(record.manifest),
    }


def _record_from_json(data: dict[str, object]) -> SkillRecord | None:
    """Rehydrate one cached skill record, preserving quarantine and validation errors.

    Args:
        data (dict[str, object]): Cached record payload.

    Returns:
        SkillRecord | None: Parsed record, or ``None`` when validation fails.

    Examples:
        >>> _record_from_json({"canonical_id": 1}) is None
        True
    """
    cid = data.get("canonical_id")
    skill_dir = data.get("skill_dir")
    provenance = data.get("provenance")
    markdown_raw = data.get("markdown_raw")
    validation_errors = data.get("validation_errors")
    manifest_raw = data.get("manifest")
    if not isinstance(cid, str) or not isinstance(skill_dir, str):
        return None
    if not isinstance(provenance, str):
        return None
    if provenance not in ("core", "user", "generated", "plugin"):
        return None
    if not isinstance(markdown_raw, str):
        return None
    if not isinstance(manifest_raw, dict):
        return None
    prov = cast("ProvenanceKind", provenance)
    errs: tuple[str, ...] = ()
    if isinstance(validation_errors, list):
        errs = tuple(str(x) for x in validation_errors)
    try:
        manifest = _manifest_from_json(manifest_raw, provenance=prov)
    except Exception:
        return None
    return SkillRecord(
        canonical_id=cid,
        skill_dir=Path(skill_dir),
        manifest=manifest,
        provenance=prov,
        markdown_raw=markdown_raw,
        validation_errors=errs,
    )


def _registry_fingerprint_digest(records: dict[str, SkillRecord]) -> str:
    """Return the registry fingerprint digest shared with registry-version invalidation.

    Args:
        records (dict[str, SkillRecord]): Current discovery rows.

    Returns:
        str: SHA-256 hex digest of sorted fingerprint lines.

    Examples:
        >>> _registry_fingerprint_digest({}) == _sha256_lines([])
        True
    """
    lines: list[str] = []
    for sid in sorted(records):
        rec = records[sid]
        q = int(rec.manifest.effective_quarantine(rec.provenance))
        caps = json.dumps(build_skill_capability_rows(rec.manifest), sort_keys=True)
        lines.append(f"{sid}|{rec.manifest.version}|{q}|{caps}")
    return _sha256_lines(lines)


def _write_cache(
    cache_path: Path,
    *,
    tree_signature: str,
    skills_roots: list[str],
    registry_seq: int,
    records: dict[str, SkillRecord],
    scan_ms: float,
) -> None:
    """Persist discovery rows and invalidation metadata atomically under ``.sevn/``.

    Args:
        cache_path (Path): Target cache file path.
        tree_signature (str): Filesystem signature digest.
        skills_roots (list[str]): Normalised configured skills root paths.
        registry_seq (int): Manager ``registry_version`` sequence at write time.
        records (dict[str, SkillRecord]): Discovery rows to persist.
        scan_ms (float): Measured full-scan duration in milliseconds.

    Returns:
        None

    Examples:
        >>> from pathlib import Path as _P
        >>> _write_cache(_P("/tmp/x.cache"), tree_signature="sig", skills_roots=[], registry_seq=0, records={}, scan_ms=1.0)  # doctest: +ELLIPSIS
    """
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    doc: dict[str, Any] = {
        "version": _CACHE_VERSION,
        "tree_signature": tree_signature,
        "skills_roots": skills_roots,
        "registry_seq": registry_seq,
        "registry_fingerprint": _registry_fingerprint_digest(records),
        "scan_ms": round(scan_ms, 2),
        "records": [_record_to_json(records[sid]) for sid in sorted(records)],
    }
    tmp = cache_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, cache_path)


__all__ = [
    "DISCOVERY_CACHE_FILENAME",
    "discovery_cache_enabled",
    "discovery_cache_file",
    "reload_skills_with_cache",
]
