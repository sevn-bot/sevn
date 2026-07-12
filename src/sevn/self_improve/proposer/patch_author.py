"""Patch author routing, validation, and artefact writes (`specs/33-self-improvement.md` §4.1).

Module: sevn.self_improve.proposer.patch_author
Depends: difflib, fnmatch, json, os, pathlib, sevn.config.sections.self_improve,
    sevn.self_improve.proposer.agent, sevn.self_improve.proposer.context_loader,
    sevn.self_improve.proposer.prompt, sevn.self_improve.proposer.patch_author_stub

Exports:
    PatchAuthorResult — outcome of a patch authoring attempt.
    preset_requires_proposer — whether preset B/C runs the proposer stage.
    paths_in_unified_diff — extract target paths from unified diff text.
    reject_patch_glob_scope — fail when touched paths violate glob policy.
    reject_patch_policy — honour ``allow_*`` config flags on diff paths.
    resolve_patch_author_mode — fail closed on unknown ``patch_author`` values.
    proposer_budget_exhausted — daily token budget gate before LLM spend.
    author_patch_from_shortlist — async patch author entrypoint.
    write_patch_artefacts — persist ``patch/diff.patch`` under a job bundle.
"""

from __future__ import annotations

import difflib
import fnmatch
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path  # noqa: TC003 — runtime job bundle and ledger paths
from typing import TYPE_CHECKING, Any, Literal

from sevn.config.sections.self_improve import SelfImproveWorkspaceConfig  # noqa: TC001

if TYPE_CHECKING:
    from sevn.agent.tracing.sink import TraceSink
    from sevn.config.settings import ProcessSettings
    from sevn.config.workspace_config import WorkspaceConfig
    from sevn.workspace.layout import WorkspaceLayout

DEFAULT_ALLOWED_GLOBS: tuple[str, ...] = (
    "workspace/prompts/**",
    "workspace/skills/**",
)

PATCH_AUTHOR_MODES: frozenset[str] = frozenset({"pydantic_agent"})
PatchAuthorMode = Literal["pydantic_agent"]

_PRESET_RANK: dict[str, int] = {"A": 0, "B": 1, "C": 2}
_CONFIG_PATH_MARKERS: tuple[str, ...] = (
    "sevn.json",
    "infra/sevn.schema.json",
)
_DEPENDENCY_PATH_MARKERS: tuple[str, ...] = (
    "pyproject.toml",
    "uv.lock",
    "requirements.txt",
    "requirements-dev.txt",
)
_LCM_PATH_PREFIXES: tuple[str, ...] = ("workspace/memory/",)


@dataclass(frozen=True, slots=True)
class PatchAuthorResult:
    """Outcome of patch authoring."""

    ok: bool
    diff: str
    target_path: str | None
    rejection: str | None = None
    author: str | None = None


def preset_requires_proposer(preset: str) -> bool:
    """Return whether the improve preset runs the proposer before eval.

    Args:
        preset (str): Job preset label (``A``, ``B``, or ``C``).

    Returns:
        bool: ``True`` for preset **B** and **C**.

    Examples:
        >>> preset_requires_proposer("A")
        False
        >>> preset_requires_proposer("B")
        True
    """
    return _PRESET_RANK.get(preset, 0) >= _PRESET_RANK["B"]


def resolve_patch_author_mode(value: str | None) -> PatchAuthorMode:
    """Resolve configured ``patch_author`` enum — fail closed when unknown.

    Args:
        value (str | None): Raw config value.

    Returns:
        PatchAuthorMode: Supported author mode.

    Raises:
        ValueError: When ``value`` is not a supported mode.

    Examples:
        >>> resolve_patch_author_mode("pydantic_agent")
        'pydantic_agent'
        >>> try:
        ...     resolve_patch_author_mode("claude_sdk")
        ... except ValueError:
        ...     True
        ... else:
        ...     False
        True
    """
    mode = (value or "pydantic_agent").strip()
    if mode not in PATCH_AUTHOR_MODES:
        msg = f"unsupported self_improve.patch_author mode: {mode!r}"
        raise ValueError(msg)
    return mode  # type: ignore[return-value]


def paths_in_unified_diff(diff: str) -> list[str]:
    """Collect file paths referenced by ``+++`` hunk headers.

    Args:
        diff (str): Unified diff text.

    Returns:
        list[str]: Normalised paths (no ``a/`` / ``b/`` prefix, no timestamp suffix).

    Examples:
        >>> paths_in_unified_diff("+++ b/workspace/prompts/x.md\\n")
        ['workspace/prompts/x.md']
    """
    paths: list[str] = []
    for line in diff.splitlines():
        if not line.startswith("+++"):
            continue
        raw = line[4:].strip()
        if raw.startswith("b/"):
            raw = raw[2:]
        if raw in ("/dev/null", "dev/null"):
            continue
        if "\t" in raw:
            raw = raw.split("\t", 1)[0]
        if raw:
            paths.append(raw)
    return paths


def _path_matches_any(path: str, patterns: list[str]) -> bool:
    """Return whether ``path`` matches any ``fnmatch`` pattern in ``patterns``.

    Args:
        path (str): Normalised or raw file path.
        patterns (list[str]): Glob patterns to test.

    Returns:
        bool: ``True`` when at least one pattern matches.

    Examples:
        >>> _path_matches_any("workspace/prompts/x.md", ["workspace/prompts/**"])
        True
    """
    normalised = path.replace("\\", "/")
    return any(fnmatch.fnmatch(normalised, pattern) for pattern in patterns)


def reject_patch_glob_scope(
    diff: str,
    *,
    allowed_globs: list[str],
    deny_globs: list[str] | None = None,
) -> str | None:
    """Reject diffs that touch paths outside ``allowed_globs`` or inside ``deny_globs``.

    Args:
        diff (str): Unified diff text.
        allowed_globs (list[str]): Allowlist patterns (``fnmatch`` semantics).
        deny_globs (list[str] | None): Optional deny patterns checked first.

    Returns:
        str | None: Human-readable rejection reason, or ``None`` when allowed.

    Examples:
        >>> reject_patch_glob_scope(
        ...     "+++ b/src/hack.py\\n",
        ...     allowed_globs=["workspace/prompts/**"],
        ... ) is not None
        True
    """
    touched = paths_in_unified_diff(diff)
    if not touched:
        return "patch_rejected_scope: no file paths in diff"
    deny = deny_globs or []
    for path in touched:
        for pattern in deny:
            if _path_matches_any(path, [pattern]):
                return f"patch_rejected_scope: path {path!r} matches deny glob {pattern!r}"
        if not _path_matches_any(path, allowed_globs):
            return f"patch_rejected_scope: path {path!r} outside allowed_globs"
    return None


def reject_patch_policy(
    diff: str,
    *,
    allow_config_changes: bool,
    allow_dependency_changes: bool,
    allow_lcm_memory_changes: bool,
) -> str | None:
    """Reject diffs that violate ``allow_*`` self-improve policy flags.

    Args:
        diff (str): Unified diff text.
        allow_config_changes (bool): Permit ``sevn.json`` / schema edits.
        allow_dependency_changes (bool): Permit dependency manifest edits.
        allow_lcm_memory_changes (bool): Permit LCM memory path edits.

    Returns:
        str | None: Human-readable rejection reason, or ``None`` when allowed.

    Examples:
        >>> reject_patch_policy(
        ...     "+++ b/sevn.json\\n",
        ...     allow_config_changes=False,
        ...     allow_dependency_changes=False,
        ...     allow_lcm_memory_changes=False,
        ... ) is not None
        True
    """
    for path in paths_in_unified_diff(diff):
        normalised = path.replace("\\", "/")
        base = normalised.rsplit("/", 1)[-1]
        if not allow_config_changes and (
            base in _CONFIG_PATH_MARKERS or normalised in _CONFIG_PATH_MARKERS
        ):
            return (
                f"patch_rejected_policy: config path {path!r} blocked (allow_config_changes=false)"
            )
        if not allow_dependency_changes and (
            base in _DEPENDENCY_PATH_MARKERS or normalised in _DEPENDENCY_PATH_MARKERS
        ):
            return (
                f"patch_rejected_policy: dependency path {path!r} blocked "
                "(allow_dependency_changes=false)"
            )
        if not allow_lcm_memory_changes and any(
            normalised.startswith(prefix) for prefix in _LCM_PATH_PREFIXES
        ):
            return (
                f"patch_rejected_policy: lcm memory path {path!r} blocked "
                "(allow_lcm_memory_changes=false)"
            )
    return None


def _resolve_allowed_globs(allowed_globs: list[str] | None) -> list[str]:
    """Return configured allowlist or shipped ``DEFAULT_ALLOWED_GLOBS``.

    Args:
        allowed_globs (list[str] | None): Workspace override from job config.

    Returns:
        list[str]: Effective allowlist patterns.

    Examples:
        >>> _resolve_allowed_globs(None) == list(DEFAULT_ALLOWED_GLOBS)
        True
    """
    if allowed_globs:
        return list(allowed_globs)
    return list(DEFAULT_ALLOWED_GLOBS)


def _deterministic_target_path(*, job_id: str, allowed_globs: list[str]) -> str | None:
    """Pick the first candidate path that satisfies ``allowed_globs``.

    Args:
        job_id (str): Improve job id used for slug generation.
        allowed_globs (list[str]): Effective allowlist patterns.

    Returns:
        str | None: Target path under allowlist, or ``None`` when none match.

    Examples:
        >>> _deterministic_target_path(job_id="job-1", allowed_globs=["workspace/prompts/**"])
        'workspace/prompts/seimprove-job1.md'
    """
    slug = job_id.replace("-", "")[:12] or "job"
    candidates = (
        f"workspace/prompts/seimprove-{slug}.md",
        f"workspace/skills/seimprove-{slug}.md",
        "src/sevn/self_improve/README-stub.md",
    )
    for path in candidates:
        if _path_matches_any(path, allowed_globs):
            return path
    return None


def _shortlist_summary(shortlist: dict[str, Any]) -> dict[str, Any]:
    """Summarise shortlist JSON for deterministic patch body metadata.

    Args:
        shortlist (dict[str, Any]): Parsed ``shortlist.json`` payload.

    Returns:
        dict[str, Any]: ``candidate_count`` and ``top_turn_ids`` keys.

    Examples:
        >>> _shortlist_summary({"candidates": [{"turn_id": "t1"}]})
        {'candidate_count': 1, 'top_turn_ids': ['t1']}
    """
    raw_candidates = shortlist.get("candidates")
    if not isinstance(raw_candidates, list):
        return {"candidate_count": 0, "top_turn_ids": []}
    turn_ids: list[str] = []
    for row in raw_candidates[:5]:
        if isinstance(row, dict) and isinstance(row.get("turn_id"), str):
            turn_ids.append(row["turn_id"])
    return {"candidate_count": len(raw_candidates), "top_turn_ids": turn_ids}


def _parse_token_budget_daily(value: str | int) -> int:
    """Parse ``eval.token_budget_daily`` human suffixes into token counts.

    Args:
        value (str | int): Configured budget string or integer.

    Returns:
        int: Parsed daily token budget.

    Examples:
        >>> _parse_token_budget_daily("100k")
        100000
        >>> _parse_token_budget_daily(500)
        500
    """
    if isinstance(value, int):
        return max(0, value)
    raw = value.strip().lower().replace("_", "")
    multiplier = 1
    if raw.endswith("k"):
        multiplier = 1_000
        raw = raw[:-1]
    elif raw.endswith("m"):
        multiplier = 1_000_000
        raw = raw[:-1]
    try:
        return max(0, int(float(raw) * multiplier))
    except ValueError:
        return 0


def _budget_ledger_path(layout: WorkspaceLayout) -> Path:
    """Return the daily token ledger path under ``.sevn/improve/``.

    Args:
        layout (WorkspaceLayout): Resolved workspace layout.

    Returns:
        Path: Ledger JSON path.

    Examples:
        >>> _budget_ledger_path.__name__
        '_budget_ledger_path'
    """
    return layout.dot_sevn / "improve" / "token_budget_daily.json"


def proposer_budget_exhausted(
    workspace: WorkspaceConfig,
    layout: WorkspaceLayout,
) -> bool:
    """Return whether the daily proposer token budget is exhausted.

    Args:
        workspace (WorkspaceConfig): Parsed workspace configuration.
        layout (WorkspaceLayout): Resolved filesystem layout.

    Returns:
        bool: ``True`` when spend meets or exceeds ``eval.token_budget_daily``.

    Examples:
        >>> from pathlib import Path
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> from sevn.workspace.layout import WorkspaceLayout
        >>> ws = WorkspaceConfig.minimal(self_improve={"enabled": True, "eval": {"token_budget_daily": "100k"}})
        >>> ly = WorkspaceLayout(Path("/tmp/x/sevn.json"), Path("/tmp/x"))
        >>> proposer_budget_exhausted(ws, ly)
        False
    """
    si = workspace.self_improve
    if si is None or si.eval is None:
        return False
    limit = _parse_token_budget_daily(si.eval.token_budget_daily)
    if limit <= 0:
        return True
    ledger_path = _budget_ledger_path(layout)
    if not ledger_path.is_file():
        return False
    try:
        payload = json.loads(ledger_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    if not isinstance(payload, dict):
        return False
    today = datetime.now(tz=UTC).date().isoformat()
    if payload.get("date") != today:
        return False
    used = payload.get("tokens_used")
    if not isinstance(used, int):
        return False
    return used >= limit


def _content_to_unified_diff(*, target_path: str, content: str) -> str:
    """Build a new-file unified diff from full ``content`` text.

    Args:
        target_path (str): Destination repo-relative path.
        content (str): Full proposed file body.

    Returns:
        str: Unified diff text.

    Examples:
        >>> diff = _content_to_unified_diff(target_path="workspace/prompts/x.md", content="# hi\\n")
        >>> diff.startswith("--- /dev/null")
        True
    """
    if content and not content.endswith("\n"):
        content = content + "\n"
    new_lines = content.splitlines(keepends=True)
    return "".join(
        difflib.unified_diff(
            [],
            new_lines,
            fromfile="/dev/null",
            tofile=target_path,
            lineterm="\n",
        )
    )


def _effective_si_flags(si: SelfImproveWorkspaceConfig | None) -> tuple[bool, bool, bool]:
    """Return ``allow_*`` flags with defaults when ``si`` is absent.

    Args:
        si (SelfImproveWorkspaceConfig | None): Self-improve subtree.

    Returns:
        tuple[bool, bool, bool]: ``allow_config``, ``allow_dependency``, ``allow_lcm``.

    Examples:
        >>> _effective_si_flags(None)
        (False, False, False)
    """
    if si is None:
        return False, False, False
    return si.allow_config_changes, si.allow_dependency_changes, si.allow_lcm_memory_changes


def _validate_patch_diff(
    diff: str,
    *,
    target_path: str | None,
    allowed_globs: list[str],
    deny_globs: list[str] | None,
    allow_config_changes: bool,
    allow_dependency_changes: bool,
    allow_lcm_memory_changes: bool,
    workspace: WorkspaceConfig | None = None,
    content_root: Path | None = None,
) -> str | None:
    """Run static scope, policy, and optional LLM Guard checks on a diff.

    Args:
        diff (str): Unified diff text.
        target_path (str | None): Primary target path for error context.
        allowed_globs (list[str]): Effective allowlist patterns.
        deny_globs (list[str] | None): Optional deny patterns.
        allow_config_changes (bool): Permit config edits.
        allow_dependency_changes (bool): Permit dependency manifest edits.
        allow_lcm_memory_changes (bool): Permit LCM memory edits.
        workspace (WorkspaceConfig | None): Workspace for LLM Guard scanner config.
        content_root (Path | None): Content root for scanner binding.

    Returns:
        str | None: Rejection reason or ``None`` when allowed.

    Examples:
        >>> _validate_patch_diff(
        ...     "+++ b/workspace/prompts/x.md\\n@@ -0,0 +1 @@\\n+# ok\\n",
        ...     target_path="workspace/prompts/x.md",
        ...     allowed_globs=["workspace/prompts/**"],
        ...     deny_globs=None,
        ...     allow_config_changes=False,
        ...     allow_dependency_changes=False,
        ...     allow_lcm_memory_changes=False,
        ... ) is None
        True
    """
    scope_reason = reject_patch_glob_scope(diff, allowed_globs=allowed_globs, deny_globs=deny_globs)
    if scope_reason is not None:
        return scope_reason
    policy_reason = reject_patch_policy(
        diff,
        allow_config_changes=allow_config_changes,
        allow_dependency_changes=allow_dependency_changes,
        allow_lcm_memory_changes=allow_lcm_memory_changes,
    )
    if policy_reason is not None:
        return policy_reason
    from sevn.self_improve.proposer import reject_patch_diff

    security_reason = reject_patch_diff(diff)
    if security_reason is not None:
        return security_reason
    if workspace is not None and content_root is not None:
        import asyncio

        from sevn.security.llm_guard_scanner import ScanVerdict, scan_patch_diff

        async def _scan() -> str | None:
            result = await scan_patch_diff(
                diff,
                workspace=content_root,
                cfg=workspace,
            )
            if result.verdict == ScanVerdict.block:
                reasons = ",".join(r.value for r in result.reasons) or "policy"
                return f"patch_rejected_security: llm_guard ({reasons})"
            return None

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(_scan())
        if loop.is_running():
            # Worker calls from async context — caller should use async validation path.
            return None
        return asyncio.run(_scan())
    _ = target_path
    return None


async def _validate_patch_diff_async(
    diff: str,
    *,
    allowed_globs: list[str],
    deny_globs: list[str] | None,
    allow_config_changes: bool,
    allow_dependency_changes: bool,
    allow_lcm_memory_changes: bool,
    workspace: WorkspaceConfig | None = None,
    content_root: Path | None = None,
) -> str | None:
    """Async variant of :func:`_validate_patch_diff` including LLM Guard.

    Args:
        diff (str): Unified diff text.
        allowed_globs (list[str]): Effective allowlist patterns.
        deny_globs (list[str] | None): Optional deny patterns.
        allow_config_changes (bool): Permit config edits.
        allow_dependency_changes (bool): Permit dependency manifest edits.
        allow_lcm_memory_changes (bool): Permit LCM memory edits.
        workspace (WorkspaceConfig | None): Workspace for LLM Guard scanner config.
        content_root (Path | None): Content root for scanner binding.

    Returns:
        str | None: Rejection reason or ``None`` when allowed.

    Examples:
        >>> import asyncio
        >>> asyncio.run(_validate_patch_diff_async(
        ...     "+++ b/workspace/prompts/x.md\\n@@ -0,0 +1 @@\\n+# ok\\n",
        ...     allowed_globs=["workspace/prompts/**"],
        ...     deny_globs=None,
        ...     allow_config_changes=False,
        ...     allow_dependency_changes=False,
        ...     allow_lcm_memory_changes=False,
        ... )) is None
        True
    """
    scope_reason = reject_patch_glob_scope(diff, allowed_globs=allowed_globs, deny_globs=deny_globs)
    if scope_reason is not None:
        return scope_reason
    policy_reason = reject_patch_policy(
        diff,
        allow_config_changes=allow_config_changes,
        allow_dependency_changes=allow_dependency_changes,
        allow_lcm_memory_changes=allow_lcm_memory_changes,
    )
    if policy_reason is not None:
        return policy_reason
    from sevn.self_improve.proposer import reject_patch_diff

    security_reason = reject_patch_diff(diff)
    if security_reason is not None:
        return security_reason
    if workspace is not None and content_root is not None:
        from sevn.security.llm_guard_scanner import ScanVerdict, scan_patch_diff

        result = await scan_patch_diff(diff, workspace=content_root, cfg=workspace)
        if result.verdict == ScanVerdict.block:
            reasons = ",".join(r.value for r in result.reasons) or "policy"
            return f"patch_rejected_security: llm_guard ({reasons})"
    return None


def _stub_enabled() -> bool:
    """Return whether deterministic stub authoring is forced via env.

    Returns:
        bool: ``True`` when ``SEVN_PATCH_AUTHOR_STUB=1``.

    Examples:
        >>> isinstance(_stub_enabled(), bool)
        True
    """
    return os.environ.get("SEVN_PATCH_AUTHOR_STUB", "").strip().lower() in ("1", "true", "yes")


async def author_patch_from_shortlist(
    *,
    job_id: str,
    shortlist: dict[str, Any],
    allowed_globs: list[str] | None = None,
    deny_globs: list[str] | None = None,
    plan_md_path: str | None = None,
    workspace: WorkspaceConfig | None = None,
    layout: WorkspaceLayout | None = None,
    job_bundle: Path | None = None,
    patch_author_mode: str | None = None,
    trace: TraceSink | None = None,
    process: ProcessSettings | None = None,
) -> PatchAuthorResult:
    """Build a unified diff from shortlist metadata via stub or tier-B agent.

    Args:
        job_id (str): Improve job identifier (stable slug input).
        shortlist (dict[str, Any]): Parsed ``shortlist.json`` payload.
        allowed_globs (list[str] | None): Optional allowlist; defaults to PRD presets.
        deny_globs (list[str] | None): Optional deny patterns.
        plan_md_path (str | None): Optional spec-kit ``plan.md`` path for prompt context.
        workspace (WorkspaceConfig | None): Workspace config for agent + guard paths.
        layout (WorkspaceLayout | None): Layout for context pack + scanner root.
        job_bundle (Path | None): Job bundle directory for context pack load.
        patch_author_mode (str | None): Override ``self_improve.patch_author`` mode.
        trace (TraceSink | None): Optional trace sink for provider spans.
        process (ProcessSettings | None): Process settings for proxy URL resolution.

    Returns:
        PatchAuthorResult: ``ok=True`` with diff text, or ``ok=False`` with ``rejection``.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(author_patch_from_shortlist)
        True
    """
    globs = _resolve_allowed_globs(allowed_globs)
    si = workspace.self_improve if workspace is not None else None
    allow_cfg, allow_dep, allow_lcm = _effective_si_flags(si)
    if _stub_enabled():
        stub_result = _run_stub(
            job_id=job_id,
            shortlist=shortlist,
            allowed_globs=globs,
            deny_globs=deny_globs,
            plan_md_path=plan_md_path,
            allow_config_changes=allow_cfg,
            allow_dependency_changes=allow_dep,
            allow_lcm_memory_changes=allow_lcm,
            workspace=workspace,
            content_root=layout.content_root if layout is not None else None,
        )
        return stub_result  # noqa: RET504
    configured_mode = patch_author_mode
    if configured_mode is None and si is not None:
        configured_mode = si.patch_author
    try:
        mode = resolve_patch_author_mode(configured_mode)
    except ValueError as exc:
        return PatchAuthorResult(ok=False, diff="", target_path=None, rejection=str(exc))
    if mode != "pydantic_agent":
        return PatchAuthorResult(
            ok=False,
            diff="",
            target_path=None,
            rejection=f"unsupported patch author mode: {mode!r}",
        )
    if workspace is None or layout is None:
        return PatchAuthorResult(
            ok=False,
            diff="",
            target_path=None,
            rejection="patch_author_failed: workspace and layout required for pydantic_agent",
        )
    from sevn.self_improve.proposer.agent import run_patch_proposal_agent
    from sevn.self_improve.proposer.context_loader import load_context_pack
    from sevn.self_improve.proposer.prompt import build_patch_author_prompt

    context_pack = load_context_pack(job_bundle) if job_bundle is not None else {}
    user_prompt = build_patch_author_prompt(
        job_id=job_id,
        shortlist=shortlist,
        context_pack=context_pack,
        allowed_globs=globs,
        deny_globs=deny_globs,
        plan_md_path=plan_md_path,
        allow_config_changes=allow_cfg,
        allow_dependency_changes=allow_dep,
        allow_lcm_memory_changes=allow_lcm,
    )
    try:
        proposal = await run_patch_proposal_agent(
            workspace=workspace,
            layout=layout,
            job_id=job_id,
            user_prompt=user_prompt,
            trace=trace,
            process=process,
        )
    except Exception as exc:
        return PatchAuthorResult(
            ok=False,
            diff="",
            target_path=None,
            rejection=f"patch_author_failed: {exc}",
        )
    target = proposal.target_path.strip().replace("\\", "/")
    diff = _content_to_unified_diff(target_path=target, content=proposal.content)
    rejection = await _validate_patch_diff_async(
        diff,
        allowed_globs=globs,
        deny_globs=deny_globs,
        allow_config_changes=allow_cfg,
        allow_dependency_changes=allow_dep,
        allow_lcm_memory_changes=allow_lcm,
        workspace=workspace,
        content_root=layout.content_root,
    )
    if rejection is not None:
        return PatchAuthorResult(ok=False, diff=diff, target_path=target, rejection=rejection)
    return PatchAuthorResult(
        ok=True,
        diff=diff,
        target_path=target,
        rejection=None,
        author="pydantic_agent",
    )


def _run_stub(
    *,
    job_id: str,
    shortlist: dict[str, Any],
    allowed_globs: list[str],
    deny_globs: list[str] | None,
    plan_md_path: str | None,
    allow_config_changes: bool,
    allow_dependency_changes: bool,
    allow_lcm_memory_changes: bool,
    workspace: WorkspaceConfig | None,
    content_root: Path | None,
) -> PatchAuthorResult:
    """Run deterministic stub authoring and attach author metadata.

    Args:
        job_id (str): Improve job id.
        shortlist (dict[str, Any]): Parsed shortlist payload.
        allowed_globs (list[str]): Effective allowlist.
        deny_globs (list[str] | None): Optional deny patterns.
        plan_md_path (str | None): Optional plan path.
        allow_config_changes (bool): Policy flag for post-check.
        allow_dependency_changes (bool): Policy flag for post-check.
        allow_lcm_memory_changes (bool): Policy flag for post-check.
        workspace (WorkspaceConfig | None): Optional workspace for guard scan skip.
        content_root (Path | None): Optional content root (unused for stub sync path).

    Returns:
        PatchAuthorResult: Stub outcome with ``author='deterministic_stub'``.

    Examples:
        >>> result = _run_stub(
        ...     job_id="j",
        ...     shortlist={"candidates": []},
        ...     allowed_globs=["workspace/prompts/**"],
        ...     deny_globs=None,
        ...     plan_md_path=None,
        ...     allow_config_changes=False,
        ...     allow_dependency_changes=False,
        ...     allow_lcm_memory_changes=False,
        ...     workspace=None,
        ...     content_root=None,
        ... )
        >>> result.author
        'deterministic_stub'
    """
    from sevn.self_improve.proposer.patch_author_stub import stub_author_patch_from_shortlist

    stub = stub_author_patch_from_shortlist(
        job_id=job_id,
        shortlist=shortlist,
        allowed_globs=allowed_globs,
        deny_globs=deny_globs,
        plan_md_path=plan_md_path,
    )
    if not stub.ok:
        return PatchAuthorResult(
            ok=False,
            diff=stub.diff,
            target_path=stub.target_path,
            rejection=stub.rejection,
            author="deterministic_stub",
        )
    policy_reason = reject_patch_policy(
        stub.diff,
        allow_config_changes=allow_config_changes,
        allow_dependency_changes=allow_dependency_changes,
        allow_lcm_memory_changes=allow_lcm_memory_changes,
    )
    if policy_reason is not None:
        return PatchAuthorResult(
            ok=False,
            diff=stub.diff,
            target_path=stub.target_path,
            rejection=policy_reason,
            author="deterministic_stub",
        )
    _ = workspace
    _ = content_root
    return PatchAuthorResult(
        ok=True,
        diff=stub.diff,
        target_path=stub.target_path,
        rejection=None,
        author="deterministic_stub",
    )


def write_patch_artefacts(
    bundle_dir: Path,
    result: PatchAuthorResult,
    *,
    author: str | None = None,
) -> Path:
    """Write ``patch/diff.patch`` (and ``patch/meta.json``) under a job bundle.

    Args:
        bundle_dir (Path): ``.sevn/improve/jobs/<job_id>/`` directory.
        result (PatchAuthorResult): Successful authoring outcome.
        author (str | None): Optional author override for ``meta.json``.

    Returns:
        Path: Path to the written unified diff file.

    Raises:
        ValueError: When ``result.ok`` is false.

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> ok = PatchAuthorResult(
        ...     ok=True,
        ...     diff="+++ b/x\\n",
        ...     target_path="workspace/prompts/x.md",
        ...     author="pydantic_agent",
        ... )
        >>> with tempfile.TemporaryDirectory() as tmp:
        ...     path = write_patch_artefacts(Path(tmp), ok)
        ...     path.name == "diff.patch"
        True
    """
    if not result.ok or not result.diff:
        msg = "cannot write patch artefacts for failed authoring"
        raise ValueError(msg)
    patch_dir = bundle_dir / "patch"
    patch_dir.mkdir(parents=True, exist_ok=True)
    diff_path = patch_dir / "diff.patch"
    diff_path.write_text(result.diff, encoding="utf-8")
    meta_author = author or result.author or "pydantic_agent"
    meta = {
        "schema_version": 1,
        "target_path": result.target_path,
        "author": meta_author,
    }
    (patch_dir / "meta.json").write_text(
        json.dumps(meta, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return diff_path


__all__ = [
    "DEFAULT_ALLOWED_GLOBS",
    "PATCH_AUTHOR_MODES",
    "PatchAuthorMode",
    "PatchAuthorResult",
    "author_patch_from_shortlist",
    "paths_in_unified_diff",
    "preset_requires_proposer",
    "proposer_budget_exhausted",
    "reject_patch_glob_scope",
    "reject_patch_policy",
    "resolve_patch_author_mode",
    "write_patch_artefacts",
]
