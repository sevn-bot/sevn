"""Last-known-good baseline and eval report deltas (`specs/33-self-improvement.md` §4.3).

Module: sevn.self_improve.eval.baseline
Depends: json, pathlib, sevn.self_improve.eval.replay

Exports:
    LastKnownGoodRecord — persisted baseline metrics snapshot.
    baseline_path_for_job_bundle — resolve ``last_known_good.json`` beside jobs.
    baseline_section_for_report — serialize baseline for eval report v2.
    compute_metric_deltas — metric diff vs baseline.
    load_last_known_good — read baseline file when present.
    parse_token_budget_daily — parse ``eval.token_budget_daily`` suffixes.
    save_last_known_good — write baseline snapshot atomically.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path  # noqa: TC003 — runtime bundle paths in load/save helpers
from typing import Any

_LAST_KNOWN_GOOD_NAME = "last_known_good.json"
_TOKEN_BUDGET_SUFFIX = re.compile(r"^([0-9]+(?:\.[0-9]+)?)([kKmM])?$")


@dataclass(frozen=True, slots=True)
class LastKnownGoodRecord:
    """On-disk last-known-good metrics snapshot."""

    baseline_branch: str
    baseline_sha: str
    metrics: dict[str, float]
    recorded_at: str


def baseline_path_for_job_bundle(job_bundle: Path) -> Path:
    """Resolve ``.sevn/improve/last_known_good.json`` from a job bundle path.

    Args:
        job_bundle (Path): ``.sevn/improve/jobs/<job_id>/`` directory.

    Returns:
        Path: ``.sevn/improve/last_known_good.json`` beside the jobs folder.

    Examples:
        >>> baseline_path_for_job_bundle(
        ...     Path("/ws/.sevn/improve/jobs/job-1"),
        ... ).as_posix()
        '/ws/.sevn/improve/last_known_good.json'
    """
    return job_bundle.parent.parent / _LAST_KNOWN_GOOD_NAME


def load_last_known_good(path: Path) -> LastKnownGoodRecord | None:
    """Load baseline metrics when ``last_known_good.json`` exists.

    Args:
        path (Path): Absolute path to the baseline file.

    Returns:
        LastKnownGoodRecord | None: Parsed record, or ``None`` when missing.

    Examples:
        >>> load_last_known_good(Path("/missing/last_known_good.json")) is None
        True
    """
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    metrics_raw = data.get("metrics", {})
    metrics = {str(k): float(v) for k, v in metrics_raw.items()}
    return LastKnownGoodRecord(
        baseline_branch=str(data.get("baseline_branch", "main")),
        baseline_sha=str(data.get("baseline_sha", "")),
        metrics=metrics,
        recorded_at=str(data.get("recorded_at", "")),
    )


def save_last_known_good(
    *,
    path: Path,
    metrics: dict[str, float],
    baseline_branch: str | None = None,
    baseline_sha: str | None = None,
) -> None:
    """Persist a last-known-good metrics snapshot.

    Args:
        path (Path): Destination ``last_known_good.json`` path.
        metrics (dict[str, float]): Metric name → value map.
        baseline_branch (str | None): Git branch label; defaults to env or ``main``.
        baseline_sha (str | None): Git SHA; defaults to env when unset.

    Returns:
        None: Writes JSON atomically via temp file + rename.

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> td = Path(tempfile.mkdtemp())
        >>> p = td / "last_known_good.json"
        >>> save_last_known_good(path=p, metrics={"golden_routing.intent_match_rate": 1.0})
        >>> load_last_known_good(p) is not None
        True
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    branch = baseline_branch or os.environ.get("SEVN_BASELINE_BRANCH", "main")
    sha = baseline_sha or os.environ.get("SEVN_BASELINE_SHA", "")
    payload = {
        "baseline_branch": branch,
        "baseline_sha": sha,
        "metrics": metrics,
        "recorded_at": datetime.now(tz=UTC).isoformat(),
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def compute_metric_deltas(
    *,
    current: dict[str, float],
    baseline: dict[str, float],
) -> dict[str, float]:
    """Compute ``current - baseline`` for shared metric keys.

    Args:
        current (dict[str, float]): Metrics from the present eval run.
        baseline (dict[str, float]): Metrics from ``last_known_good.json``.

    Returns:
        dict[str, float]: Delta per metric key present in either map.

    Examples:
        >>> deltas = compute_metric_deltas(
        ...     current={"golden_routing.intent_match_rate": 0.98},
        ...     baseline={"golden_routing.intent_match_rate": 1.0},
        ... )
        >>> round(deltas["golden_routing.intent_match_rate"], 2)
        -0.02
    """
    keys = sorted(set(current) | set(baseline))
    return {key: float(current.get(key, 0.0)) - float(baseline.get(key, 0.0)) for key in keys}


def parse_token_budget_daily(raw: str | int) -> int:
    """Parse ``eval.token_budget_daily`` human suffixes or raw integers.

    Args:
        raw (str | int): Config value such as ``100k`` or ``50000``.

    Returns:
        int: Token budget as a positive integer.

    Examples:
        >>> parse_token_budget_daily("100k")
        100000
        >>> parse_token_budget_daily(2500)
        2500
    """
    if isinstance(raw, int):
        return max(1, raw)
    text = raw.strip().lower()
    match = _TOKEN_BUDGET_SUFFIX.match(text)
    if not match:
        return max(1, int(text))
    value = float(match.group(1))
    suffix = match.group(2) or ""
    if suffix == "k":
        return max(1, int(value * 1_000))
    if suffix == "m":
        return max(1, int(value * 1_000_000))
    return max(1, int(value))


def baseline_section_for_report(record: LastKnownGoodRecord | None) -> dict[str, Any] | None:
    """Serialize baseline metadata for ``eval_report.json`` schema v2.

    Args:
        record (LastKnownGoodRecord | None): Loaded baseline or ``None``.

    Returns:
        dict[str, Any] | None: Baseline block, or ``None`` when no file exists.

    Examples:
        >>> baseline_section_for_report(None) is None
        True
    """
    if record is None:
        return None
    return {
        "baseline_branch": record.baseline_branch,
        "baseline_sha": record.baseline_sha,
        "metrics": record.metrics,
        "recorded_at": record.recorded_at,
    }
