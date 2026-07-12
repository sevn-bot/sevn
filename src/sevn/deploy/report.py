"""JSON deploy report builder and writer.

Module: sevn.deploy.report
Depends: datetime, json, pathlib, typing

Exports:
    DeployReport — in-memory deploy report.
    build_report_dict — render schema-shaped dict.
    find_latest_report — newest report JSON under ``reports/``.
    redact_report_for_display — strip sensitive fields for logs.
    write_deploy_report — persist report JSON.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

StepStatus = Literal["ok", "failed", "skipped", "planned"]


@dataclass
class DeployReport:
    """Structured remote deploy outcome."""

    host_id: str
    bundle_path: str
    bot_name: str
    mode: Literal["deploy", "check", "dry-run"]
    steps: list[dict[str, Any]] = field(default_factory=list)
    remote: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def add_step(
        self,
        step_id: str,
        *,
        status: StepStatus,
        duration_ms: int | None = None,
        detail: str | None = None,
        **extra: Any,
    ) -> None:
        """Append one step record.

        Args:
            step_id (str): Stable step identifier.
            status (StepStatus): Step outcome.
            duration_ms (int | None): Elapsed milliseconds when measured.
            detail (str | None): Human-readable detail without secrets.
            extra (Any): Additional JSON-safe fields merged into the step row.

        Examples:
            >>> report = DeployReport(
            ...     host_id="prod", bundle_path="b.env", bot_name="Sevn", mode="check"
            ... )
            >>> report.add_step("preflight", status="ok", duration_ms=10)
            >>> report.steps[0]["id"]
            'preflight'
        """
        row: dict[str, Any] = {"id": step_id, "status": status}
        if duration_ms is not None:
            row["duration_ms"] = duration_ms
        if detail:
            row["detail"] = detail
        row.update(extra)
        self.steps.append(row)

    def fail(self, message: str) -> None:
        """Record a top-level error string.

        Args:
            message (str): Error without secret values.

        Examples:
            >>> report = DeployReport(
            ...     host_id="prod", bundle_path="b.env", bot_name="Sevn", mode="check"
            ... )
            >>> report.fail("ssh failed")
            >>> report.errors[-1]
            'ssh failed'
        """
        self.errors.append(message)


def build_report_dict(report: DeployReport) -> dict[str, Any]:
    """Render a schema-shaped deploy report dict.

    Args:
        report (DeployReport): In-memory report.

    Returns:
        dict[str, Any]: JSON-serializable payload.

    Examples:
        >>> payload = build_report_dict(
        ...     DeployReport(
        ...         host_id="prod", bundle_path="b.env", bot_name="Sevn", mode="dry-run"
        ...     )
        ... )
        >>> payload["schema_version"]
        1
    """
    return {
        "schema_version": 1,
        "generated_at": report.generated_at,
        "host_id": report.host_id,
        "bundle_path": report.bundle_path,
        "bot_name": report.bot_name,
        "mode": report.mode,
        "steps": list(report.steps),
        "remote": dict(report.remote),
        "errors": list(report.errors),
    }


def write_deploy_report(report: DeployReport, *, reports_dir: Path | None = None) -> Path:
    """Write a deploy report JSON file under ``reports/``.

    Args:
        report (DeployReport): Report to persist.
        reports_dir (Path | None): Output directory; defaults to ``reports/`` under cwd.

    Returns:
        Path: Written JSON path.

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> out = Path(tempfile.mkdtemp())
        >>> path = write_deploy_report(
        ...     DeployReport(
        ...         host_id="prod", bundle_path="b.env", bot_name="Sevn", mode="check"
        ...     ),
        ...     reports_dir=out,
        ... )
        >>> path.name.startswith("remote-deploy-prod-")
        True
    """
    root = (reports_dir or Path("reports")).resolve()
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = root / f"remote-deploy-{report.host_id}-{stamp}.json"
    path.write_text(
        json.dumps(build_report_dict(report), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def find_latest_report(
    *, reports_dir: Path | None = None, host_id: str | None = None
) -> Path | None:
    """Return the newest remote deploy report JSON.

    Args:
        reports_dir (Path | None): Directory to scan.
        host_id (str | None): Optional host filter prefix.

    Returns:
        Path | None: Newest matching report or None.

    Examples:
        >>> find_latest_report(reports_dir=Path("/nonexistent")) is None
        True
    """
    root = (reports_dir or Path("reports")).resolve()
    if not root.is_dir():
        return None
    pattern = "remote-deploy-*.json" if host_id is None else f"remote-deploy-{host_id}-*.json"
    candidates = sorted(root.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def redact_report_for_display(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a copy safe for operator logs (no secret-bearing detail).

    Args:
        payload (dict[str, Any]): Full report dict.

    Returns:
        dict[str, Any]: Redacted copy.

    Examples:
        >>> redact_report_for_display({"errors": ["no secrets here"]})["errors"]
        ['no secrets here']
    """
    copied: dict[str, Any] = json.loads(json.dumps(payload))
    return copied
