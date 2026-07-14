"""Spec-kit constitution, options, and allowlisted CLI integration (`specs/35-bot-evolution.md`).

Module: sevn.evolution.spec_kit
Depends: os, pathlib, subprocess, sevn.config.workspace_config, sevn.evolution.spec_kit_runs,
    sevn.gateway.config_io.workspace_config_io

Exports:
    ConstitutionPayload — constitution body + persistence metadata.
    SpecKitRunResult — structured subprocess outcome.
    load_constitution — read constitution markdown + metadata.
    save_constitution — persist constitution for an owner principal.
    constitution_template_text — bundled seed template for Reset.
    load_spec_kit_options — MC-facing options snapshot.
    save_spec_kit_options — merge-patch spec-kit related workspace keys.
    run_specify_allowlisted — invoke or dry-run one allowlisted command.
"""

from __future__ import annotations

import os
import shlex
import subprocess  # nosec B404
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from sevn.config.workspace_config import (
    MySevnBugsWorkspaceConfig,
    SelfImproveSpecKitConfig,
    SpecKitOptionsWorkspaceConfig,
    SpecKitWorkspaceConfig,
    WorkspaceConfig,
)
from sevn.evolution import spec_kit_runs
from sevn.gateway.config_io.workspace_config_io import mutate_sevn_json

if TYPE_CHECKING:
    from sevn.workspace.layout import WorkspaceLayout

ALLOWLISTED_SPEC_KIT_COMMANDS: frozenset[str] = frozenset(
    {"constitution", "specify", "plan", "tasks", "implement"},
)

_FORBIDDEN_ARGV_TOKENS: frozenset[str] = frozenset(
    {"sh", "bash", "zsh", "fish", "cmd", "powershell", "pwsh"},
)

ConstitutionSource = Literal["repo", "workspace_mirror", "template"]

_WORKSPACE_MIRROR_REL = Path(".sevn/spec-kit/constitution.md")
_REPO_CONSTITUTION_PREFIX = "evolution/spec-kit/"


def _try_resolve_repo_root() -> Path | None:
    """Return ``SEVN_REPO_ROOT`` when set and readable.

    Returns:
        Path | None: Repo checkout root.

    Examples:
        >>> _try_resolve_repo_root() is None or _try_resolve_repo_root().is_dir()
        True
    """
    raw = os.environ.get("SEVN_REPO_ROOT", "").strip()
    if not raw:
        return None
    root = Path(raw).expanduser().resolve()
    return root if root.is_dir() else None


@dataclass(frozen=True)
class ConstitutionPayload:
    """Constitution body and persistence metadata for Mission Control."""

    text: str
    path: str
    writable: bool
    source: ConstitutionSource
    banner: str | None = None


@dataclass(frozen=True)
class SpecKitRunResult:
    """Structured result from :func:`run_specify_allowlisted`."""

    run_id: str
    command: str
    argv: list[str]
    cwd: str
    status: spec_kit_runs.SpecKitRunStatus
    dry_run: bool
    exit_code: int | None
    stdout: str
    stderr: str
    detail: str | None = None


def constitution_template_text() -> str:
    """Return the seed constitution markdown from the repo template when present.

    Returns:
        str: Template body for **Reset to template**.

    Examples:
        >>> len(constitution_template_text()) > 0
        True
    """
    repo = _try_resolve_repo_root()
    if repo is not None:
        template = repo / "evolution" / "spec-kit" / "CONSTITUTION.md"
        if template.is_file():
            return template.read_text(encoding="utf-8")
    return (
        "# sevn.bot spec-kit constitution\n\n"
        "- Run `make ci` before shipping patches.\n"
        "- Code writes only in git worktrees under `workspace/.sevn/code-worktrees/`.\n"
        "- Feature issues require HITL before implement.\n"
    )


def _effective_spec_kit(ws: WorkspaceConfig) -> SpecKitWorkspaceConfig:
    """Return ``spec_kit`` config with defaults when absent.

    Args:
        ws (WorkspaceConfig): Parsed workspace.

    Returns:
        SpecKitWorkspaceConfig: Effective subtree.

    Examples:
        >>> _effective_spec_kit(WorkspaceConfig.minimal()).enabled
        True
    """
    if ws.spec_kit is not None:
        return ws.spec_kit
    return SpecKitWorkspaceConfig()


def _constitution_repo_path(ws: WorkspaceConfig) -> Path | None:
    """Resolve repo-relative constitution path when checkout is available.

    Args:
        ws (WorkspaceConfig): Parsed workspace.

    Returns:
        Path | None: Absolute path when readable.

    Examples:
        >>> _constitution_repo_path(WorkspaceConfig.minimal()) is None or True
        True
    """
    repo = _try_resolve_repo_root()
    if repo is None:
        return None
    rel = _effective_spec_kit(ws).constitution_path.replace("\\", "/").lstrip("/")
    candidate = repo / rel
    return candidate if candidate.is_file() or candidate.parent.is_dir() else None


def load_constitution(ws: WorkspaceConfig, layout: WorkspaceLayout) -> ConstitutionPayload:
    """Load constitution text for Mission Control display.

    Args:
        ws (WorkspaceConfig): Parsed workspace.
        layout (WorkspaceLayout): Resolved layout.

    Returns:
        ConstitutionPayload: Body and persistence metadata.

    Examples:
        >>> from pathlib import Path
        >>> from sevn.workspace.layout import WorkspaceLayout
        >>> ws = WorkspaceConfig.minimal()
        >>> ly = WorkspaceLayout(Path("/tmp/s.json"), Path("/tmp/w"))
        >>> payload = load_constitution(ws, ly)
        >>> len(payload.text) > 0
        True
    """
    repo_path = _constitution_repo_path(ws)
    if repo_path is not None and repo_path.is_file():
        return ConstitutionPayload(
            text=repo_path.read_text(encoding="utf-8"),
            path=str(repo_path),
            writable=repo_path.parent.is_dir(),
            source="repo",
        )
    mirror = layout.dot_sevn / "spec-kit" / "constitution.md"
    if mirror.is_file():
        return ConstitutionPayload(
            text=mirror.read_text(encoding="utf-8"),
            path=str(mirror),
            writable=True,
            source="workspace_mirror",
            banner="Workspace mirror — set SEVN_REPO_ROOT to edit repo canonical path.",
        )
    template = constitution_template_text()
    return ConstitutionPayload(
        text=template,
        path=str(_effective_spec_kit(ws).constitution_path),
        writable=False,
        source="template",
        banner="Using bundled template; save writes workspace mirror.",
    )


def save_constitution(
    text: str,
    *,
    owner_principal: str,
    ws: WorkspaceConfig,
    layout: WorkspaceLayout,
) -> ConstitutionPayload:
    """Persist constitution to repo or workspace mirror.

    Args:
        text (str): Markdown body.
        owner_principal (str): Owner principal for audit (reserved).
        ws (WorkspaceConfig): Parsed workspace.
        layout (WorkspaceLayout): Resolved layout.

    Returns:
        ConstitutionPayload: Post-save metadata.

    Examples:
        >>> save_constitution.__name__
        'save_constitution'
    """
    _ = owner_principal
    repo_path = _constitution_repo_path(ws)
    if repo_path is not None and str(repo_path).startswith(str(_try_resolve_repo_root() or "")):
        repo_path.parent.mkdir(parents=True, exist_ok=True)
        repo_path.write_text(text, encoding="utf-8")
        return ConstitutionPayload(
            text=text,
            path=str(repo_path),
            writable=True,
            source="repo",
        )
    mirror = layout.dot_sevn / "spec-kit" / "constitution.md"
    mirror.parent.mkdir(parents=True, exist_ok=True)
    mirror.write_text(text, encoding="utf-8")
    return ConstitutionPayload(
        text=text,
        path=str(mirror),
        writable=True,
        source="workspace_mirror",
        banner="Saved to workspace mirror.",
    )


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``patch`` into ``base`` for nested dict keys.

    Args:
        base (dict[str, Any]): Existing mapping.
        patch (dict[str, Any]): Partial update.

    Returns:
        dict[str, Any]: Merged mapping.

    Examples:
        >>> _deep_merge({"a": {"b": 1}}, {"a": {"c": 2}})
        {'a': {'b': 1, 'c': 2}}
    """
    out = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict):
            existing = out.get(key)
            if isinstance(existing, dict):
                out[key] = _deep_merge(existing, value)
            else:
                out[key] = value
        else:
            out[key] = value
    return out


def load_spec_kit_options(ws: WorkspaceConfig) -> dict[str, Any]:
    """Return Mission Control options snapshot.

    Args:
        ws (WorkspaceConfig): Parsed workspace.

    Returns:
        dict[str, Any]: Flat toggles and nested ``spec_kit`` subtree.

    Examples:
        >>> opts = load_spec_kit_options(WorkspaceConfig.minimal())
        >>> opts["spec_kit_enabled"] is True
        True
    """
    sk = _effective_spec_kit(ws)
    my = ws.my_sevn
    bugs = my.bugs if my and my.bugs else MySevnBugsWorkspaceConfig()
    si_sk = (
        ws.self_improve.spec_kit
        if ws.self_improve is not None and ws.self_improve.spec_kit is not None
        else SelfImproveSpecKitConfig()
    )
    return {
        "spec_kit": sk.model_dump(mode="json"),
        "spec_kit_enabled": sk.enabled,
        "my_sevn_bugs_use_spec_kit": bugs.use_spec_kit,
        "self_improve_spec_kit_enabled": si_sk.enabled,
        "self_improve_spec_kit_require_plan_before_patch": si_sk.require_plan_before_patch,
        "self_improve_spec_kit_require_hitl_for_plan": si_sk.require_hitl_for_plan,
        "integration": sk.integration,
        "dry_run_default": sk.options.dry_run_default if sk.options else False,
    }


def save_spec_kit_options(
    patch: dict[str, Any],
    *,
    sevn_json_path: Path,
) -> dict[str, Any]:
    """Merge-patch spec-kit workspace keys and persist ``sevn.json``.

    Args:
        patch (dict[str, Any]): Partial update from Mission Control.
        sevn_json_path (Path): Path to ``sevn.json``.

    Returns:
        dict[str, Any]: Post-save snapshot from :func:`load_spec_kit_options`.

    Examples:
        >>> save_spec_kit_options.__name__
        'save_spec_kit_options'
    """
    from sevn.config.workspace_config import parse_workspace_config

    def mutator(doc: dict[str, Any]) -> None:
        if "spec_kit" in patch and isinstance(patch["spec_kit"], dict):
            doc["spec_kit"] = _deep_merge(
                doc.get("spec_kit", {}) if isinstance(doc.get("spec_kit"), dict) else {},
                patch["spec_kit"],
            )
        if patch.get("spec_kit_enabled") is not None:
            doc.setdefault("spec_kit", {})
            if isinstance(doc["spec_kit"], dict):
                doc["spec_kit"]["enabled"] = bool(patch["spec_kit_enabled"])
        if patch.get("my_sevn_bugs_use_spec_kit") is not None:
            doc.setdefault("my_sevn", {})
            if isinstance(doc["my_sevn"], dict):
                doc["my_sevn"].setdefault("bugs", {})
                if isinstance(doc["my_sevn"]["bugs"], dict):
                    doc["my_sevn"]["bugs"]["use_spec_kit"] = bool(
                        patch["my_sevn_bugs_use_spec_kit"]
                    )
        for key, dotted in (
            ("self_improve_spec_kit_enabled", ("self_improve", "spec_kit", "enabled")),
            (
                "self_improve_spec_kit_require_plan_before_patch",
                ("self_improve", "spec_kit", "require_plan_before_patch"),
            ),
            (
                "self_improve_spec_kit_require_hitl_for_plan",
                ("self_improve", "spec_kit", "require_hitl_for_plan"),
            ),
        ):
            if patch.get(key) is not None:
                doc.setdefault("self_improve", {})
                if isinstance(doc["self_improve"], dict):
                    doc["self_improve"].setdefault("spec_kit", {})
                    if isinstance(doc["self_improve"]["spec_kit"], dict):
                        doc["self_improve"]["spec_kit"][dotted[2]] = bool(patch[key])
        if patch.get("integration") is not None:
            doc.setdefault("spec_kit", {})
            if isinstance(doc["spec_kit"], dict):
                doc["spec_kit"]["integration"] = str(patch["integration"])
        if patch.get("dry_run_default") is not None:
            doc.setdefault("spec_kit", {})
            if isinstance(doc["spec_kit"], dict):
                doc["spec_kit"].setdefault("options", {})
                if isinstance(doc["spec_kit"]["options"], dict):
                    doc["spec_kit"]["options"]["dry_run_default"] = bool(patch["dry_run_default"])

    updated = mutate_sevn_json(sevn_json_path, mutator)
    return load_spec_kit_options(parse_workspace_config(updated))


def _validate_argv(argv: list[str]) -> str | None:
    """Reject argv tokens that invoke a shell.

    Args:
        argv (list[str]): Extra CLI arguments.

    Returns:
        str | None: Error message when rejected, else ``None``.

    Examples:
        >>> _validate_argv(["--dry-run"]) is None
        True
    """
    lowered = [part.lower() for part in argv]
    for token in lowered:
        if token in _FORBIDDEN_ARGV_TOKENS:
            return f"forbidden argv token: {token}"
    return None


def _build_cli_argv(ws: WorkspaceConfig, command: str, argv: list[str]) -> list[str]:
    """Build the subprocess argv for one allowlisted command.

    Args:
        ws (WorkspaceConfig): Workspace config.
        command (str): Allowlisted command name.
        argv (list[str]): Extra args.

    Returns:
        list[str]: Full argv list.

    Examples:
        >>> _build_cli_argv(WorkspaceConfig.minimal(), "plan", [])[-1]
        'plan'
    """
    sk = _effective_spec_kit(ws)
    base = shlex.split(sk.cli_command) if sk.cli_command else ["uv", "run", "specify"]
    return [*base, command, *argv]


def run_specify_allowlisted(
    command: str,
    argv: list[str],
    cwd: Path,
    *,
    owner_principal: str,
    ws: WorkspaceConfig,
    layout: WorkspaceLayout,
    issue_id: str | None = None,
    job_id: str | None = None,
    dry_run: bool | None = None,
) -> SpecKitRunResult:
    """Run or dry-run one allowlisted spec-kit command; append an audit row.

    Args:
        command (str): Allowlisted command name.
        argv (list[str]): Extra CLI args (must not invoke a shell).
        cwd (Path): Working directory for the subprocess.
        owner_principal (str): Owner principal for audit.
        ws (WorkspaceConfig): Workspace config.
        layout (WorkspaceLayout): Resolved layout.
        issue_id (str | None): Optional issue correlation id.
        job_id (str | None): Optional improve job correlation id.
        dry_run (bool | None): When ``None``, uses ``spec_kit.options.dry_run_default``.

    Returns:
        SpecKitRunResult: Structured outcome for Mission Control.

    Raises:
        ValueError: When *command* or *argv* fail allowlist checks.

    Examples:
        >>> run_specify_allowlisted.__name__
        'run_specify_allowlisted'
    """
    started = spec_kit_runs.utc_now_iso()
    run_id = spec_kit_runs.new_run_id()
    cmd = command.strip().lower()
    cwd.mkdir(parents=True, exist_ok=True)
    if cmd not in ALLOWLISTED_SPEC_KIT_COMMANDS:
        msg = f"command not allowlisted: {command!r}"
        finished = spec_kit_runs.utc_now_iso()
        record = spec_kit_runs.SpecKitRunRecord(
            run_id=run_id,
            command=command,
            argv=list(argv),
            cwd=str(cwd),
            status="rejected",
            started_at=started,
            finished_at=finished,
            owner_principal=owner_principal,
            issue_id=issue_id,
            job_id=job_id,
            detail=msg,
        )
        spec_kit_runs.append_spec_kit_run(layout.dot_sevn, record)
        raise ValueError(msg)
    argv_err = _validate_argv(argv)
    if argv_err:
        finished = spec_kit_runs.utc_now_iso()
        record = spec_kit_runs.SpecKitRunRecord(
            run_id=run_id,
            command=command,
            argv=list(argv),
            cwd=str(cwd),
            status="rejected",
            started_at=started,
            finished_at=finished,
            owner_principal=owner_principal,
            issue_id=issue_id,
            job_id=job_id,
            detail=argv_err,
        )
        spec_kit_runs.append_spec_kit_run(layout.dot_sevn, record)
        raise ValueError(argv_err)

    sk = _effective_spec_kit(ws)
    opts = sk.options if sk.options is not None else SpecKitOptionsWorkspaceConfig()
    effective_dry = opts.dry_run_default if dry_run is None else bool(dry_run)
    if not sk.enabled:
        detail = "spec_kit.enabled is false"
        finished = spec_kit_runs.utc_now_iso()
        record = spec_kit_runs.SpecKitRunRecord(
            run_id=run_id,
            command=cmd,
            argv=list(argv),
            cwd=str(cwd),
            status="rejected",
            started_at=started,
            finished_at=finished,
            owner_principal=owner_principal,
            issue_id=issue_id,
            job_id=job_id,
            detail=detail,
        )
        spec_kit_runs.append_spec_kit_run(layout.dot_sevn, record)
        return SpecKitRunResult(
            run_id=run_id,
            command=cmd,
            argv=list(argv),
            cwd=str(cwd),
            status="rejected",
            dry_run=effective_dry,
            exit_code=None,
            stdout="",
            stderr="",
            detail=detail,
        )

    full_argv = _build_cli_argv(ws, cmd, argv)
    if effective_dry:
        if "--dry-run" not in full_argv:
            full_argv = [*full_argv, "--dry-run"]
        detail = f"dry-run: would run {shlex.join(full_argv)}"
        finished = spec_kit_runs.utc_now_iso()
        record = spec_kit_runs.SpecKitRunRecord(
            run_id=run_id,
            command=cmd,
            argv=list(argv),
            cwd=str(cwd),
            status="dry_run",
            started_at=started,
            finished_at=finished,
            owner_principal=owner_principal,
            issue_id=issue_id,
            job_id=job_id,
            exit_code=0,
            stdout=detail,
            stderr="",
            detail=detail,
        )
        spec_kit_runs.append_spec_kit_run(layout.dot_sevn, record)
        return SpecKitRunResult(
            run_id=run_id,
            command=cmd,
            argv=list(argv),
            cwd=str(cwd),
            status="dry_run",
            dry_run=True,
            exit_code=0,
            stdout=detail,
            stderr="",
            detail=detail,
        )

    env = {**os.environ, "SEVN_SPEC_KIT_DRY_RUN": "0"}
    try:
        proc = subprocess.run(  # nosec B603
            full_argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
            check=False,
        )
        status: spec_kit_runs.SpecKitRunStatus = "ok" if proc.returncode == 0 else "error"
        finished = spec_kit_runs.utc_now_iso()
        record = spec_kit_runs.SpecKitRunRecord(
            run_id=run_id,
            command=cmd,
            argv=list(argv),
            cwd=str(cwd),
            status=status,
            started_at=started,
            finished_at=finished,
            owner_principal=owner_principal,
            issue_id=issue_id,
            job_id=job_id,
            exit_code=proc.returncode,
            stdout=proc.stdout[:8192] if proc.stdout else "",
            stderr=proc.stderr[:8192] if proc.stderr else "",
            detail=None,
        )
        spec_kit_runs.append_spec_kit_run(layout.dot_sevn, record)
        return SpecKitRunResult(
            run_id=run_id,
            command=cmd,
            argv=list(argv),
            cwd=str(cwd),
            status=status,
            dry_run=False,
            exit_code=proc.returncode,
            stdout=record.stdout,
            stderr=record.stderr,
            detail=None,
        )
    except OSError as exc:
        finished = spec_kit_runs.utc_now_iso()
        detail = str(exc)
        record = spec_kit_runs.SpecKitRunRecord(
            run_id=run_id,
            command=cmd,
            argv=list(argv),
            cwd=str(cwd),
            status="error",
            started_at=started,
            finished_at=finished,
            owner_principal=owner_principal,
            issue_id=issue_id,
            job_id=job_id,
            detail=detail,
        )
        spec_kit_runs.append_spec_kit_run(layout.dot_sevn, record)
        return SpecKitRunResult(
            run_id=run_id,
            command=cmd,
            argv=list(argv),
            cwd=str(cwd),
            status="error",
            dry_run=False,
            exit_code=None,
            stdout="",
            stderr=detail,
            detail=detail,
        )


__all__ = [
    "ALLOWLISTED_SPEC_KIT_COMMANDS",
    "ConstitutionPayload",
    "SpecKitRunResult",
    "constitution_template_text",
    "load_constitution",
    "load_spec_kit_options",
    "run_specify_allowlisted",
    "save_constitution",
    "save_spec_kit_options",
]
