"""Skills registry: scan, validate, ``load_skill`` payloads, subprocess runners (`specs/12`).
Module: sevn.skills.manager
Depends: asyncio, hashlib, json, logging, pathlib, shutil, sys, time, uuid, yaml,
    sevn.agent.tracing.sink, sevn.config.defaults, sevn.security.llmignore,
    sevn.security.sandbox_runtime, sevn.skills.capabilities, sevn.skills.errors,
    sevn.skills.index, sevn.skills.manifest, sevn.skills.models
Exports:
    Classes:
        SkillsManager — Discover skills, build payloads, run scripts/runnables.
    Functions:
        did_you_mean_skill_script — fuzzy declared script paths for tool errors.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import shutil
import sys
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Final

import yaml
from loguru import logger

from sevn.agent.tracing.sink import TraceEvent, TraceSink
from sevn.config.defaults import (
    DEFAULT_SKILL_MAX_WALL_SECONDS,
    LOAD_SKILL_MARKDOWN_INLINE_MAX_BYTES,
)
from sevn.security.llmignore import assert_shadow_workspace_excludes_llmignore
from sevn.security.sandbox_runtime import materialize_shadow_workspace
from sevn.skills.browser_session import merge_browser_proc_env
from sevn.skills.capabilities import build_skill_capability_rows
from sevn.skills.computer_use import COMPUTER_USE_SKILL_ID, gate_computer_use_core_skill
from sevn.skills.cua_agent import CUA_AGENT_SKILL_ID, gate_cua_agent_core_skill
from sevn.skills.cursor_cloud import CURSOR_CLOUD_SKILL_ID, gate_cursor_cloud_core_skill
from sevn.skills.discogs import DISCOGS_SKILL_IDS, discogs_skill_enabled, gate_discogs_core_skills
from sevn.skills.discogs_secrets import merge_discogs_proc_env
from sevn.skills.errors import (
    SKILL_INVALID_JSON,
    SKILL_NOT_FOUND,
    SKILL_QUARANTINED,
    SKILL_RUNNABLE_UNSUPPORTED,
    SKILL_SCRIPT_ARGS,
    SKILL_SCRIPT_NONZERO,
    SKILL_SCRIPT_UNKNOWN,
    SKILL_VALIDATION,
    TOOL_TIMEOUT,
    SkillExecutionError,
    failure_envelope,
    success_envelope,
)
from sevn.skills.index import SkillsIndex, SkillsIndexBuilder, resolve_skill_alias
from sevn.skills.lume import LUME_SKILL_ID, gate_lume_core_skill
from sevn.skills.manifest import (
    SkillManifest,
    downgrade_manifest,
    infer_abortable_for_script,
    parse_skill_markdown,
    required_positional_arg_count,
    split_frontmatter,
    validate_script_argv,
    validate_script_paths,
)
from sevn.skills.models import ProvenanceKind, SkillRecord
from sevn.skills.obsidian_cli import OBSIDIAN_CLI_SKILL_ID, gate_obsidian_cli_core_skill
from sevn.skills.openwiki import OPENWIKI_SKILL_ID, gate_openwiki_core_skill
from sevn.skills.openwiki_secrets import merge_openwiki_proc_env
from sevn.skills.social_media_manager import (
    SOCIAL_MEDIA_MANAGER_SKILL_ID,
    gate_social_media_manager_core_skill,
)
from sevn.workspace.layout import WorkspaceLayout

if TYPE_CHECKING:
    from sevn.config.workspace_config import WorkspaceConfig

_PROV_ORDER: Final[dict[ProvenanceKind, int]] = {
    "core": 0,
    "generated": 1,
    "user": 2,
    "plugin": 3,
}

# Skills that are always excluded from the runtime (gateway) skill index regardless of config.
# ``kokoro-tts`` is the local TTS *engine* behind the voice ``tts`` tool's ``kokoro`` backend
# (``sevn.voice.backends.KokoroBackend`` execs ``scripts/generate.py`` directly). It ships and
# seeds so the backend can find it, but must never be offered to the model as a research skill.
_RUNTIME_QUARANTINED_CORE_SKILL_IDS: Final[frozenset[str]] = frozenset(
    {"discogs-shared", "kokoro-tts"},
)


def _skill_trace_event(kind: str, attrs: Mapping[str, object]) -> TraceEvent:
    """Build a synthetic ``TraceEvent`` for the skills subsystem.
    Args:
        kind (str): Event kind tag (e.g. ``"skill.load"``, ``"skill.run"``).
        attrs (Mapping[str, object]): Free-form structured attributes.
    Returns:
        TraceEvent: Single-instant span with ``status="ok"`` and synthetic ids.
    Examples:
        >>> ev = _skill_trace_event("skill.test", {"k": "v"})
        >>> ev.kind
        'skill.test'
    """
    now = time.time_ns()
    return TraceEvent(
        kind=kind,
        span_id=f"skl-{uuid.uuid4().hex[:12]}",
        parent_span_id=None,
        session_id="skills",
        turn_id="skills",
        tier=None,
        ts_start_ns=now,
        ts_end_ns=now,
        status="ok",
        attrs=dict(attrs),
    )


async def _emit_skill(sink: TraceSink | None, kind: str, attrs: Mapping[str, object]) -> None:
    """Emit a synthetic skills trace event when ``sink`` is wired.
    Args:
        sink (TraceSink | None): Trace sink; ``None`` makes this a no-op.
        kind (str): Trace event kind.
        attrs (Mapping[str, object]): Structured attributes.
    Examples:
        >>> import asyncio, inspect
        >>> inspect.iscoroutinefunction(_emit_skill)
        True
        >>> asyncio.run(_emit_skill(None, "skill.test", {})) is None
        True
    """
    if sink is None:
        return
    await sink.emit(_skill_trace_event(kind, attrs))


def _sha256_lines(lines: list[str]) -> str:
    """Hash ``\\n``-joined lines with SHA-256 for fingerprinting.
    Args:
        lines (list[str]): Pre-formatted fingerprint rows.
    Returns:
        str: Hex digest of the joined UTF-8 bytes.
    Examples:
        >>> len(_sha256_lines(["a", "b"]))
        64
    """
    joined = "\n".join(lines).encode("utf-8")
    return hashlib.sha256(joined).hexdigest()


def _loads_single_json_object(raw: bytes) -> dict[str, Any]:
    """Decode subprocess stdout into a single JSON object, salvaging stray prefixes.
    Args:
        raw (bytes): UTF-8 (lossy decoded) stdout from a skill subprocess.
    Returns:
        dict[str, Any]: Parsed JSON object.
    Raises:
        ValueError: When stdout is empty after stripping.
        TypeError: When the decoded JSON is not an object.
        json.JSONDecodeError: When no object can be recovered from the text.
    Examples:
        >>> _loads_single_json_object(b'{"ok": true}')
        {'ok': True}
    """
    if not raw.strip():
        msg = "empty stdout from skill subprocess"
        raise ValueError(msg)
    text = raw.decode("utf-8", errors="replace").strip()
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        obj = json.loads(text[start : end + 1])
    if not isinstance(obj, dict):
        msg = "skill subprocess JSON must be an object"
        raise TypeError(msg)
    return obj


_SKILL_SCRIPT_ALIASES: Final[dict[str, dict[str, str]]] = {
    "scheduling": {
        "cron_status": "scripts/cron_list.py",
        "scripts/cron_status": "scripts/cron_list.py",
        "scripts/cron_status.py": "scripts/cron_list.py",
    },
}


def _canonicalise_script_name(rec: SkillRecord, script: str) -> str | None:
    """Normalise a ``run_skill_script`` script arg to a manifest ``scripts:`` path.

    Accepts ``name``, ``scripts/name``, and ``scripts/name.py`` as equivalent forms
    per ``specs/12-skills-system.md`` §2.4.

    Args:
        rec (SkillRecord): Resolved skill record.
        script (str): Caller-supplied script identifier.

    Returns:
        str | None: Manifest-relative script path when recognised; else ``None``.

    Examples:
        >>> from pathlib import Path
        >>> from sevn.skills.manifest import SkillManifest, SkillScriptEntry
        >>> from sevn.skills.models import SkillRecord
        >>> rec = SkillRecord(
        ...     canonical_id="demo",
        ...     skill_dir=Path("/tmp/demo"),
        ...     manifest=SkillManifest(
        ...         name="demo",
        ...         description="d",
        ...         version="1.0.0",
        ...         scripts=(SkillScriptEntry(path="scripts/scan.py", description="scan"),),
        ...     ),
        ...     markdown_raw="",
        ...     provenance="core",
        ... )
        >>> _canonicalise_script_name(rec, "scan")
        'scripts/scan.py'
    """
    raw = script.strip().strip("/")
    if not raw:
        return None
    declared = {entry.path for entry in rec.manifest.scripts}
    alias_target = _SKILL_SCRIPT_ALIASES.get(rec.canonical_id, {}).get(raw)
    if alias_target is not None and alias_target in declared:
        return alias_target
    candidates: list[str] = [raw]
    if not raw.startswith("scripts/"):
        candidates.append(f"scripts/{raw}")
    if not raw.endswith(".py"):
        candidates.extend(f"{candidate}.py" for candidate in list(candidates))
    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if candidate in declared:
            return candidate
    return None


def _skill_script_workspace_source_path(
    workspace_path: Path,
    rec: SkillRecord,
    script_rel: str,
) -> str:
    """Return the workspace-relative on-disk path for a declared skill script.

    Args:
        workspace_path (Path): Operator workspace root.
        rec (SkillRecord): Resolved skill record.
        script_rel (str): Manifest-relative script path (e.g. ``scripts/pdf.py``).

    Returns:
        str: Path relative to the workspace (e.g. ``skills/core/pdf/scripts/pdf.py``).

    Examples:
        >>> from pathlib import Path
        >>> from sevn.skills.manifest import SkillManifest
        >>> from sevn.skills.models import SkillRecord
        >>> ws = Path("/tmp/ws")
        >>> rec = SkillRecord(
        ...     canonical_id="pdf",
        ...     skill_dir=ws / "skills" / "core" / "pdf",
        ...     manifest=SkillManifest(name="pdf", description="d", version="1.0.0"),
        ...     provenance="core",
        ...     markdown_raw="",
        ... )
        >>> _skill_script_workspace_source_path(ws, rec, "scripts/pdf.py")
        'skills/core/pdf/scripts/pdf.py'
    """
    workspace_root = workspace_path.expanduser().resolve()
    skill_dir = rec.skill_dir.resolve()
    try:
        rel_skill = skill_dir.relative_to(workspace_root)
        return (rel_skill / script_rel).as_posix()
    except ValueError:
        pass
    prov = rec.provenance
    if prov == "plugin":
        parts = rec.canonical_id.split("/", 1)
        if len(parts) == 2:
            return f"skills/plugins/{parts[0]}/{parts[1]}/{script_rel}"
    if prov in ("core", "user", "generated"):
        return f"skills/{prov}/{rec.canonical_id}/{script_rel}"
    return f"skills/{rec.canonical_id}/{script_rel}"


_SKILL_CONTRACT_MARKERS: Final[tuple[str, ...]] = (
    "# SKILL CONTRACT",
    "# OUTPUT CONTRACT",
)

_LOAD_SKILL_MENU_HINT: Final[str] = (
    "Use `read` or `search_in_file` on `skill_md_path` or paths in `references`; "
    "call `load_skill` with `full=true` only when you must inline the entire contract."
)


def _skill_md_workspace_path(workspace_path: Path, rec: SkillRecord) -> str:
    """Return the workspace-relative path to a skill's ``SKILL.md``.

    Args:
        workspace_path (Path): Operator workspace root.
        rec (SkillRecord): Resolved skill record.

    Returns:
        str: Path relative to the workspace (e.g. ``skills/core/pdf/SKILL.md``).

    Examples:
        >>> from pathlib import Path
        >>> from sevn.skills.manifest import SkillManifest
        >>> from sevn.skills.models import SkillRecord
        >>> ws = Path("/tmp/ws")
        >>> rec = SkillRecord(
        ...     canonical_id="pdf",
        ...     skill_dir=ws / "skills" / "core" / "pdf",
        ...     manifest=SkillManifest(name="pdf", description="d", version="1.0.0"),
        ...     provenance="core",
        ...     markdown_raw="",
        ... )
        >>> _skill_md_workspace_path(ws, rec)
        'skills/core/pdf/SKILL.md'
    """
    return _skill_script_workspace_source_path(workspace_path, rec, "SKILL.md")


def _list_skill_reference_paths(workspace_path: Path, rec: SkillRecord) -> list[str]:
    """List workspace-relative ``references/*.md`` paths for a skill directory.

    Args:
        workspace_path (Path): Operator workspace root.
        rec (SkillRecord): Resolved skill record.

    Returns:
        list[str]: Sorted workspace-relative paths (may be empty).

    Examples:
        >>> from pathlib import Path
        >>> from sevn.skills.manifest import SkillManifest
        >>> from sevn.skills.models import SkillRecord
        >>> import tempfile
        >>> ws = Path(tempfile.mkdtemp())
        >>> skill_dir = ws / "skills" / "user" / "demo"
        >>> skill_dir.mkdir(parents=True)
        >>> _ = (skill_dir / "SKILL.md").write_text("---\\nname: demo\\n---\\n", encoding="utf-8")
        >>> (skill_dir / "references").mkdir()
        >>> _ = (skill_dir / "references" / "a.md").write_text("x", encoding="utf-8")
        >>> rec = SkillRecord(
        ...     canonical_id="demo",
        ...     skill_dir=skill_dir,
        ...     manifest=SkillManifest(name="demo", description="d", version="1.0.0"),
        ...     provenance="user",
        ...     markdown_raw="",
        ... )
        >>> _list_skill_reference_paths(ws, rec)
        ['skills/user/demo/references/a.md']
    """
    ref_dir = rec.skill_dir / "references"
    if not ref_dir.is_dir():
        return []
    out: list[str] = []
    for path in sorted(ref_dir.glob("*.md")):
        out.append(
            _skill_script_workspace_source_path(
                workspace_path,
                rec,
                f"references/{path.name}",
            ),
        )
    return out


def _skill_markdown_intro(raw: str, *, max_bytes: int) -> tuple[str, bool]:
    """Build a spill-safe ``SKILL.md`` prefix for menu ``load_skill`` payloads.

    Args:
        raw (str): Full UTF-8 ``SKILL.md`` text.
        max_bytes (int): Maximum UTF-8 byte length for the returned prefix.

    Returns:
        tuple[str, bool]: ``(intro_text, was_truncated)`` — ``was_truncated`` is
            ``False`` only when ``intro_text`` equals ``raw``.

    Examples:
        >>> intro, truncated = _skill_markdown_intro("x" * 100, max_bytes=50)
        >>> truncated
        True
        >>> len(intro.encode("utf-8")) <= 51
        True
    """
    full_bytes = len(raw.encode("utf-8"))
    if full_bytes <= max_bytes:
        return raw, False
    has_frontmatter = raw.lstrip("\ufeff").startswith("---")
    if has_frontmatter:
        fm_yaml, body = split_frontmatter(raw)
        cut_body = body
        for marker in _SKILL_CONTRACT_MARKERS:
            idx = body.find(marker)
            if idx >= 0:
                cut_body = body[:idx].rstrip()
                break
        intro = f"---{fm_yaml}---\n{cut_body}\n"
    else:
        intro = raw
    if len(intro.encode("utf-8")) <= max_bytes:
        return intro, intro != raw
    encoded = intro.encode("utf-8")
    cut = max_bytes
    while cut > 0 and encoded[cut - 1 : cut] != b"\n":
        cut -= 1
    if cut <= 0:
        cut = max_bytes
    trimmed = encoded[:cut].decode("utf-8", errors="ignore").rstrip()
    while trimmed and len(trimmed.encode("utf-8")) > max_bytes:
        trimmed = trimmed[:-1]
    return f"{trimmed}\n", True


def did_you_mean_skill_script(
    workspace_path: Path,
    skill: str,
    script: str,
    *,
    limit: int = 5,
) -> list[str]:
    """Fuzzy-match declared script paths for ``run_skill_script`` failures.

    Never echoes the unknown input. Returns workspace-relative source paths
    (e.g. ``skills/core/pdf/scripts/pdf.py``) ahead of manifest ``scripts:``
    paths so agents can ``read`` the bundled source after a miss.

    Args:
        workspace_path (Path): Workspace root for bundled + overlay skill scan.
        skill (str): Canonical skill id from the tool call.
        script (str): Caller-supplied script identifier that failed resolution.
        limit (int): Max suggestions.

    Returns:
        list[str]: Source and manifest script paths closest to ``script``.

    Examples:
        >>> from pathlib import Path
        >>> isinstance(did_you_mean_skill_script(Path("/tmp"), "missing", "x"), list)
        True
    """
    import difflib

    raw = script.strip()
    if not raw or not skill.strip():
        return []
    try:
        man = SkillsManager.shared(workspace_path)
        rec = man.get_record(skill.strip())
    except SkillExecutionError:
        return []
    declared = sorted({entry.path for entry in rec.manifest.scripts})
    if not declared:
        return []
    stem_to_path: dict[str, str] = {}
    for path in declared:
        stem_to_path[path] = path
        stem_to_path[Path(path).name] = path
        stem_to_path[Path(path).stem] = path
    for alias_key, target in _SKILL_SCRIPT_ALIASES.get(rec.canonical_id, {}).items():
        if target in declared:
            stem_to_path[alias_key] = target
            stem_to_path[Path(alias_key).stem] = target
    query_forms = {raw, Path(raw).stem}
    if not raw.startswith("scripts/"):
        query_forms.add(f"scripts/{raw}")
    query_forms.add(Path(raw).name)
    unknown_paths = {raw, f"scripts/{raw}", f"scripts/{raw}.py"}
    manifest_matches: list[str] = []
    for query in query_forms:
        if not query:
            continue
        for hit in difflib.get_close_matches(query, sorted(stem_to_path), n=limit, cutoff=0.5):
            resolved = stem_to_path[hit]
            if resolved in unknown_paths or resolved in manifest_matches:
                continue
            manifest_matches.append(resolved)
            if len(manifest_matches) >= limit:
                break
        if len(manifest_matches) >= limit:
            break
    out: list[str] = []
    seen: set[str] = set()
    for manifest_path in manifest_matches:
        for candidate in (
            _skill_script_workspace_source_path(workspace_path, rec, manifest_path),
            manifest_path,
        ):
            if candidate in seen:
                continue
            seen.add(candidate)
            out.append(candidate)
            if len(out) >= limit:
                return out
    return out


def _plugin_enabled(cfg: WorkspaceConfig | None, plugin_name: str) -> bool:
    """``skills.<plugin>.enabled`` defaults **false** (`specs/12` §5).
    Args:
        cfg (WorkspaceConfig | None): Loaded workspace config; ``None`` -> disabled.
        plugin_name (str): Plugin directory name under ``skills/plugins/``.
    Returns:
        bool: True when the plugin is explicitly enabled in ``sevn.json``.
    Examples:
        >>> _plugin_enabled(None, "anything")
        False
    """
    if cfg is None or cfg.skills is None:
        return False
    blob = cfg.skills
    block = blob.get(plugin_name)
    if isinstance(block, dict) and "enabled" in block:
        return bool(block["enabled"])
    return False


def _merge_records(
    discovered: list[tuple[int, SkillRecord]],
) -> dict[str, SkillRecord]:
    """Pick winning record per id: **user > generated > core**; later root wins ties.
    Args:
        discovered (list[tuple[int, SkillRecord]]): ``(root_index, record)`` pairs in
            scan order from one or more ``skills`` roots.
    Returns:
        dict[str, SkillRecord]: Canonical id -> winning record.
    Raises:
        SkillExecutionError: When the same plugin id maps to different install paths.
    Examples:
        >>> _merge_records([])
        {}
    """
    by_id: dict[str, list[tuple[int, SkillRecord]]] = {}
    for root_idx, rec in discovered:
        by_id.setdefault(rec.canonical_id, []).append((root_idx, rec))
    out: dict[str, SkillRecord] = {}
    for rid, items in by_id.items():
        uniq_plugin_dirs = {
            str(t[1].skill_dir.resolve()) for t in items if t[1].provenance == "plugin"
        }
        if len(uniq_plugin_dirs) > 1:
            msg = f"duplicate plugin skill id `{rid}` maps to multiple install paths"
            raise SkillExecutionError(msg, code=SKILL_VALIDATION)
        winner = max(items, key=lambda it: (it[0], _PROV_ORDER[it[1].provenance]))
        out[rid] = winner[1]
    return out


def _load_flat_skill(
    skill_dir: Path,
    provenance: ProvenanceKind,
    *,
    downgrade_user: bool,
) -> SkillRecord:
    """Load a flat (non-plugin) skill directory and parse its ``SKILL.md``.
    Args:
        skill_dir (Path): Directory containing ``SKILL.md`` (and optional scripts).
        provenance (ProvenanceKind): ``core`` / ``generated`` / ``user``.
        downgrade_user (bool): When ``True`` apply lenient parsing for user skills.
    Returns:
        SkillRecord: Parsed record with optional validation warnings.
    Raises:
        SkillExecutionError: On missing ``SKILL.md`` (non-downgraded) or name mismatch.
    Examples:
        >>> import inspect
        >>> sig = inspect.signature(_load_flat_skill)
        >>> "downgrade_user" in sig.parameters
        True
    """
    md = skill_dir / "SKILL.md"
    if not md.is_file():
        if provenance == "user" and downgrade_user:
            # Unloadable: quarantine so inventory/list_registry never advertise it
            # as available (D14 skill-registry SSOT).
            m = SkillManifest(
                name=skill_dir.name,
                description=skill_dir.name,
                version="0.0.0",
                quarantine_flag=True,
            )
            return SkillRecord(
                canonical_id=skill_dir.name,
                skill_dir=skill_dir,
                manifest=m,
                provenance=provenance,
                markdown_raw="",
                validation_errors=("missing SKILL.md",),
            )
        msg = f"missing SKILL.md under {skill_dir}"
        raise SkillExecutionError(msg, code=SKILL_VALIDATION)
    raw = md.read_text(encoding="utf-8")
    val_errs: tuple[str, ...] = ()
    if provenance == "user" and downgrade_user:
        man, val_errs = downgrade_manifest(skill_dir.name, raw, provenance)
    else:
        man = parse_skill_markdown(raw, provenance)
    if man.name.strip() != skill_dir.name:
        if provenance == "user" and downgrade_user:
            man = replace(
                man,
                name=skill_dir.name,
            )
        else:
            msg = f"frontmatter name `{man.name}` must match directory `{skill_dir.name}`"
            raise SkillExecutionError(msg, code=SKILL_VALIDATION)
    validate_script_paths(skill_dir, man)
    return SkillRecord(
        canonical_id=skill_dir.name,
        skill_dir=skill_dir,
        manifest=man,
        provenance=provenance,
        markdown_raw=raw,
        validation_errors=val_errs,
    )


def _load_plugin_skill(
    plugin_name: str, skill_dir: Path, *, cfg: WorkspaceConfig | None
) -> SkillRecord:
    """Load a plugin-tree skill and verify the parent plugin is enabled.
    Args:
        plugin_name (str): Parent plugin directory name.
        skill_dir (Path): Skill directory under ``plugins/<plugin_name>/``.
        cfg (WorkspaceConfig | None): Workspace config used to gate plugin enablement.
    Returns:
        SkillRecord: Loaded plugin skill with canonical id ``plugin/skill``.
    Raises:
        SkillExecutionError: When the plugin is disabled, ``SKILL.md`` is missing,
            or frontmatter ``name`` does not match either filesystem or canonical name.
    Examples:
        >>> import inspect
        >>> sig = inspect.signature(_load_plugin_skill)
        >>> sorted(sig.parameters)
        ['cfg', 'plugin_name', 'skill_dir']
    """
    if plugin_name == "computer_use":
        from sevn.skills.computer_use import computer_use_config_enabled

        if not computer_use_config_enabled(cfg):
            msg = "skills.computer_use.enabled is false"
            raise SkillExecutionError(msg, code=SKILL_VALIDATION)
    elif not _plugin_enabled(cfg, plugin_name):
        msg = f"skills.{plugin_name}.enabled is false or unset"
        raise SkillExecutionError(msg, code=SKILL_VALIDATION)
    md = skill_dir / "SKILL.md"
    if not md.is_file():
        msg = f"missing SKILL.md under {skill_dir}"
        raise SkillExecutionError(msg, code=SKILL_VALIDATION)
    raw = md.read_text(encoding="utf-8")
    man = parse_skill_markdown(raw, "plugin")
    canon = f"{plugin_name}/{skill_dir.name}"
    ok_name = man.name.strip() == skill_dir.name or man.name.strip() == canon
    if not ok_name:
        msg = f"frontmatter name `{man.name}` must match `{skill_dir.name}` or `{canon}`"
        raise SkillExecutionError(msg, code=SKILL_VALIDATION)
    if man.name.strip() != skill_dir.name:
        man = replace(man, name=skill_dir.name)
    validate_script_paths(skill_dir, man)
    return SkillRecord(
        canonical_id=canon,
        skill_dir=skill_dir,
        manifest=man,
        provenance="plugin",
        markdown_raw=raw,
    )


def _scan_skills_tree(
    skills_base: Path,
    root_idx: int,
    *,
    cfg: WorkspaceConfig | None,
) -> list[tuple[int, SkillRecord]]:
    """Walk one ``skills`` root scanning flat + plugin trees into records.
    Args:
        skills_base (Path): Root path containing ``core``/``generated``/``user``/``plugins``.
        root_idx (int): Index of the root within the configured tuple (tie-breaker).
        cfg (WorkspaceConfig | None): Workspace config used to gate plugin enablement.
    Returns:
        list[tuple[int, SkillRecord]]: ``(root_index, record)`` pairs in scan order.
    Examples:
        >>> from pathlib import Path
        >>> _scan_skills_tree(Path("/no/such/dir"), 0, cfg=None)
        []
    """
    out: list[tuple[int, SkillRecord]] = []
    if not skills_base.is_dir():
        return out
    for prov, sub in (
        ("core", "core"),
        ("generated", "generated"),
        ("user", "user"),
    ):
        base = skills_base / sub
        if not base.is_dir():
            continue
        for child in sorted(base.iterdir(), key=lambda p: p.name):
            if not child.is_dir():
                continue
            if sub == "generated" and child.name == "draft":
                continue
            if (
                sub == "core"
                and child.name == COMPUTER_USE_SKILL_ID
                and gate_computer_use_core_skill(cfg) == "skip"
            ):
                continue
            if (
                sub == "core"
                and child.name == CUA_AGENT_SKILL_ID
                and gate_cua_agent_core_skill(cfg) == "skip"
            ):
                continue
            if (
                sub == "core"
                and child.name == LUME_SKILL_ID
                and gate_lume_core_skill(cfg) == "skip"
            ):
                continue
            if (
                sub == "core"
                and child.name == CURSOR_CLOUD_SKILL_ID
                and gate_cursor_cloud_core_skill(cfg) == "skip"
            ):
                continue
            if (
                sub == "core"
                and child.name == SOCIAL_MEDIA_MANAGER_SKILL_ID
                and gate_social_media_manager_core_skill(cfg) == "skip"
            ):
                continue
            if (
                sub == "core"
                and child.name == OPENWIKI_SKILL_ID
                and gate_openwiki_core_skill(cfg) == "skip"
            ):
                continue
            if (
                sub == "core"
                and child.name == OBSIDIAN_CLI_SKILL_ID
                and gate_obsidian_cli_core_skill(cfg) == "skip"
            ):
                continue
            if sub == "core" and child.name in DISCOGS_SKILL_IDS:
                if gate_discogs_core_skills(cfg) == "skip":
                    continue
                if not discogs_skill_enabled(cfg, child.name):
                    continue
            if sub == "core" and child.name in _RUNTIME_QUARANTINED_CORE_SKILL_IDS:
                continue
            try:
                prov_t: ProvenanceKind = prov  # type: ignore[assignment]
                rec = _load_flat_skill(
                    child,
                    prov_t,
                    downgrade_user=prov_t == "user",
                )
            except SkillExecutionError:
                if prov == "core":
                    raise
                logger.opt(exception=True).warning("skipping invalid {} skill {}", prov, child)
                continue
            out.append((root_idx, rec))
    plug_root = skills_base / "plugins"
    if plug_root.is_dir():
        for plugin_dir in sorted(plug_root.iterdir(), key=lambda p: p.name):
            if not plugin_dir.is_dir():
                continue
            for skill_dir in sorted(plugin_dir.iterdir(), key=lambda p: p.name):
                if not skill_dir.is_dir():
                    continue
                try:
                    rec = _load_plugin_skill(plugin_dir.name, skill_dir, cfg=cfg)
                except SkillExecutionError:
                    logger.debug("skip plugin skill {}/{}", plugin_dir.name, skill_dir.name)
                    continue
                out.append((root_idx, rec))
    return out


class SkillsManager:
    """Discover skills, build ``load_skill`` payloads, run scripts/runnables.
    Class-level singleton keyed by ``(workspace_root, normalised skills roots tuple)`` — document
    **exact keying** so gateways do not spawn duplicate scanners.
    **Collision precedence (flat ``core`` / ``generated`` / ``user``):** later filesystem ``skills``
    roots in the tuple win on ties; within one tree **user** beats **generated** beats **core**
    (see ``sevn.config.defaults`` module comment). **Plugin** skills use ``plugin/skill`` ids and
    never shadow flat names unless operators mirror paths manually.
    """

    _instances: ClassVar[dict[tuple[str, tuple[str, ...]], SkillsManager]] = {}

    def __init__(
        self,
        workspace_root: Path,
        skills_roots: tuple[Path, ...],
        *,
        layout: WorkspaceLayout | None,
        config: WorkspaceConfig | None,
        trace_sink: TraceSink | None,
    ) -> None:
        """Construct a manager and perform the initial filesystem scan.
        Args:
            workspace_root (Path): Workspace root (used to materialise shadow workspaces).
            skills_roots (tuple[Path, ...]): One or more ``skills`` roots to scan in order.
            layout (WorkspaceLayout | None): Optional layout providing ``.sevn`` paths.
            config (WorkspaceConfig | None): Workspace config (governs plugin gating).
            trace_sink (TraceSink | None): Optional sink for ``skill.*`` trace events.
        Examples:
            >>> import inspect
            >>> sig = inspect.signature(SkillsManager.__init__)
            >>> "trace_sink" in sig.parameters
            True
        """
        self._workspace_root = workspace_root.expanduser().resolve()
        self._skills_roots = tuple(p.expanduser().resolve() for p in skills_roots)
        self._layout = layout
        self._config = config
        self._trace_sink = trace_sink
        self._records: dict[str, SkillRecord] = {}
        self._index = SkillsIndex(lines={})
        self._registry_seq = 0
        self._last_digest = ""
        self.reload()

    @classmethod
    def shared(
        cls,
        workspace_root: Path | WorkspaceLayout,
        skills_roots: Sequence[Path] | None = None,
        *,
        layout: WorkspaceLayout | None = None,
        config: WorkspaceConfig | None = None,
        trace_sink: TraceSink | None = None,
    ) -> SkillsManager:
        """Return the process-wide singleton for the resolved key.
        Key: ``(str(workspace_root.resolve()), tuple(str(r.resolve()) for r in skills_roots))``.
        Args:
            workspace_root (Path | WorkspaceLayout): Workspace root (anchors the cache
                key), or a :class:`~sevn.workspace.layout.WorkspaceLayout` whose
                ``content_root`` is used (and which fills ``layout`` when omitted).
            skills_roots (Sequence[Path] | None): Optional skills roots; defaults to
                ``workspace_root/"skills"``.
            layout (WorkspaceLayout | None): Optional layout passed through on creation.
            config (WorkspaceConfig | None): Optional workspace config passed through.
            trace_sink (TraceSink | None): Optional trace sink passed through.
        Returns:
            SkillsManager: Cached singleton for the resolved key.
        Examples:
            >>> import inspect
            >>> inspect.ismethod(SkillsManager.shared) or callable(SkillsManager.shared)
            True
        """
        layout_arg = layout
        root: Path
        if isinstance(workspace_root, WorkspaceLayout):
            if layout_arg is None:
                layout_arg = workspace_root
            root = workspace_root.content_root
        else:
            root = workspace_root
        wr = root.expanduser().resolve()
        if skills_roots is None:
            roots_list: list[Path] = [wr / "skills"]
            workspace_core = wr / "skills" / "core"
            has_workspace_core = workspace_core.is_dir() and any(
                p.is_dir() for p in workspace_core.iterdir()
            )
            if not has_workspace_core:
                try:
                    from sevn.data.bundled_skills import BUNDLED_SKILLS_ROOT

                    if BUNDLED_SKILLS_ROOT.is_dir():
                        roots_list.append(BUNDLED_SKILLS_ROOT)
                except (ImportError, AttributeError):
                    pass
            roots = tuple(roots_list)
        else:
            roots = tuple(Path(p).expanduser().resolve() for p in skills_roots)
        key = (str(wr), tuple(str(p.expanduser().resolve()) for p in roots))
        inst = cls._instances.get(key)
        if inst is None:
            inst = cls(wr, roots, layout=layout_arg, config=config, trace_sink=trace_sink)
            cls._instances[key] = inst
        return inst

    @classmethod
    def reset_singletons_for_tests(cls) -> None:
        """Clear singleton map (tests only).
        Examples:
            >>> SkillsManager.reset_singletons_for_tests()
            >>> SkillsManager._instances
            {}
        """
        cls._instances.clear()

    def _registry_fingerprint_lines(self) -> list[str]:
        """Return stable, sortable fingerprint lines for the current records.
        Returns:
            list[str]: One ``id|version|quarantine|capabilities_json`` line per skill.
        Examples:
            >>> import inspect
            >>> inspect.isfunction(SkillsManager._registry_fingerprint_lines)
            True
        """
        lines: list[str] = []
        for sid in sorted(self._records):
            r = self._records[sid]
            q = int(r.manifest.effective_quarantine(r.provenance))
            caps = json.dumps(build_skill_capability_rows(r.manifest), sort_keys=True)
            lines.append(f"{sid}|{r.manifest.version}|{q}|{caps}")
        return lines

    def _bump_if_changed(self) -> None:
        """Bump ``registry_version`` when the records fingerprint moves.
        Examples:
            >>> import inspect
            >>> inspect.isfunction(SkillsManager._bump_if_changed)
            True
        """
        digest = _sha256_lines(self._registry_fingerprint_lines())
        if digest != self._last_digest:
            self._registry_seq += 1
            self._last_digest = digest

    def reload(self) -> dict[str, int]:
        """Rescan trees; recompute index + ``registry_version`` when fingerprint moves.
        Returns:
            dict[str, int]: ``prev_count``, ``new_count`` for tracing hooks.
        Examples:
            >>> import inspect
            >>> sig = inspect.signature(SkillsManager.reload)
            >>> sig.return_annotation
            'dict[str, int]'
        """
        prev = len(self._records)
        discovered: list[tuple[int, SkillRecord]] = []
        for idx, root in enumerate(self._skills_roots):
            discovered.extend(
                _scan_skills_tree(root, idx, cfg=self._config),
            )
        self._records = _merge_records(discovered)
        self._index = SkillsIndexBuilder.from_records(self._records)
        self._bump_if_changed()
        return {"prev_count": prev, "new_count": len(self._records)}

    def bump_registry_version(self) -> str:
        """Manual promote / gateway hook — forces monotonic ``registry_version`` bump.
        Returns:
            str: New ``registry_version`` string after the bump.
        Examples:
            >>> import inspect
            >>> inspect.isfunction(SkillsManager.bump_registry_version)
            True
        """
        self._registry_seq += 1
        return self.registry_version

    @property
    def registry_version(self) -> str:
        """Monotonic string for ``LoadedBodyCache`` keys (`specs/11` §3.2).
        Returns:
            str: Stringified sequence number.
        Examples:
            >>> isinstance(SkillsManager.registry_version, property)
            True
        """
        return str(self._registry_seq)

    @property
    def index(self) -> SkillsIndex:
        """Latest ``SkillsIndex`` snapshot.
        Returns:
            SkillsIndex: Immutable snapshot rebuilt on every ``reload``.
        Examples:
            >>> isinstance(SkillsManager.index, property)
            True
        """
        return self._index

    def inventory_for_triager(self) -> dict[str, dict[str, object]]:
        """Return per-skill menu rows for triager prompt surfacing.

        Returns:
            dict[str, dict[str, object]]: ``name -> {summary,scripts,runnables,quarantine}``
                map. ``quarantine`` is the effective runtime gate so advertisers
                (``list_registry``) and ``load_skill`` share one source of truth (D14).

        Examples:
            >>> import inspect
            >>> inspect.isfunction(SkillsManager.inventory_for_triager)
            True
        """
        out: dict[str, dict[str, object]] = {}
        for name in sorted(self._records):
            rec = self._records[name]
            summary = str(rec.manifest.description or "").strip()
            scripts = [str(s.path) for s in rec.manifest.scripts]
            runnables = [str(r.runnable_id) for r in rec.manifest.runnables]
            out[name] = {
                "summary": summary,
                "scripts": scripts,
                "runnables": runnables,
                "quarantine": rec.manifest.effective_quarantine(rec.provenance),
            }
        return out

    def advertised_skill_descriptions(self) -> dict[str, str]:
        """Return name → summary for skills safe to advertise via ``list_registry``.

        Quarantined / unloadable skills are omitted so a subsequent ``load_skill``
        on any listed name never returns ``SKILL_NOT_FOUND`` (D14).

        Returns:
            dict[str, str]: Non-quarantined skill id → one-line summary.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(SkillsManager.advertised_skill_descriptions)
            True
        """
        out: dict[str, str] = {}
        for name, row in self.inventory_for_triager().items():
            if row.get("quarantine"):
                continue
            summary = str(row.get("summary") or "").strip() or name
            out[name] = summary
        return out

    def get_record(self, name: str) -> SkillRecord:
        """Return the ``SkillRecord`` for ``name`` or raise ``SKILL_NOT_FOUND``.
        Args:
            name (str): Canonical skill id (``plugin/skill`` for plugin trees).
        Returns:
            SkillRecord: Resolved record.
        Raises:
            SkillExecutionError: When ``name`` is not present in the registry.
        Examples:
            >>> import inspect
            >>> inspect.isfunction(SkillsManager.get_record)
            True
        """
        resolved = resolve_skill_alias(name)
        rec = self._records.get(resolved)
        if rec is None:
            known = sorted(self._records.keys())
            hint = f" (known: {known[:8]}{'…' if len(known) > 8 else ''})" if known else ""
            msg = f"unknown skill `{name}`{hint}"
            raise SkillExecutionError(msg, code=SKILL_NOT_FOUND)
        return rec

    def _shadow_parent(self) -> Path:
        """Return the parent directory for per-run shadow workspaces.
        Returns:
            Path: ``layout.dot_sevn/skills-shadow`` when layout is wired, else
                ``workspace_root/.sevn/skills-shadow``.
        Examples:
            >>> import inspect
            >>> inspect.isfunction(SkillsManager._shadow_parent)
            True
        """
        if self._layout is not None:
            return self._layout.dot_sevn / "skills-shadow"
        return self._workspace_root / ".sevn" / "skills-shadow"

    def _build_proc_env(
        self,
        shadow: Path,
        skill_dir: Path,
        *,
        skill_name: str | None = None,
        session_id: str = "",
        artifact_output_prefix: str = "",
    ) -> dict[str, str]:
        """Build the subprocess environment for a skill run.
        Args:
            shadow (Path): Materialised shadow workspace path.
            skill_dir (Path): Resolved on-disk skill directory.
            skill_name (str | None, optional): Canonical skill id for skill-specific
                env defaults. Defaults to ``None``.
            session_id (str, optional): Gateway session id for per-session output
                subfolders. Defaults to ``""``.
            artifact_output_prefix (str, optional): Workspace-relative artifact
                output prefix for skill scripts. Defaults to ``""``.
        Returns:
            dict[str, str]: Cloned environment with ``SEVN_WORKSPACE`` /
                ``SEVN_SKILL_DIR`` injected.
        Examples:
            >>> import inspect
            >>> inspect.isfunction(SkillsManager._build_proc_env)
            True
        """
        from sevn.runtime.operator_path import augment_operator_path

        env = augment_operator_path()
        env["SEVN_WORKSPACE"] = str(shadow)
        env["SEVN_SKILL_DIR"] = str(skill_dir)
        env["SEVN_CONTENT_ROOT"] = str(self._workspace_root)
        if session_id.strip():
            env["SEVN_SESSION_ID"] = session_id.strip()
        if artifact_output_prefix.strip():
            env["SEVN_ARTIFACT_OUTPUT_PREFIX"] = artifact_output_prefix.strip()
        from sevn.config.sevn_repo import resolve_sevn_checkout_for_workspace

        checkout = resolve_sevn_checkout_for_workspace(
            self._config,
            content_root=self._workspace_root,
        )
        if checkout is not None:
            env.setdefault("SEVN_REPO_ROOT", str(checkout))
        if skill_name:
            merge_browser_proc_env(
                env,
                content_root=self._workspace_root,
                session_id=session_id,
                cfg=self._config,
                skill_name=skill_name,
            )
        return env

    async def build_load_skill_payload(self, name: str, *, full: bool = False) -> dict[str, object]:
        """§2.3 JSON **dict** envelope (serialise at tool boundary).
        Args:
            name (str): Canonical skill id.
            full (bool, optional): When ``True``, inline the entire ``SKILL.md`` body.
                Defaults to menu mode (progressive disclosure).
        Returns:
            dict[str, object]: Tool envelope (``ok``/``data``/``message``) with
                manifest fields, capability rows, and the ``markdown`` body.
        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(SkillsManager.build_load_skill_payload)
            True
        """
        try:
            rec = self.get_record(name)
        except SkillExecutionError as exc:
            return failure_envelope(exc.code, str(exc))
        caps = build_skill_capability_rows(rec.manifest)
        raw = rec.markdown_raw
        full_bytes = len(raw.encode("utf-8"))
        inline_max = LOAD_SKILL_MARKDOWN_INLINE_MAX_BYTES
        data: dict[str, object] = {
            "skill_name": rec.canonical_id,
            "version": rec.manifest.version,
            "capabilities": caps,
            "quarantine": rec.manifest.effective_quarantine(rec.provenance),
        }
        if full or full_bytes <= inline_max:
            data["markdown"] = raw
            data["markdown_truncated"] = False
        else:
            intro, _ = _skill_markdown_intro(raw, max_bytes=inline_max)
            data["markdown"] = intro
            data["markdown_truncated"] = True
            data["markdown_full_bytes"] = full_bytes
            data["skill_md_path"] = _skill_md_workspace_path(self._workspace_root, rec)
            data["references"] = _list_skill_reference_paths(self._workspace_root, rec)
            data["load_hint"] = _LOAD_SKILL_MENU_HINT
        await _emit_skill(
            self._trace_sink,
            "skill.load",
            {
                "skill_name": rec.canonical_id,
                "version": rec.manifest.version,
                "capabilities_count": len(caps),
                "quarantine": data["quarantine"],
            },
        )
        return success_envelope(data)

    async def run_script(
        self,
        name: str,
        script_path: str,
        args: Sequence[str] | None = None,
        *,
        session_id: str = "",
        artifact_output_prefix: str = "",
    ) -> dict[str, object]:
        """Run ``scripts`` entry with subprocess JSON stdout contract (`specs/12` §2.4).
        Args:
            name (str): Canonical skill id.
            script_path (str): Manifest-declared script path (relative to skill dir).
            args (Sequence[str] | None, optional): Positional argv for the script.
                Defaults to ``None``.
            session_id (str, optional): Gateway session id for output subfolders.
            artifact_output_prefix (str, optional): Workspace-relative artifact
                output prefix injected into the subprocess environment.
        Returns:
            dict[str, object]: Tool envelope (``ok``/``data`` or ``ok``/``error``/``code``).
        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(SkillsManager.run_script)
            True
        """
        try:
            rec = self.get_record(name)
        except SkillExecutionError as exc:
            return failure_envelope(exc.code, str(exc))
        if rec.manifest.effective_quarantine(rec.provenance):
            return failure_envelope(
                SKILL_QUARANTINED,
                "skill is quarantined; promote from generated/ to user/ (see PRD 04 §5.9)",
            )
        rel = _canonicalise_script_name(rec, script_path)
        if rel is None:
            known_scripts = [s.path for s in rec.manifest.scripts]
            msg = (
                f"script `{script_path}` is not declared in SKILL.md for `{name}`; "
                f"declared scripts: {known_scripts if known_scripts else '[]'}"
            )
            return failure_envelope(SKILL_SCRIPT_UNKNOWN, msg)
        script_entry = next((s for s in rec.manifest.scripts if s.path == rel), None)
        if script_entry is None:
            known_scripts = [s.path for s in rec.manifest.scripts]
            msg = (
                f"script `{script_path}` is not declared in SKILL.md for `{name}`; "
                f"declared scripts: {known_scripts if known_scripts else '[]'}"
            )
            return failure_envelope(SKILL_SCRIPT_UNKNOWN, msg)
        abs_script = (rec.skill_dir / rel).resolve()
        try:
            abs_script.relative_to(rec.skill_dir.resolve())
        except ValueError:
            return failure_envelope(SKILL_VALIDATION, "script path escapes skill directory")
        if not abs_script.is_file():
            return failure_envelope(SKILL_VALIDATION, f"missing script file `{rel}`")
        argv_err = validate_script_argv(script_entry, args)
        if argv_err is not None:
            return failure_envelope(
                SKILL_SCRIPT_ARGS,
                argv_err,
                data={
                    "script": rel,
                    "args_overview": script_entry.args_overview,
                    "argv_count": len(args or ()),
                    "required_argv_count": required_positional_arg_count(
                        script_entry.args_overview,
                    ),
                },
            )
        argv = [sys.executable, str(abs_script), *[str(a) for a in (args or ())]]
        wall = rec.manifest.max_wall_seconds or DEFAULT_SKILL_MAX_WALL_SECONDS
        abortable = infer_abortable_for_script(rel, script_entry.abortable)
        return await self._run_subprocess(
            rec,
            argv,
            label_path=rel,
            runnable_id=None,
            wall_s=float(wall),
            abortable=abortable,
            session_id=session_id,
            artifact_output_prefix=artifact_output_prefix,
        )

    async def run_runnable(
        self,
        name: str,
        runnable_id: str,
        params: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        """Execute runnable (**v1: Python** only — see §10.1).
        Args:
            name (str): Canonical skill id.
            runnable_id (str): Runnable id declared in manifest (YAML or inline fence).
            params (Mapping[str, object] | None, optional): JSON-serialisable params
                exposed via ``SEVN_RUNNABLE_PARAMS``. Defaults to ``None``.
        Returns:
            dict[str, object]: Tool envelope (``ok``/``data`` or ``ok``/``error``/``code``).
        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(SkillsManager.run_runnable)
            True
        """
        try:
            rec = self.get_record(name)
        except SkillExecutionError as exc:
            return failure_envelope(exc.code, str(exc))
        if rec.manifest.effective_quarantine(rec.provenance):
            return failure_envelope(
                SKILL_QUARANTINED,
                "skill is quarantined; promote from generated/ to user/ (see PRD 04 §5.9)",
            )
        entry = next((r for r in rec.manifest.runnables if r.runnable_id == runnable_id), None)
        if entry is None:
            known_runnables = [r.runnable_id for r in rec.manifest.runnables]
            empty_hint = (
                " This skill has no declared runnables — use run_skill_script with a "
                "declared script path instead."
                if not known_runnables
                else ""
            )
            return failure_envelope(
                SKILL_VALIDATION,
                f"unknown runnable `{runnable_id}` for skill `{name}`; "
                f"declared runnables: {known_runnables if known_runnables else '[]'}"
                f"{empty_hint}",
            )
        if entry.language != "python":
            return failure_envelope(
                SKILL_RUNNABLE_UNSUPPORTED,
                f"runnable language `{entry.language}` is not implemented (v1: python only)",
            )
        code = entry.source_body.strip()
        if not code:
            return failure_envelope(
                SKILL_VALIDATION,
                "runnable has no inline python body (use ## Inline runnables fence)",
            )
        wall = rec.manifest.max_wall_seconds or DEFAULT_SKILL_MAX_WALL_SECONDS
        abortable = bool(entry.abortable) if isinstance(entry.abortable, bool) else True
        tmp = rec.skill_dir / ".sevn-runnable-tmp"
        tmp.mkdir(exist_ok=True)
        fn = tmp / f"run-{runnable_id}-{uuid.uuid4().hex[:8]}.py"
        fn.write_text(
            f"{code}\n",
            encoding="utf-8",
        )
        try:
            payload = json.dumps(dict(params or {}), ensure_ascii=False)
            env_extra = {"SEVN_RUNNABLE_PARAMS": payload}
            argv = [sys.executable, str(fn)]
            return await self._run_subprocess(
                rec,
                argv,
                label_path=str(fn.relative_to(rec.skill_dir)),
                runnable_id=runnable_id,
                wall_s=float(wall),
                abortable=abortable,
                env_extra=env_extra,
            )
        finally:
            with contextlib.suppress(OSError):
                fn.unlink(missing_ok=True)

    async def _run_subprocess(
        self,
        rec: SkillRecord,
        argv: list[str],
        *,
        label_path: str,
        runnable_id: str | None,
        wall_s: float,
        abortable: bool,
        env_extra: dict[str, str] | None = None,
        session_id: str = "",
        artifact_output_prefix: str = "",
    ) -> dict[str, object]:
        """Run a skill subprocess with a shadow workspace and JSON-stdout contract.
        Args:
            rec (SkillRecord): Resolved skill record.
            argv (list[str]): Process argv (including interpreter).
            label_path (str): Manifest-relative label used in trace attrs.
            runnable_id (str | None): Runnable id when applicable, else ``None``.
            wall_s (float): Wall-clock timeout in seconds.
            abortable (bool): Whether the script/runnable is safe to cancel mid-run.
            env_extra (dict[str, str] | None, optional): Extra env vars merged on top
                of the base subprocess env. Defaults to ``None``.
            session_id (str, optional): Gateway session id for per-session output
                subfolders. Defaults to ``""``.
            artifact_output_prefix (str, optional): Workspace-relative artifact
                output prefix injected into the subprocess environment.
        Returns:
            dict[str, object]: Tool envelope; ``TOOL_TIMEOUT`` on wall-clock exceedance,
                ``SKILL_SCRIPT_NONZERO`` on non-zero exit, ``SKILL_INVALID_JSON`` when
                stdout cannot be parsed.
        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(SkillsManager._run_subprocess)
            True
        """
        shadow_parent = self._shadow_parent()
        shadow_parent.mkdir(parents=True, exist_ok=True)
        shadow_dir = shadow_parent / f"sh-{uuid.uuid4().hex[:12]}"
        ts_start = time.time_ns()
        proc: asyncio.subprocess.Process | None = None
        out = b""
        err = b""
        try:
            materialize_shadow_workspace(self._workspace_root, shadow_dir, clear=True)
            assert_shadow_workspace_excludes_llmignore(shadow_dir)
            env = self._build_proc_env(
                shadow_dir,
                rec.skill_dir,
                skill_name=rec.canonical_id,
                session_id=session_id,
                artifact_output_prefix=artifact_output_prefix,
            )
            if env_extra:
                env.update(env_extra)
            if rec.canonical_id == OPENWIKI_SKILL_ID:
                await merge_openwiki_proc_env(
                    env,
                    content_root=self._workspace_root,
                    cfg=self._config,
                )
            if rec.canonical_id in DISCOGS_SKILL_IDS:
                await merge_discogs_proc_env(
                    env,
                    content_root=self._workspace_root,
                    cfg=self._config,
                )
            proc = await asyncio.create_subprocess_exec(
                *argv,
                cwd=rec.skill_dir,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            if proc.stdout is None or proc.stderr is None:
                raise RuntimeError("asyncio subprocess PIPE streams missing")
            try:
                out, err = await asyncio.wait_for(proc.communicate(), timeout=wall_s)
            except TimeoutError:
                if proc.returncode is None:
                    proc.terminate()
                    with contextlib.suppress(ProcessLookupError, TimeoutError):
                        await asyncio.wait_for(proc.wait(), timeout=5.0)
                    if proc.returncode is None:
                        proc.kill()
                await _emit_skill(
                    self._trace_sink,
                    "skill.cancelled",
                    {
                        "skill_name": rec.canonical_id,
                        "path": label_path,
                        "runnable_id": runnable_id,
                        "abortable": abortable,
                        "signal_sent": "SIGTERM",
                        "cancel_source": "timeout",
                        "quarantine": rec.manifest.effective_quarantine(rec.provenance),
                    },
                )
                return failure_envelope(
                    TOOL_TIMEOUT,
                    f"skill subprocess exceeded wall timeout ({wall_s:.0f}s)",
                )
        finally:
            with contextlib.suppress(OSError):
                shutil.rmtree(shadow_dir, ignore_errors=True)
        elapsed_ms = max(1, int((time.time_ns() - ts_start) / 1_000_000))
        code = proc.returncode if proc else -1
        out_b = out
        err_b = err
        stdout_preview = out_b[:512].decode("utf-8", errors="replace")
        await _emit_skill(
            self._trace_sink,
            "skill.run",
            {
                "skill_name": rec.canonical_id,
                "path": label_path,
                "runnable_id": runnable_id,
                "abortable": abortable,
                "exit_code": int(code if code is not None else -1),
                "bytes_stdout": stdout_preview,
                "duration_ms": elapsed_ms,
                "quarantine": rec.manifest.effective_quarantine(rec.provenance),
            },
        )
        try:
            data = _loads_single_json_object(out_b)
            parse_failed = False
        except (TypeError, ValueError, json.JSONDecodeError):
            data = {}
            parse_failed = True
        if code not in (0, None):
            tail = err_b.decode("utf-8", errors="replace")[-2000:]
            # A script may exit non-zero *and* emit its own structured failure
            # envelope on stdout (e.g. pdf.py -> {"ok":false,"code":"RENDER_FAILED",
            # "error":"WeasyPrint unavailable (missing native libs?) … run sevn
            # doctor"}). Prefer that actionable envelope over a bare stderr tail:
            # masking it left a live session looping ~20 min on an invisible error
            # (P3, plan/live-session-pdf-render-grounding-failures-plan.md). Carry
            # exit_code / stderr_tail in ``data`` for diagnostics.
            if not parse_failed and data.get("ok") is False:
                existing = data.get("data")
                diag: dict[str, object] = dict(existing) if isinstance(existing, dict) else {}
                diag["exit_code"] = code
                if tail:
                    diag["stderr_tail"] = tail
                data["data"] = diag
                return data
            extra = "; stdout was not valid JSON object" if parse_failed else ""
            msg = f"nonzero exit ({code}); stderr tail: {tail}{extra}"
            return failure_envelope(SKILL_SCRIPT_NONZERO, msg)
        if parse_failed:
            stderr_tail = err_b.decode("utf-8", errors="replace")[-2048:]
            return failure_envelope(
                SKILL_INVALID_JSON,
                "skill subprocess stdout was not a single JSON object",
                data={"stderr_tail": stderr_tail},
            )
        if "ok" in data and isinstance(data.get("ok"), bool):
            return data
        return success_envelope(data)

    def scaffold_generated_skill(
        self,
        name: str,
        description: str,
        *,
        version: str = "0.1.0",
        create_scripts_dir: bool = True,
    ) -> dict[str, object]:
        """Scaffold ``generated/<name>/`` with ``quarantine: true`` (`specs/12` §2.5).

        Args:
            name (str): Flat generated skill basename (no ``/`` separator).
            description (str): One-line Triager / index description.
            version (str, optional): Semver written to frontmatter. Defaults to ``"0.1.0"``.
            create_scripts_dir (bool, optional): When ``True``, create an empty ``scripts/``
                directory beside ``SKILL.md``. Defaults to ``True``.

        Returns:
            dict[str, object]: §3.1 success envelope with ``skill_name``, ``path``, and
                ``quarantine`` fields.

        Raises:
            SkillExecutionError: When ``name`` is non-flat, when more than one skills root is
                configured, or when the destination directory already exists.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(SkillsManager.scaffold_generated_skill)
            True
        """
        if "/" in name:
            msg = "scaffold_generated_skill accepts flat generated names only"
            raise SkillExecutionError(msg, code=SKILL_VALIDATION)
        if not name.strip():
            msg = "skill name must be non-empty"
            raise SkillExecutionError(msg, code=SKILL_VALIDATION)
        if len(self._skills_roots) != 1:
            msg = "scaffold requires a single skills root"
            raise SkillExecutionError(msg, code=SKILL_VALIDATION)
        base = self._skills_roots[0]
        dst = (base / "generated" / name).resolve()
        try:
            dst.relative_to(base.resolve())
        except ValueError:
            msg = "skill name escapes generated tree"
            raise SkillExecutionError(msg, code=SKILL_VALIDATION) from None
        if dst.exists():
            msg = f"generated skill already exists: {dst}"
            raise SkillExecutionError(msg, code=SKILL_VALIDATION)
        dst.mkdir(parents=True, exist_ok=False)
        if create_scripts_dir:
            (dst / "scripts").mkdir(parents=True, exist_ok=True)
        frontmatter: dict[str, object] = {
            "name": name,
            "description": description,
            "version": version,
            "quarantine": True,
            "scripts": [],
        }
        fm_yaml = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).rstrip() + "\n"
        body = f"# {name}\n\nGenerated skill scaffold.\n"
        (dst / "SKILL.md").write_text(f"---\n{fm_yaml}---\n{body}", encoding="utf-8")
        self.reload()
        rel_path = dst.relative_to(base)
        return success_envelope(
            {
                "skill_name": name,
                "path": str(rel_path),
                "quarantine": True,
            },
        )

    def promote_generated_to_user(self, skill_name: str) -> None:
        """Move ``generated/<name>/`` -> ``user/<name>/`` and bump registry (`specs/12` §2.5).
        Args:
            skill_name (str): Flat generated skill name (no ``/`` separator).
        Raises:
            SkillExecutionError: When ``skill_name`` is non-flat, when more than one
                skills root is configured, when the source path is missing, or when
                the destination already exists.
        Examples:
            >>> import inspect
            >>> inspect.isfunction(SkillsManager.promote_generated_to_user)
            True
        """
        if "/" in skill_name:
            msg = "promote_generated_to_user accepts flat generated names only"
            raise SkillExecutionError(msg, code=SKILL_VALIDATION)
        if len(self._skills_roots) != 1:
            msg = "promote requires a single skills root"
            raise SkillExecutionError(msg, code=SKILL_VALIDATION)
        base = self._skills_roots[0]
        src = (base / "generated" / skill_name).resolve()
        dst = (base / "user" / skill_name).resolve()
        if not src.is_dir():
            msg = f"missing generated skill directory: {src}"
            raise SkillExecutionError(msg, code=SKILL_NOT_FOUND)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            msg = f"user skill already exists: {dst}"
            raise SkillExecutionError(msg, code=SKILL_VALIDATION)
        shutil.move(str(src), str(dst))
        md = dst / "SKILL.md"
        if md.is_file():
            raw = md.read_text(encoding="utf-8")
            try:
                fm, body = split_frontmatter(raw)
                mapping = yaml.safe_load(fm) or {}
                if isinstance(mapping, dict):
                    mapping["quarantine"] = False
                    new_fm = (
                        yaml.safe_dump(
                            mapping,
                            sort_keys=False,
                            allow_unicode=True,
                        ).rstrip()
                        + "\n"
                    )
                    md.write_text(f"---\n{new_fm}---\n{body}", encoding="utf-8")
            except (SkillExecutionError, yaml.YAMLError, OSError):
                logger.opt(exception=True).warning(
                    "could not clear quarantine frontmatter for {}", dst
                )
        self.reload()
