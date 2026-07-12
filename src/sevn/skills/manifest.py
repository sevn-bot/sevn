"""Parse ``SKILL.md`` YAML frontmatter + runnable fence metadata (specs 12 §3.1-§3.3).

Module: sevn.skills.manifest
Depends: pathlib, typing, yaml, json, re, sevn.skills.errors

Exports:
    Classes:
        SkillManifest — Validated frontmatter + merged runnable entries.
        SkillScriptEntry — One ``scripts:`` manifest row.
        RunnableEntry — One runnable shim target (fence or YAML).
    Functions:
        split_frontmatter — Split ``SKILL.md`` text into YAML and body.
        manifest_from_mapping — Build a ``SkillManifest`` from a YAML dict.
        infer_abortable_for_script — Default ``abortable`` from path heuristics.
        parse_skill_markdown — Strict ``SKILL.md`` -> ``SkillManifest`` parser.
        downgrade_manifest — Lenient parser for ``user`` skills only.
        validate_script_paths — Assert manifest script paths exist on disk.
        required_positional_arg_count — Count required ``<placeholder>`` argv slots.
        validate_script_argv — Pre-flight argv check from ``args_overview``.

Examples:
    >>> from pathlib import Path
    >>> bool(Path("."))
    True
"""

from __future__ import annotations

import itertools
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import yaml

from sevn.skills.errors import SKILL_VALIDATION, SkillExecutionError

if TYPE_CHECKING:
    from sevn.skills.models import ProvenanceKind

_INLINE_RUNNABLE_HEADER: Final[re.Pattern[str]] = re.compile(
    r"^\s*#\s*sevn-runnable:\s*(?P<meta>\{.+\})\s*\r?$",
)
_OPTIONAL_ARG_SEGMENT: Final[re.Pattern[str]] = re.compile(r"\[[^\]]*\]")
_REQUIRED_PLACEHOLDER: Final[re.Pattern[str]] = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class SkillScriptEntry:
    """One declared script callable."""

    path: str
    description: str
    args_overview: str | None = None
    abortable: bool | None = None
    python_version: str | None = None


@dataclass(frozen=True)
class RunnableEntry:
    """Runnable extracted from YAML and/or fenced body blocks."""

    runnable_id: str
    description: str
    language: str
    parameters: list[object]
    schema_version: int = 1
    source_body: str = ""
    """Fence body excluding the metadata comment line."""

    abortable: bool | None = None


@dataclass
class SkillManifest:
    """Authoring contract for ``SKILL.md``."""

    name: str
    description: str
    version: str
    scripts: tuple[SkillScriptEntry, ...] = ()
    see_also: tuple[str, ...] = ()
    runnables: tuple[RunnableEntry, ...] = ()
    python_version: str | None = None
    max_wall_seconds: int | None = None
    quarantine_flag: bool | None = None

    def effective_quarantine(self, provenance: ProvenanceKind) -> bool:
        """Return runtime quarantine (default ``True`` under ``generated/``).

        Args:
            provenance (ProvenanceKind): Skill tree kind.

        Returns:
            bool: When ``True``, subprocess runners must refuse execution.

        Examples:
            >>> m = SkillManifest(name="x", description="d", version="1.0.0")
            >>> m.effective_quarantine("generated")
            True
        """
        if self.quarantine_flag is not None:
            return bool(self.quarantine_flag)
        return provenance == "generated"


def split_frontmatter(markdown_raw: str) -> tuple[str, str]:
    r"""Split ``SKILL.md`` into YAML blob and markdown body.

    Args:
        markdown_raw (str): Full UTF-8 text.

    Returns:
        tuple[str, str]: Frontmatter YAML without delimiters and trailing body.

    Raises:
        SkillExecutionError: When delimiters are missing.

    Examples:
        >>> split_frontmatter("---\nname: a\n---\nb") == ("\nname: a", "b")
        True
    """
    stripped = markdown_raw.lstrip("\ufeff")
    if not stripped.startswith("---"):
        msg = "SKILL.md must start with YAML frontmatter delimiter ---"
        raise SkillExecutionError(msg, code=SKILL_VALIDATION)
    end = stripped.find("\n---", 3)
    if end == -1:
        msg = "SKILL.md frontmatter missing closing ---"
        raise SkillExecutionError(msg, code=SKILL_VALIDATION)
    fm_yaml = stripped[3:end]
    body = stripped[end + 4 :].lstrip("\n")
    return fm_yaml, body


def _coerce_scripts(raw: object) -> tuple[SkillScriptEntry, ...]:
    """Coerce raw ``scripts:`` YAML payload into validated ``SkillScriptEntry`` tuples.

    Args:
        raw (object): Decoded YAML value (typically ``list[dict[str, Any]]`` or ``None``).

    Returns:
        tuple[SkillScriptEntry, ...]: Validated script rows in source order.

    Raises:
        SkillExecutionError: When the row shape or required keys are invalid.

    Examples:
        >>> _coerce_scripts(None)
        ()
        >>> rows = _coerce_scripts([{"path": "scripts/a.py", "description": "do a"}])
        >>> rows[0].path
        'scripts/a.py'
    """
    if raw is None:
        return ()
    if not isinstance(raw, list):
        msg = "`scripts:` must be a list when present"
        raise SkillExecutionError(msg, code=SKILL_VALIDATION)
    rows: list[SkillScriptEntry] = []
    for i, row in enumerate(raw):
        if not isinstance(row, dict):
            raise SkillExecutionError(
                f"scripts[{i}] must be an object mapping",
                code=SKILL_VALIDATION,
            )
        path = row.get("path")
        description = row.get("description")
        if not isinstance(path, str) or not path.strip():
            raise SkillExecutionError(
                f"scripts[{i}].path is required",
                code=SKILL_VALIDATION,
            )
        if not isinstance(description, str) or not description.strip():
            raise SkillExecutionError(
                f"scripts[{i}].description must be non-empty",
                code=SKILL_VALIDATION,
            )
        ao = row.get("args_overview")
        pv = row.get("python_version")
        ab_raw = row.get("abortable")
        ab = bool(ab_raw) if isinstance(ab_raw, bool) else None
        rows.append(
            SkillScriptEntry(
                path=path.strip(),
                description=description.strip(),
                args_overview=ao.strip() if isinstance(ao, str) and ao.strip() else None,
                abortable=ab,
                python_version=pv.strip() if isinstance(pv, str) and pv.strip() else None,
            )
        )
    return tuple(rows)


def _coerce_yaml_runnables(raw: object) -> tuple[RunnableEntry, ...]:
    """Coerce raw ``runnables:`` YAML payload into validated ``RunnableEntry`` tuples.

    Args:
        raw (object): Decoded YAML value (typically ``list[dict[str, Any]]`` or ``None``).

    Returns:
        tuple[RunnableEntry, ...]: Validated runnable rows in source order.

    Raises:
        SkillExecutionError: When the row shape or required keys are invalid.

    Examples:
        >>> _coerce_yaml_runnables(None)
        ()
        >>> rows = _coerce_yaml_runnables(
        ...     [{"id": "r1", "description": "hi", "language": "python"}]
        ... )
        >>> rows[0].runnable_id
        'r1'
    """
    if raw is None:
        return ()
    if not isinstance(raw, list):
        msg = "`runnables:` must be a list when present"
        raise SkillExecutionError(msg, code=SKILL_VALIDATION)
    rows: list[RunnableEntry] = []
    for i, row in enumerate(raw):
        if not isinstance(row, dict):
            raise SkillExecutionError(
                f"runnables[{i}] must be an object mapping",
                code=SKILL_VALIDATION,
            )
        rid = row.get("id")
        desc = row.get("description")
        lang = row.get("language", "python")
        if not isinstance(rid, str) or not rid.strip():
            raise SkillExecutionError(
                f"runnables[{i}].id is required",
                code=SKILL_VALIDATION,
            )
        if not isinstance(desc, str) or not desc.strip():
            raise SkillExecutionError(
                f"runnables[{i}].description must be non-empty",
                code=SKILL_VALIDATION,
            )
        if not isinstance(lang, str) or not lang.strip():
            raise SkillExecutionError(
                f"runnables[{i}].language must be non-empty when set",
                code=SKILL_VALIDATION,
            )
        params = row.get("parameters", [])
        if not isinstance(params, list):
            raise SkillExecutionError(
                f"runnables[{i}].parameters must be a list",
                code=SKILL_VALIDATION,
            )
        sch = row.get("schema_version", 1)
        if not isinstance(sch, int):
            raise SkillExecutionError(
                f"runnables[{i}].schema_version must be integer",
                code=SKILL_VALIDATION,
            )
        sb = row.get("source_body", "")
        if not isinstance(sb, str):
            raise SkillExecutionError(
                f"runnables[{i}].source_body must be a string when set",
                code=SKILL_VALIDATION,
            )
        ab_raw = row.get("abortable")
        ab = bool(ab_raw) if isinstance(ab_raw, bool) else None
        rows.append(
            RunnableEntry(
                runnable_id=rid.strip(),
                description=desc.strip(),
                language=lang.strip().lower(),
                parameters=params,
                schema_version=int(sch),
                source_body=sb,
                abortable=ab,
            )
        )
    return tuple(rows)


def _parse_inline_runnables(body: str) -> tuple[RunnableEntry, ...]:
    """Extract runnable metadata from fenced code under ``## Inline runnables``.

    Args:
        body (str): Markdown body of ``SKILL.md`` (frontmatter excluded).

    Returns:
        tuple[RunnableEntry, ...]: Inline runnables in source order, empty when
            the section or fences are absent.

    Raises:
        SkillExecutionError: When a fence header has invalid JSON or fields.

    Examples:
        >>> _parse_inline_runnables("body without runnables section")
        ()
    """
    ix = body.find("## Inline runnables")
    if ix == -1:
        return ()
    section = body[ix:]
    out: list[RunnableEntry] = []
    fences = list(re.finditer(r"^\s*(?P<fence>`{3,})([^`\n]*)$", section, flags=re.MULTILINE))
    for left, right in itertools.pairwise(fences):
        opening = left.group("fence")
        if len(opening) < 3:
            continue
        inner_start = left.end()
        inner_end = right.start()
        block_lines = section[inner_start:inner_end].strip("\n").splitlines()
        if not block_lines:
            continue
        m = _INLINE_RUNNABLE_HEADER.match(block_lines[0])
        if not m:
            continue
        try:
            meta = json.loads(m.group("meta"))
        except json.JSONDecodeError as exc:
            msg = "invalid sevn-runnable JSON metadata"
            raise SkillExecutionError(msg, code=SKILL_VALIDATION) from exc
        if not isinstance(meta, dict):
            raise SkillExecutionError("sevn-runnable meta must be an object", code=SKILL_VALIDATION)
        rid_raw = meta.get("id")
        desc_raw = meta.get("description")
        lang_raw = meta.get("language", "python")
        params = meta.get("parameters", [])
        sch_raw = meta.get("schema_version", 1)
        if not isinstance(rid_raw, str) or not rid_raw.strip():
            raise SkillExecutionError("sevn-runnable id required", code=SKILL_VALIDATION)
        if not isinstance(desc_raw, str) or not desc_raw.strip():
            raise SkillExecutionError("sevn-runnable description required", code=SKILL_VALIDATION)
        if not isinstance(lang_raw, str) or not lang_raw.strip():
            raise SkillExecutionError("sevn-runnable language invalid", code=SKILL_VALIDATION)
        if not isinstance(params, list):
            raise SkillExecutionError(
                "sevn-runnable parameters must be list", code=SKILL_VALIDATION
            )
        if not isinstance(sch_raw, int):
            raise SkillExecutionError(
                "sevn-runnable schema_version must be int",
                code=SKILL_VALIDATION,
            )
        remainder = "\n".join(block_lines[1:])
        rid = rid_raw.strip()
        if any(e.runnable_id == rid for e in out):
            raise SkillExecutionError(
                f"duplicate runnable id from fences: {rid}",
                code=SKILL_VALIDATION,
            )
        out.append(
            RunnableEntry(
                runnable_id=rid,
                description=desc_raw.strip(),
                language=lang_raw.strip().lower(),
                parameters=params,
                schema_version=int(sch_raw),
                source_body=remainder,
                abortable=None,
            )
        )
    return tuple(out)


def manifest_from_mapping(
    data: dict[str, Any],
    *,
    body: str,
    provenance: ProvenanceKind,
) -> SkillManifest:
    """Build manifest from YAML dict + markdown body-derived runnables.

    Args:
        data (dict[str, Any]): Decoded YAML frontmatter mapping.
        body (str): Markdown body text (after frontmatter) used to scan inline runnables.
        provenance (ProvenanceKind): Skill tree provenance.

    Returns:
        SkillManifest: Validated manifest with merged YAML + inline runnables.

    Raises:
        SkillExecutionError: On core ``runnables`` presence or malformed fields.

    Examples:
        >>> m = manifest_from_mapping(
        ...     {"name": "x", "description": "d", "version": "1.0.0"},
        ...     body="",
        ...     provenance="user",
        ... )
        >>> m.name
        'x'
    """
    name_raw = data.get("name")
    desc_raw = data.get("description")
    ver_raw = data.get("version")
    if not isinstance(name_raw, str) or not name_raw.strip():
        raise SkillExecutionError("`name:` is required in frontmatter", code=SKILL_VALIDATION)
    if not isinstance(desc_raw, str) or not desc_raw.strip():
        raise SkillExecutionError(
            "`description:` is required in frontmatter", code=SKILL_VALIDATION
        )
    if not isinstance(ver_raw, str) or not ver_raw.strip():
        raise SkillExecutionError("`version:` is required in frontmatter", code=SKILL_VALIDATION)
    if provenance == "core":
        core_r = data.get("runnables")
        if isinstance(core_r, list) and len(core_r) > 0:
            raise SkillExecutionError(
                "`runnables` are disallowed under workspace/skills/core",
                code=SKILL_VALIDATION,
            )
        fence_r = _parse_inline_runnables(body)
        if fence_r:
            raise SkillExecutionError(
                "inline runnable fences disallowed under workspace/skills/core",
                code=SKILL_VALIDATION,
            )
        runns: tuple[RunnableEntry, ...] = ()
    else:
        yaml_r = _coerce_yaml_runnables(data.get("runnables"))
        fence_r = _parse_inline_runnables(body)
        by_id = {r.runnable_id: r for r in yaml_r}
        for fr in fence_r:
            by_id.setdefault(fr.runnable_id, fr)
        runns = tuple(by_id[runnable_id] for runnable_id in sorted(by_id.keys()))
    pv = data.get("python_version")
    mxs = data.get("max_wall_seconds")
    mq = data.get("quarantine")
    see_raw = data.get("see_also")
    if see_raw is None:
        see_tuple: tuple[str, ...] = ()
    elif not isinstance(see_raw, list) or any(not isinstance(s, str) for s in see_raw):
        raise SkillExecutionError(
            "`see_also` must be a list[str] when present", code=SKILL_VALIDATION
        )
    else:
        see_tuple = tuple(str(s).strip() for s in see_raw if str(s).strip())
    mq_flag: bool | None = mq if isinstance(mq, bool) else None
    max_wall_i: int | None = None
    if isinstance(mxs, int) and mxs > 0:
        max_wall_i = mxs
    pyv = pv.strip() if isinstance(pv, str) and pv.strip() else None
    scripts_part = _coerce_scripts(data.get("scripts"))
    return SkillManifest(
        name=name_raw.strip(),
        description=desc_raw.strip(),
        version=ver_raw.strip(),
        scripts=scripts_part,
        see_also=see_tuple,
        runnables=runns,
        python_version=pyv,
        max_wall_seconds=max_wall_i,
        quarantine_flag=mq_flag,
    )


def infer_abortable_for_script(rel_path: str, explicit: bool | None) -> bool:
    """Default ``abortable`` when YAML omits the flag (minimal basename heuristic).

    Args:
        rel_path (str): Script path relative to its skill directory.
        explicit (bool | None): Manifest-declared override; wins when not ``None``.

    Returns:
        bool: ``True`` when scripts may be cancelled mid-run, ``False`` for
            risky verbs in the basename (``delete``, ``send``, ``wipe``, ...).

    Examples:
        >>> infer_abortable_for_script("scripts/safe.py", None)
        True
        >>> infer_abortable_for_script("scripts/send_email.py", None)
        False
        >>> infer_abortable_for_script("scripts/send_email.py", True)
        True
    """
    if explicit is not None:
        return bool(explicit)
    slug = Path(rel_path).name.lower()
    risk_tokens = (
        "destroy",
        "delete",
        "purge",
        "exfil",
        "send",
        "tweet",
        "post",
        "purchase",
        "wipe",
    )
    return not any(tok in slug for tok in risk_tokens)


def parse_skill_markdown(text: str, provenance: ProvenanceKind) -> SkillManifest:
    """Parse YAML + body -> ``SkillManifest`` (strict).

    Args:
        text (str): Full UTF-8 ``SKILL.md`` text including frontmatter delimiters.
        provenance (ProvenanceKind): Skill tree provenance kind.

    Returns:
        SkillManifest: Strictly validated manifest.

    Raises:
        SkillExecutionError: On YAML parse errors or invalid frontmatter shape.

    Examples:
        >>> m = parse_skill_markdown(
        ...     "---\\nname: x\\ndescription: d\\nversion: 1.0.0\\n---\\n",
        ...     "user",
        ... )
        >>> m.version
        '1.0.0'
    """
    try:
        fm_yaml, body = split_frontmatter(text)
        mapping = yaml.safe_load(fm_yaml) or {}
    except yaml.YAMLError as exc:
        msg = "SKILL.md frontmatter YAML parse error"
        raise SkillExecutionError(msg, code=SKILL_VALIDATION) from exc
    if not isinstance(mapping, dict):
        msg = "SKILL.md frontmatter must deserialize to an object mapping"
        raise SkillExecutionError(msg, code=SKILL_VALIDATION)
    return manifest_from_mapping(mapping, body=body, provenance=provenance)


def downgrade_manifest(
    skill_dir_name: str, text: str, provenance: ProvenanceKind
) -> tuple[SkillManifest, tuple[str, ...]]:
    """Lenient manifest for ``user`` skills only (narrow scope).

    Args:
        skill_dir_name (str): Filesystem name of the skill directory; used as
            fallback ``name`` when frontmatter parsing fails or mismatches.
        text (str): Full ``SKILL.md`` text.
        provenance (ProvenanceKind): Must be ``"user"``; otherwise an error is raised.

    Returns:
        tuple[SkillManifest, tuple[str, ...]]: Tolerant manifest plus a tuple of
            non-fatal warning strings (empty when strict parse succeeded).

    Raises:
        SkillExecutionError: When called with a non-user provenance.

    Examples:
        >>> m, errs = downgrade_manifest("demo", "not yaml at all", "user")
        >>> m.name
        'demo'
        >>> len(errs) >= 1
        True
    """
    if provenance != "user":
        msg = "downgrade_manifest applies only to user skills"
        raise SkillExecutionError(msg, code=SKILL_VALIDATION)
    try:
        m = parse_skill_markdown(text, provenance)
    except (SkillExecutionError, yaml.YAMLError) as exc:
        m = SkillManifest(
            name=skill_dir_name,
            description=skill_dir_name,
            version="0.0.0",
        )
        return m, (str(exc),)
    errs: list[str] = []
    if m.name.strip() != skill_dir_name.strip():
        errs.append("frontmatter `name:` does not match directory; using filesystem name for index")
        m = SkillManifest(
            name=skill_dir_name,
            description=m.description,
            version=m.version,
            scripts=m.scripts,
            see_also=m.see_also,
            runnables=m.runnables,
            python_version=m.python_version,
            max_wall_seconds=m.max_wall_seconds,
            quarantine_flag=m.quarantine_flag,
        )
    return m, tuple(errs)


def required_positional_arg_count(args_overview: str | None) -> int:
    """Count required positional argv slots declared in ``args_overview``.

    Treats ``<placeholder>`` tokens outside ``[...]`` optional segments as required.
    Flag-only overviews (``--query STR``) and ``(no args)`` yield ``0``.

    Args:
        args_overview (str | None): ``SKILL.md`` script ``args_overview`` string.

    Returns:
        int: Minimum positional ``argv`` length before invoking the script.

    Examples:
        >>> required_positional_arg_count("<url> [path] [--full-page]")
        1
        >>> required_positional_arg_count("[--tab <target_id>] <url>")
        1
        >>> required_positional_arg_count("[--force]")
        0
        >>> required_positional_arg_count("--query STR [--limit N]")
        0
    """
    if not args_overview or not args_overview.strip():
        return 0
    text = args_overview.strip()
    if text.lower() in {"(no args)", "no args"}:
        return 0
    stripped = _OPTIONAL_ARG_SEGMENT.sub("", text)
    return len(_REQUIRED_PLACEHOLDER.findall(stripped))


def validate_script_argv(
    entry: SkillScriptEntry,
    argv: Sequence[str] | None,
) -> str | None:
    """Return an error message when ``argv`` is too short for ``args_overview``.

    Args:
        entry (SkillScriptEntry): Manifest script row.
        argv (Sequence[str] | None): Positional args from ``run_skill_script``.

    Returns:
        str | None: Human-readable error, or ``None`` when argv satisfies the overview.

    Examples:
        >>> row = SkillScriptEntry(
        ...     path="scripts/capture.py",
        ...     description="navigate + screenshot",
        ...     args_overview="<url> [path] [--full-page]",
        ... )
        >>> validate_script_argv(row, []) is not None
        True
        >>> validate_script_argv(row, ["https://example.com"]) is None
        True
    """
    required = required_positional_arg_count(entry.args_overview)
    if required == 0:
        return None
    got = len(argv) if argv else 0
    if got >= required:
        return None
    overview = entry.args_overview or ""
    return (
        f"script `{entry.path}` requires at least {required} positional argv "
        f"element(s) but got {got}; pass values in run_skill_script.argv — "
        f"expected: {overview}"
    )


def validate_script_paths(skill_dir: Path, manifest: SkillManifest) -> None:
    """Fail when declared script paths lack backing files (**core**/CI gate).

    Args:
        skill_dir (Path): Directory containing ``SKILL.md`` and script files.
        manifest (SkillManifest): Parsed manifest with declared script rows.

    Raises:
        SkillExecutionError: When a declared script path is missing on disk.

    Examples:
        >>> from pathlib import Path
        >>> m = SkillManifest(name="x", description="d", version="1.0.0")
        >>> validate_script_paths(Path("/tmp"), m) is None
        True
    """
    for s in manifest.scripts:
        p = skill_dir / s.path
        if not p.is_file():
            msg = f"script path `{s.path}` is missing on disk relative to skill directory"
            raise SkillExecutionError(msg, code=SKILL_VALIDATION)
