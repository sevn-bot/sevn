"""SkillSpector wrapper for workspace skill security scans (`specs/09-security-scanner.md`).

Module: sevn.skills.security_scan
Depends: json, shutil, subprocess, dataclasses, pathlib, sevn.agent.tracing.sink

Exports:
    ScanIssue — One normalized SkillSpector issue row.
    ScanResult — Aggregate scan outcome for a skill path.
    BaselineSuppression — CI baseline row keyed by skill_path + rule_id.
    load_baseline — Parse ``infra/skillspector-baseline.json``.
    normalize_skill_path — Repo/workspace-relative posix path without trailing slash.
    parse_skillspector_report — Normalize SkillSpector JSON ``issues`` list.
    apply_baseline — Drop issues matching baseline suppressions.
    filter_by_severities — Keep issues whose severity is in the given set.
    resolve_skillspector_command — Locate the ``skillspector`` CLI for subprocess use.
    run_skillspector_subprocess — Invoke ``skillspector scan`` and return parsed JSON.
    scan_skill_path — Scan one directory or file; optional baseline subtraction.
    emit_security_scan_trace — Record ``skills.security_scan`` without exploit text.
    write_workspace_scan_summary — Persist last operator scan under ``.sevn/``.
    read_workspace_scan_summary — Read last operator scan summary for doctor/CLI.
    workspace_scan_summary_path — Path helper for ``.sevn/skillspector-last-scan.json``.

Examples:
    >>> normalize_skill_path("skills/user/foo/")
    'skills/user/foo'
"""

from __future__ import annotations

import json
import shutil
import subprocess  # nosec B404
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from time import time_ns
from typing import Any, Final

from sevn.agent.tracing.sink import SYSTEM_TURN_ID, TraceEvent, TraceSink

DEFAULT_FAIL_SEVERITIES: Final[tuple[str, ...]] = ("HIGH", "CRITICAL")
MEDIUM_PLUS_SEVERITIES: Final[frozenset[str]] = frozenset({"MEDIUM", "HIGH", "CRITICAL"})
WORKSPACE_SUMMARY_NAME: Final[str] = "skillspector-last-scan.json"


@dataclass(frozen=True)
class ScanIssue:
    """One normalized SkillSpector issue."""

    rule_id: str
    severity: str
    file: str | None = None
    pattern: str | None = None


@dataclass
class ScanResult:
    """Outcome of scanning one skill directory or markdown file."""

    path: Path
    issues: list[ScanIssue] = field(default_factory=list)
    risk_score: int | None = None
    risk_severity: str | None = None
    scanner_available: bool = True
    error: str | None = None
    raw_report: dict[str, Any] | None = None

    def issues_at_or_above(self, severities: Sequence[str]) -> list[ScanIssue]:
        """Return issues whose severity is in ``severities``.

        Args:
            severities (Sequence[str]): Severity labels to keep (e.g. ``HIGH``).

        Returns:
            list[ScanIssue]: Matching issues.

        Examples:
            >>> r = ScanResult(path=Path("/tmp/x"), issues=[ScanIssue("E2", "HIGH")])
            >>> r.issues_at_or_above(("HIGH",))[0].rule_id
            'E2'
        """
        allowed = frozenset(severities)
        return [issue for issue in self.issues if issue.severity in allowed]


@dataclass(frozen=True)
class BaselineSuppression:
    """CI baseline row suppressing ``skill_path`` + ``rule_id`` pairs."""

    skill_path: str
    rule_id: str
    reason: str
    reviewed: str


def normalize_skill_path(path: str | Path, *, repo_root: Path | None = None) -> str:
    """Return a stable posix path without trailing slash for baseline keys.

    Args:
        path (str | Path): Absolute or relative skill path.
        repo_root (Path | None): When set, relativize absolute paths under the repo.

    Returns:
        str: Normalized repo-relative or input-relative posix path.

    Examples:
        >>> normalize_skill_path("skills/user/foo/")
        'skills/user/foo'
    """
    raw = Path(path)
    if repo_root is not None:
        try:
            raw = raw.resolve().relative_to(repo_root.resolve())
        except ValueError:
            raw = raw.resolve()
    return raw.as_posix().rstrip("/")


def parse_skillspector_report(
    data: dict[str, Any],
) -> tuple[list[ScanIssue], int | None, str | None]:
    """Normalize SkillSpector JSON report into :class:`ScanIssue` rows.

    Args:
        data (dict[str, Any]): Parsed SkillSpector JSON report.

    Returns:
        tuple[list[ScanIssue], int | None, str | None]: Issues, risk score, risk severity.

    Examples:
        >>> issues, score, sev = parse_skillspector_report(
        ...     {"issues": [{"id": "E2", "severity": "HIGH", "location": {"file": "a.py"}}],
        ...      "risk_assessment": {"score": 42, "severity": "HIGH"}}
        ... )
        >>> issues[0].rule_id
        'E2'
    """
    issues: list[ScanIssue] = []
    for row in data.get("issues") or []:
        if not isinstance(row, dict):
            continue
        rule_id = str(row.get("id") or row.get("rule_id") or "").strip()
        severity = str(row.get("severity") or "").strip().upper()
        if not rule_id or not severity:
            continue
        location = row.get("location")
        file_path: str | None = None
        if isinstance(location, dict):
            file_path = str(location.get("file") or "") or None
        elif isinstance(location, str) and location.strip():
            file_path = location.strip()
        issues.append(
            ScanIssue(
                rule_id=rule_id,
                severity=severity,
                file=file_path,
                pattern=str(row.get("pattern") or "") or None,
            ),
        )
    risk = data.get("risk_assessment")
    score: int | None = None
    risk_severity: str | None = None
    if isinstance(risk, dict):
        raw_score = risk.get("score")
        if isinstance(raw_score, int):
            score = raw_score
        elif isinstance(raw_score, float):
            score = int(raw_score)
        raw_sev = risk.get("severity")
        if isinstance(raw_sev, str) and raw_sev.strip():
            risk_severity = raw_sev.strip().upper()
    return issues, score, risk_severity


def load_baseline(path: Path) -> list[BaselineSuppression]:
    """Load baseline suppressions from ``infra/skillspector-baseline.json``.

    Args:
        path (Path): Baseline JSON path.

    Returns:
        list[BaselineSuppression]: Parsed suppressions (empty when file missing).

    Examples:
        >>> load_baseline(Path("/nonexistent/baseline.json"))
        []
    """
    if not path.is_file():
        return []
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = blob.get("suppressions")
    if not isinstance(rows, list):
        return []
    out: list[BaselineSuppression] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        skill_path = str(row.get("skill_path") or "").strip()
        rule_id = str(row.get("rule_id") or "").strip()
        reason = str(row.get("reason") or "").strip()
        reviewed = str(row.get("reviewed") or "").strip()
        if skill_path and rule_id and reason and reviewed:
            out.append(
                BaselineSuppression(
                    skill_path=normalize_skill_path(skill_path),
                    rule_id=rule_id,
                    reason=reason,
                    reviewed=reviewed,
                ),
            )
    return out


def apply_baseline(
    issues: Sequence[ScanIssue],
    *,
    skill_path: str,
    baseline: Sequence[BaselineSuppression],
) -> list[ScanIssue]:
    """Remove issues suppressed by baseline ``skill_path`` + ``rule_id`` keys.

    Args:
        issues (Sequence[ScanIssue]): Raw scanner issues.
        skill_path (str): Normalized skill path for this scan target.
        baseline (Sequence[BaselineSuppression]): CI suppressions.

    Returns:
        list[ScanIssue]: Issues not covered by baseline rows.

    Examples:
        >>> apply_baseline(
        ...     [ScanIssue("E2", "HIGH")],
        ...     skill_path="skills/user/foo",
        ...     baseline=[BaselineSuppression("skills/user/foo", "E2", "ok", "2026-06-14")],
        ... )
        []
    """
    normalized = normalize_skill_path(skill_path)
    suppressed_rules = {row.rule_id for row in baseline if row.skill_path == normalized}
    if not suppressed_rules:
        return list(issues)
    return [issue for issue in issues if issue.rule_id not in suppressed_rules]


def filter_by_severities(
    issues: Sequence[ScanIssue],
    severities: Sequence[str],
) -> list[ScanIssue]:
    """Keep issues whose severity is in ``severities``.

    Args:
        issues (Sequence[ScanIssue]): Candidate issues.
        severities (Sequence[str]): Severity labels to retain.

    Returns:
        list[ScanIssue]: Filtered issues.

    Examples:
        >>> filter_by_severities([ScanIssue("E2", "HIGH"), ScanIssue("P4", "MEDIUM")], ("HIGH",))
        [ScanIssue(rule_id='E2', severity='HIGH', file=None, pattern=None)]
    """
    allowed = frozenset(severities)
    return [issue for issue in issues if issue.severity in allowed]


def resolve_skillspector_command() -> list[str] | None:
    """Locate the ``skillspector`` CLI executable for subprocess invocation.

    Returns:
        list[str] | None: argv prefix (e.g. ``["skillspector"]``) or ``None`` when missing.

    Examples:
        >>> cmd = resolve_skillspector_command()
        >>> cmd is None or isinstance(cmd, list)
        True
    """
    found = shutil.which("skillspector")
    if found:
        return [found]
    venv_bin = Path(sys.prefix) / "bin" / "skillspector"
    if venv_bin.is_file():
        return [str(venv_bin)]
    return None


def run_skillspector_subprocess(
    target: Path,
    *,
    no_llm: bool = True,
    command: Sequence[str] | None = None,
    timeout_seconds: float = 300.0,
) -> dict[str, Any]:
    """Run ``skillspector scan`` against ``target`` and return parsed JSON.

    Args:
        target (Path): Skill directory or markdown file to scan.
        no_llm (bool): Pass ``--no-llm`` for static-only analysis.
        command (Sequence[str] | None): Override CLI argv prefix.
        timeout_seconds (float): Subprocess wall clock limit.

    Returns:
        dict[str, Any]: Parsed SkillSpector JSON report.

    Raises:
        FileNotFoundError: When SkillSpector is not installed.
        RuntimeError: When the CLI fails or returns invalid JSON.

    Examples:
        >>> run_skillspector_subprocess  # doctest: +SKIP
        ...
    """
    argv = list(command or resolve_skillspector_command() or [])
    if not argv:
        msg = "SkillSpector CLI not found — install with: uv sync --extra skillspector"
        raise FileNotFoundError(msg)
    cmd = [
        *argv,
        "scan",
        str(target),
        "--format",
        "json",
    ]
    if no_llm:
        cmd.append("--no-llm")
    completed = subprocess.run(  # nosec B603
        cmd,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    stdout = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()
    if not stdout:
        detail = stderr or f"skillspector exited {completed.returncode} with empty stdout"
        raise RuntimeError(detail)
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError as exc:
        msg = f"skillspector returned invalid JSON: {exc}"
        raise RuntimeError(msg) from exc
    if not isinstance(parsed, dict):
        msg = "skillspector JSON root must be an object"
        raise RuntimeError(msg)
    return parsed


def scan_skill_path(
    path: Path,
    *,
    repo_root: Path | None = None,
    baseline: Sequence[BaselineSuppression] | None = None,
    fail_severities: Sequence[str] = DEFAULT_FAIL_SEVERITIES,
    no_llm: bool = True,
    command: Sequence[str] | None = None,
) -> ScanResult:
    """Scan one skill directory or markdown file with SkillSpector.

    Args:
        path (Path): Existing directory or ``.md`` file.
        repo_root (Path | None): Repo root for baseline path normalization.
        baseline (Sequence[BaselineSuppression] | None): Optional CI suppressions.
        fail_severities (Sequence[str]): Severities retained after baseline filtering.
        no_llm (bool): Static-only scan when True.
        command (Sequence[str] | None): Override SkillSpector CLI argv prefix.

    Returns:
        ScanResult: Parsed outcome; ``error`` set when the scanner is missing or fails.

    Examples:
        >>> scan_skill_path(Path("/nonexistent")).scanner_available
        False
    """
    result = ScanResult(path=path)
    if not path.exists():
        result.scanner_available = False
        result.error = f"missing scan target: {path}"
        return result
    try:
        raw = run_skillspector_subprocess(path, no_llm=no_llm, command=command)
    except FileNotFoundError as exc:
        result.scanner_available = False
        result.error = str(exc)
        return result
    except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
        result.scanner_available = True
        result.error = str(exc)
        return result
    issues, score, risk_severity = parse_skillspector_report(raw)
    normalized = normalize_skill_path(path, repo_root=repo_root)
    issues = filter_by_severities(issues, fail_severities)
    if baseline:
        issues = apply_baseline(issues, skill_path=normalized, baseline=baseline)
    result.issues = issues
    result.risk_score = score
    result.risk_severity = risk_severity
    result.raw_report = raw
    return result


async def emit_security_scan_trace(
    trace: TraceSink | None,
    *,
    session_id: str,
    path: str,
    result: ScanResult,
    turn_id: str = SYSTEM_TURN_ID,
) -> None:
    """Emit ``skills.security_scan`` without raw exploit strings in attrs.

    Args:
        trace (TraceSink | None): Active trace sink (no-op when ``None``).
        session_id (str): Session id for the trace row.
        path (str): Normalized scanned path.
        result (ScanResult): Scan outcome.
        turn_id (str): Correlation id; defaults to :data:`SYSTEM_TURN_ID`.

    Returns:
        None

    Examples:
        >>> import asyncio
        >>> asyncio.run(
        ...     emit_security_scan_trace(
        ...         None, session_id="s", path="p", result=ScanResult(path=Path("p"))
        ...     )
        ... ) is None
        True
    """
    if trace is None:
        return
    now = time_ns()
    await trace.emit(
        TraceEvent(
            kind="skills.security_scan",
            span_id=f"skills-scan-{now}",
            parent_span_id=None,
            session_id=session_id,
            turn_id=turn_id,
            tier=None,
            ts_start_ns=now,
            ts_end_ns=now,
            status="error" if result.error else "ok",
            attrs={
                "path": path,
                "score": result.risk_score,
                "finding_count": len(result.issues),
                "scanner_available": result.scanner_available,
            },
        ),
    )


def workspace_scan_summary_path(workspace_root: Path) -> Path:
    """Return ``<workspace>/.sevn/skillspector-last-scan.json`` path.

    Args:
        workspace_root (Path): Workspace content root.

    Returns:
        Path: Summary file path (may not exist).

    Examples:
        >>> workspace_scan_summary_path(Path("/tmp/ws")).name
        'skillspector-last-scan.json'
    """
    return workspace_root / ".sevn" / WORKSPACE_SUMMARY_NAME


def write_workspace_scan_summary(
    workspace_root: Path,
    *,
    scanned_paths: Sequence[str],
    total_findings: int,
    high_critical: int,
) -> Path:
    """Persist a compact last-scan summary for doctor/CLI.

    Args:
        workspace_root (Path): Workspace content root.
        scanned_paths (Sequence[str]): Normalized paths scanned.
        total_findings (int): Count of issues at or above configured severities.
        high_critical (int): Count of HIGH/CRITICAL issues after baseline (if any).

    Returns:
        Path: Written summary file.

    Examples:
        >>> from tempfile import TemporaryDirectory
        >>> with TemporaryDirectory() as td:
        ...     p = write_workspace_scan_summary(
        ...         Path(td),
        ...         scanned_paths=["skills/user/a"],
        ...         total_findings=0,
        ...         high_critical=0,
        ...     )
        ...     p.is_file()
        True
    """
    out = workspace_scan_summary_path(workspace_root)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "scanned_at": time_ns(),
        "scanned_paths": list(scanned_paths),
        "total_findings": total_findings,
        "high_critical": high_critical,
    }
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out


def read_workspace_scan_summary(workspace_root: Path) -> dict[str, Any] | None:
    """Read last workspace scan summary when present.

    Args:
        workspace_root (Path): Workspace content root.

    Returns:
        dict[str, Any] | None: Parsed summary or ``None``.

    Examples:
        >>> read_workspace_scan_summary(Path("/nonexistent")) is None
        True
    """
    path = workspace_scan_summary_path(workspace_root)
    if not path.is_file():
        return None
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return blob if isinstance(blob, dict) else None


__all__ = [
    "DEFAULT_FAIL_SEVERITIES",
    "MEDIUM_PLUS_SEVERITIES",
    "BaselineSuppression",
    "ScanIssue",
    "ScanResult",
    "apply_baseline",
    "emit_security_scan_trace",
    "filter_by_severities",
    "load_baseline",
    "normalize_skill_path",
    "parse_skillspector_report",
    "read_workspace_scan_summary",
    "resolve_skillspector_command",
    "run_skillspector_subprocess",
    "scan_skill_path",
    "workspace_scan_summary_path",
    "write_workspace_scan_summary",
]
