"""Native-vs-FunctionModel parity harness for golden_llm (W12).

Module: tests.fixtures.golden_llm.parity
Depends: tests.fixtures.golden_llm.evaluators, tests.fixtures.golden_llm.harness

Exports:
    ParitySnapshot — tool list + final text comparison bundle.
    ParityCaseResult — one case parity outcome.
    ParityReport — aggregate parity report for a slot flip gate.
    compare_snapshots — structural diff between two snapshots.
    baseline_from_recording — FunctionModel baseline from W11 recording.
    load_native_snapshot — optional native recording sidecar.
    run_parity_report — tokenless parity over a case subset.
    slot_flip_blocked — whether native diverges from FunctionModel baseline.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tests.fixtures.golden_llm.eval_runner import build_replay_task, configure_golden_eval_otel
from tests.fixtures.golden_llm.evaluators import (
    GoldenRunOutput,
    snapshot_from_output,
    snapshot_from_recording,
)
from tests.fixtures.golden_llm.harness import (
    GOLDEN_LLM_ROOT,
    GoldenRecording,
    discover_cases,
    load_recording,
)

NATIVE_SNAPSHOTS_ROOT = GOLDEN_LLM_ROOT / "native_snapshots"


@dataclass(frozen=True, slots=True)
class ParitySnapshot:
    """Tool names + assistant text used for parity comparison."""

    tool_names: tuple[str, ...]
    final_text: str

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ParitySnapshot:
        """Build from a JSON-serializable mapping.

        Args:
            payload (dict[str, Any]): ``tool_names`` + ``final_text`` keys.

        Returns:
            ParitySnapshot: Parsed snapshot.

        Examples:
            >>> ParitySnapshot.from_dict({"tool_names": ["read"], "final_text": "ok"}).final_text
            'ok'
        """
        names = payload.get("tool_names", [])
        if not isinstance(names, list):
            names = []
        return cls(
            tool_names=tuple(str(n) for n in names), final_text=str(payload.get("final_text", ""))
        )


@dataclass(frozen=True, slots=True)
class ParityCaseResult:
    """Parity outcome for one golden case."""

    case_id: str
    matched: bool
    function_model: ParitySnapshot
    native: ParitySnapshot | None
    detail: str


@dataclass(frozen=True, slots=True)
class ParityReport:
    """Aggregate native-vs-FunctionModel parity for a case subset."""

    case_results: tuple[ParityCaseResult, ...]
    matched_count: int
    total: int

    @property
    def match_rate(self) -> float:
        """Return the fraction of cases at parity."""
        return self.matched_count / self.total if self.total else 0.0


def baseline_from_recording(recording: GoldenRecording) -> ParitySnapshot:
    """Derive the FunctionModel baseline snapshot from a W11 recording.

    Args:
        recording (GoldenRecording): Recorded transport script + provider trace.

    Returns:
        ParitySnapshot: Baseline tool list and final text.

    Examples:
        >>> baseline_from_recording(GoldenRecording(case_id="x", transport_responses=[])).final_text
        ''
    """
    payload = snapshot_from_recording(recording=recording)
    return ParitySnapshot.from_dict(payload)


def load_native_snapshot(case_id: str) -> ParitySnapshot | None:
    """Load an optional post-build native snapshot sidecar when present.

    Args:
        case_id (str): Golden case id.

    Returns:
        ParitySnapshot | None: Native path snapshot or ``None`` when not recorded.

    Examples:
        >>> load_native_snapshot("missing-case-id") is None
        True
    """
    path = NATIVE_SNAPSHOTS_ROOT / f"{case_id}.json"
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return ParitySnapshot.from_dict(payload)


def save_native_snapshot(case_id: str, snapshot: ParitySnapshot) -> Path:
    """Persist a native snapshot sidecar (post-build manual record step).

    Args:
        case_id (str): Golden case id.
        snapshot (ParitySnapshot): Native path outcome.

    Returns:
        Path: Written JSON path under ``native_snapshots/``.

    Examples:
        >>> path = save_native_snapshot("x", ParitySnapshot(tool_names=("read",), final_text="ok"))
        >>> path.parent.name
        'native_snapshots'
    """
    NATIVE_SNAPSHOTS_ROOT.mkdir(parents=True, exist_ok=True)
    path = NATIVE_SNAPSHOTS_ROOT / f"{case_id}.json"
    path.write_text(
        json.dumps(
            {"tool_names": list(snapshot.tool_names), "final_text": snapshot.final_text},
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def compare_snapshots(
    *,
    baseline: ParitySnapshot,
    candidate: ParitySnapshot,
) -> tuple[bool, str]:
    """Compare two parity snapshots for tool-list + final-text equality.

    Args:
        baseline (ParitySnapshot): FunctionModel or recorded baseline.
        candidate (ParitySnapshot): Replay or native candidate.

    Returns:
        tuple[bool, str]: ``(matched, detail)`` pair.

    Examples:
        >>> a = ParitySnapshot(tool_names=("read",), final_text="hello")
        >>> compare_snapshots(baseline=a, candidate=a)[0]
        True
    """
    if baseline.tool_names != candidate.tool_names:
        return (
            False,
            f"tool_names {list(candidate.tool_names)!r} != baseline {list(baseline.tool_names)!r}",
        )
    if baseline.final_text.strip().lower() != candidate.final_text.strip().lower():
        return (
            False,
            f"final_text diverges: {candidate.final_text[:80]!r}",
        )
    return True, "matched"


async def _replay_snapshot(case_id: str) -> ParitySnapshot:
    task = build_replay_task()
    output: GoldenRunOutput = await task(case_id)
    return ParitySnapshot.from_dict(snapshot_from_output(output))


async def run_parity_report(
    *,
    case_ids: tuple[str, ...] | None = None,
) -> ParityReport:
    """Score FunctionModel replay vs recording baseline; optional native sidecars.

    Tokenless: replays use W11 transport scripts. Native sidecars under
    ``native_snapshots/`` are compared when present (post-build manual record).

    Args:
        case_ids (tuple[str, ...] | None): Subset to score; default all recorded cases.

    Returns:
        ParityReport: Per-case parity outcomes.

    Examples:
        >>> import asyncio
        >>> report = asyncio.run(run_parity_report(case_ids=("read_01",)))
        >>> report.total >= 1
        True
    """
    configure_golden_eval_otel()
    cases = discover_cases()
    if case_ids is not None:
        wanted = set(case_ids)
        cases = [case for case in cases if case.id in wanted]
    results: list[ParityCaseResult] = []
    matched = 0
    for case in cases:
        recording = load_recording(case)
        if recording is None:
            continue
        baseline = baseline_from_recording(recording)
        replay = await _replay_snapshot(case.id)
        replay_ok, replay_detail = compare_snapshots(baseline=baseline, candidate=replay)
        native = load_native_snapshot(case.id)
        if native is None:
            results.append(
                ParityCaseResult(
                    case_id=case.id,
                    matched=replay_ok,
                    function_model=baseline,
                    native=None,
                    detail=replay_detail if replay_ok else f"replay: {replay_detail}",
                ),
            )
            if replay_ok:
                matched += 1
            continue
        native_ok, native_detail = compare_snapshots(baseline=baseline, candidate=native)
        ok = replay_ok and native_ok
        detail = "matched"
        if not replay_ok:
            detail = f"replay: {replay_detail}"
        elif not native_ok:
            detail = f"native: {native_detail}"
        results.append(
            ParityCaseResult(
                case_id=case.id,
                matched=ok,
                function_model=baseline,
                native=native,
                detail=detail,
            ),
        )
        if ok:
            matched += 1
    return ParityReport(case_results=tuple(results), matched_count=matched, total=len(results))


def slot_flip_blocked(report: ParityReport) -> bool:
    """Return whether a default-native slot flip must remain blocked.

    Args:
        report (ParityReport): Parity report from :func:`run_parity_report`.

    Returns:
        bool: ``True`` when any scored case diverges (blocks default-native flip).

    Examples:
        >>> slot_flip_blocked(ParityReport(case_results=(), matched_count=0, total=0))
        False
    """
    if report.total == 0:
        return False
    return report.matched_count < report.total


__all__ = [
    "NATIVE_SNAPSHOTS_ROOT",
    "ParityCaseResult",
    "ParityReport",
    "ParitySnapshot",
    "baseline_from_recording",
    "compare_snapshots",
    "load_native_snapshot",
    "run_parity_report",
    "save_native_snapshot",
    "slot_flip_blocked",
]
