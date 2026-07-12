"""Workspace skills subsystem (`specs/12-skills-system.md`).

Module: sevn.skills

Exports:
    SkillManifest — ``SKILL.md`` authoring contract (+ script/runnable entries).
    SkillScriptEntry — Manifest script row model.
    RunnableEntry — Runnable metadata / inline body hook.
    ProvenanceKind — ``core`` | ``user`` | ``generated`` | ``plugin``.
    SkillRecord — Resolved directory + manifest.
    SkillsIndex — name → picker line (+ ``see_also``).
    SkillsIndexBuilder — Builds ``SkillsIndex`` from ``SkillRecord`` map.
    SkillsManager.shared — Singleton registry keyed by workspace + roots tuple.
    build_skill_capability_rows — §2.3 ``capabilities[]`` rows.
    SkillExecutionError — Domain error with envelope ``code`` string.
    TOOL_TIMEOUT — Skill wall-clock timeout (**tools-spec** spelling).
    failure_envelope / success_envelope — Tool JSON fragments.
"""

from __future__ import annotations

from sevn.skills.capabilities import build_skill_capability_rows
from sevn.skills.errors import (
    QUARANTINE_SECURITY,
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
from sevn.skills.index import SkillsIndex, SkillsIndexBuilder
from sevn.skills.manager import SkillsManager
from sevn.skills.manifest import (
    RunnableEntry,
    SkillManifest,
    SkillScriptEntry,
    downgrade_manifest,
    infer_abortable_for_script,
    parse_skill_markdown,
    split_frontmatter,
    validate_script_paths,
)
from sevn.skills.models import ProvenanceKind, SkillRecord

__all__ = [
    "QUARANTINE_SECURITY",
    "SKILL_INVALID_JSON",
    "SKILL_NOT_FOUND",
    "SKILL_QUARANTINED",
    "SKILL_RUNNABLE_UNSUPPORTED",
    "SKILL_SCRIPT_ARGS",
    "SKILL_SCRIPT_NONZERO",
    "SKILL_SCRIPT_UNKNOWN",
    "SKILL_VALIDATION",
    "TOOL_TIMEOUT",
    "ProvenanceKind",
    "RunnableEntry",
    "SkillExecutionError",
    "SkillManifest",
    "SkillRecord",
    "SkillScriptEntry",
    "SkillsIndex",
    "SkillsIndexBuilder",
    "SkillsManager",
    "build_skill_capability_rows",
    "downgrade_manifest",
    "failure_envelope",
    "infer_abortable_for_script",
    "parse_skill_markdown",
    "split_frontmatter",
    "success_envelope",
    "validate_script_paths",
]
