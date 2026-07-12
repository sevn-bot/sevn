"""Golden routing and live replay smoke segments (`specs/33-self-improvement.md` §4.3).

Module: sevn.self_improve.eval.replay
Depends: asyncio, json, os, pathlib, sevn.agent.triager, sevn.config.workspace_config

Exports:
    EvalSegmentResult — one eval graph segment outcome.
    GoldenRoutingMetrics — accuracy counters for golden replay.
    GoldenRoutingReplayResult — segment + metrics bundle.
    LiveReplaySmokeResult — live replay segment outcome.
    golden_routing_fixture_path — resolve Wave 5 corpus on disk.
    strip_corpus_locale_prefix — remove ``[en]``/``[de]`` golden-corpus locale tags.
    run_golden_routing_replay — accuracy replay over the Wave 5 corpus.
    run_live_replay_smoke — replay or live_budget smoke (no silent pass).
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from sevn.agent.triager.context import (
    ApprovedUserTurn,
    RegistryIndexEntry,
    RegistrySnapshot,
    SessionView,
    TriagePromptContext,
)
from sevn.agent.triager.run import triage_turn
from sevn.config.workspace_config import parse_workspace_config
from sevn.self_improve.eval.baseline import parse_token_budget_daily

if TYPE_CHECKING:
    from sevn.config.workspace_config import WorkspaceConfig

_GOLDEN_ROUTING_CORPUS_REL = "tests/fixtures/triager/golden_routing.jsonl"
# Golden eval corpus prefixes messages with ``[en]`` / ``[de]`` locale tags — not used in production.
_CORPUS_LOCALE_PREFIX: re.Pattern[str] = re.compile(r"^\[[a-z]{2}\]\s*", re.I)
_GOLDEN_SMOKE_SAMPLE_ROWS = 12
_GOLDEN_SCHEMA_SAMPLE_ROWS = 12
DEFAULT_INTENT_MATCH_THRESHOLD = 0.95
DEFAULT_TOOLS_MATCH_THRESHOLD = 0.95
_CI_GOLDEN_SAMPLE_SIZE = 50
_LOCAL_GOLDEN_SAMPLE_SIZE = 200
_LIVE_REPLAY_TOKENS_PER_ROW = 500
_GOLDEN_REPLAY_SEED = 33
# Wave 5 corpus uses extended labels; map to ``Intent`` enum for replay/stub.
_CORPUS_INTENT_CANONICAL: dict[str, str] = {
    "GREETING": "GREETING",
    "NEW_REQUEST": "NEW_REQUEST",
    "UNKNOWN": "UNKNOWN",
    "FOLLOW_UP": "FOLLOWUP",
    "FOLLOWUP": "FOLLOWUP",
    "CLARIFICATION": "NEW_REQUEST",
    "FEEDBACK": "NEW_REQUEST",
}


@dataclass(frozen=True, slots=True)
class GoldenRoutingMetrics:
    """Accuracy counters produced by golden routing replay."""

    sampled: int
    total: int
    intent_matches: int
    complexity_matches: int
    intent_match_rate: float
    complexity_match_rate: float
    tools_matches: int
    tools_match_rate: float
    mismatches: tuple[dict[str, str], ...]


@dataclass(frozen=True, slots=True)
class GoldenRoutingReplayResult:
    """Golden routing segment outcome plus structured metrics."""

    segment: EvalSegmentResult
    metrics: GoldenRoutingMetrics


def strip_corpus_locale_prefix(message: str) -> str:
    """Strip golden-corpus locale tags such as ``[en]`` / ``[de]`` from a message.

    Production channel messages never carry these prefixes; only the eval harness
    corpus uses them for locale stratification.

    Args:
        message (str): Raw corpus or replay message text.

    Returns:
        str: Message with an optional leading ``[xx]`` tag removed.

    Examples:
        >>> strip_corpus_locale_prefix("[en] hello")
        'hello'
        >>> strip_corpus_locale_prefix("hello")
        'hello'
    """
    return _CORPUS_LOCALE_PREFIX.sub("", message.strip())


def golden_routing_fixture_path(*, repo_root: Path) -> Path:
    """Resolve the Wave 5 golden routing corpus under a repository root.

    Args:
        repo_root (Path): Checkout root containing ``tests/fixtures/triager/``.

    Returns:
        Path: Absolute path to ``golden_routing.jsonl``.

    Examples:
        >>> from pathlib import Path
        >>> golden_routing_fixture_path(repo_root=Path("/repo")).as_posix()
        '/repo/tests/fixtures/triager/golden_routing.jsonl'
    """
    return repo_root / _GOLDEN_ROUTING_CORPUS_REL


@dataclass(frozen=True, slots=True)
class EvalSegmentResult:
    """Outcome for a single evaluation graph segment."""

    name: str
    status: Literal["passed", "failed", "skipped"]
    detail: str


@dataclass(frozen=True, slots=True)
class LiveReplaySmokeResult:
    """Outcome for optional ``live_replay_smoke`` eval segment."""

    status: Literal["skipped", "passed", "failed"]
    reason: str


def run_golden_routing_replay(
    *,
    repo_root: Path,
    intent_threshold: float = DEFAULT_INTENT_MATCH_THRESHOLD,
    tools_threshold: float = DEFAULT_TOOLS_MATCH_THRESHOLD,
    sample_size: int | None = None,
) -> GoldenRoutingReplayResult:
    """Replay golden rows through Triager and compare intent/complexity/tools vs labels.

    When ``SEVN_TRIAGER_STUB=1``, injects per-row stub JSON from labels (recorded
    responses). Otherwise runs the live Triager transport (``SEVN_TRIAGER_STUB=0``).

    Args:
        repo_root (Path): Repository checkout containing ``tests/fixtures/triager/``.
        intent_threshold (float): Minimum intent match rate (default ``0.95``).
        tools_threshold (float): Minimum triager tool-list match rate (default ``0.95``).
        sample_size (int | None): Override stratified sample size; defaults to
            50 on CI and 200 locally.

    Returns:
        GoldenRoutingReplayResult: Segment status plus accuracy metrics.

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> td = Path(tempfile.mkdtemp())
        >>> corpus = td / "tests/fixtures/triager"
        >>> corpus.mkdir(parents=True)
        >>> _ = (corpus / "golden_routing.jsonl").write_text("", encoding="utf-8")
        >>> run_golden_routing_replay(repo_root=td).segment.status
        'failed'
    """
    path = golden_routing_fixture_path(repo_root=repo_root)
    if not path.is_file():
        segment = EvalSegmentResult(
            name="golden_routing",
            status="failed",
            detail=f"missing corpus at {path.as_posix()}",
        )
        return GoldenRoutingReplayResult(segment=segment, metrics=_empty_metrics())

    rows = _load_golden_rows(path)
    total = len(rows)
    if total < 200:
        segment = EvalSegmentResult(
            name="golden_routing",
            status="failed",
            detail=f"expected >=200 rows, got {total}",
        )
        return GoldenRoutingReplayResult(segment=segment, metrics=_empty_metrics(total=total))

    schema_err = _validate_golden_schema(rows)
    if schema_err is not None:
        segment = EvalSegmentResult(
            name="golden_routing",
            status="failed",
            detail=schema_err,
        )
        return GoldenRoutingReplayResult(segment=segment, metrics=_empty_metrics(total=total))

    max_rows = sample_size if sample_size is not None else _default_golden_sample_size()
    sampled_rows = _stratified_sample(rows, max_rows=max_rows, seed=_GOLDEN_REPLAY_SEED)
    metrics = _run_golden_accuracy(sampled_rows, corpus_total=total)
    passed = (
        metrics.intent_match_rate >= intent_threshold
        and metrics.tools_match_rate >= tools_threshold
    )
    detail = (
        f"sampled {metrics.sampled}/{metrics.total}; "
        f"intent_match_rate={metrics.intent_match_rate:.3f} "
        f"(threshold={intent_threshold:.2f}); "
        f"complexity_match_rate={metrics.complexity_match_rate:.3f}; "
        f"tools_match_rate={metrics.tools_match_rate:.3f} "
        f"(threshold={tools_threshold:.2f})"
    )
    if not passed and metrics.mismatches:
        first = metrics.mismatches[0]
        detail = f"{detail}; first_mismatch={first}"
    segment = EvalSegmentResult(
        name="golden_routing",
        status="passed" if passed else "failed",
        detail=detail,
    )
    return GoldenRoutingReplayResult(segment=segment, metrics=metrics)


def run_live_replay_smoke(
    *,
    workspace: WorkspaceConfig,
    job_bundle: Path,
    repo_root: Path | None = None,
    intent_threshold: float = DEFAULT_INTENT_MATCH_THRESHOLD,
) -> LiveReplaySmokeResult:
    """Run bounded replay or token-capped live smoke — never silently pass.

    ``eval_network=offline`` skips. ``replay`` runs a bounded golden slice with
    stub or live Triager. ``live_budget`` caps rows via ``eval.token_budget_daily``.

    Args:
        workspace (WorkspaceConfig): Active workspace configuration.
        job_bundle (Path): On-disk artefact directory for the job.
        repo_root (Path | None): Optional repository root for corpus resolution.
        intent_threshold (float): Intent accuracy gate for replay modes.

    Returns:
        LiveReplaySmokeResult: Segment outcome for eval report aggregation.

    Examples:
        >>> from pathlib import Path
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> run_live_replay_smoke(
        ...     workspace=WorkspaceConfig.minimal(),
        ...     job_bundle=Path("/tmp/x"),
        ... ).status
        'skipped'
    """
    si = workspace.self_improve
    network = "offline"
    if si is not None and si.eval is not None:
        network = si.eval.eval_network
    if network == "offline":
        return LiveReplaySmokeResult(
            status="skipped",
            reason="eval_network=offline",
        )

    root = repo_root if repo_root is not None else _resolve_repo_root(None)
    if network == "replay":
        return _run_replay_mode_smoke(
            repo_root=root,
            job_bundle=job_bundle,
            intent_threshold=intent_threshold,
        )
    if network == "live_budget":
        token_budget = parse_token_budget_daily(
            si.eval.token_budget_daily if si is not None and si.eval is not None else "100k",
        )
        return _run_live_budget_smoke(
            repo_root=root,
            job_bundle=job_bundle,
            token_budget=token_budget,
            intent_threshold=intent_threshold,
        )
    return LiveReplaySmokeResult(
        status="failed",
        reason=f"unsupported eval_network={network!r}",
    )


def _run_replay_mode_smoke(
    *,
    repo_root: Path,
    job_bundle: Path,
    intent_threshold: float,
) -> LiveReplaySmokeResult:
    """Execute bounded golden replay smoke for ``eval_network=replay``.

    Args:
        repo_root (Path): Repository checkout root.
        job_bundle (Path): Job artefact directory.
        intent_threshold (float): Intent accuracy gate.

    Returns:
        LiveReplaySmokeResult: Pass/fail outcome for the smoke segment.

    Examples:
        >>> _run_replay_mode_smoke.__name__
        '_run_replay_mode_smoke'
    """
    stub_on = _triager_stub_enabled()
    if not stub_on and not _live_triager_available():
        return LiveReplaySmokeResult(
            status="failed",
            reason=(
                "replay mode requires SEVN_TRIAGER_STUB=1 or a configured triager "
                f"provider (bundle={job_bundle!s})"
            ),
        )
    result = run_golden_routing_replay(
        repo_root=repo_root,
        intent_threshold=intent_threshold,
        sample_size=_GOLDEN_SMOKE_SAMPLE_ROWS,
    )
    if result.segment.status == "passed":
        return LiveReplaySmokeResult(
            status="passed",
            reason=f"replay slice {result.segment.detail}",
        )
    return LiveReplaySmokeResult(status="failed", reason=result.segment.detail)


def _run_live_budget_smoke(
    *,
    repo_root: Path,
    job_bundle: Path,
    token_budget: int,
    intent_threshold: float,
) -> LiveReplaySmokeResult:
    """Execute token-budget-capped smoke for ``eval_network=live_budget``.

    Args:
        repo_root (Path): Repository checkout root.
        job_bundle (Path): Job artefact directory.
        token_budget (int): Parsed daily token cap.
        intent_threshold (float): Intent accuracy gate.

    Returns:
        LiveReplaySmokeResult: Pass/fail outcome for the smoke segment.

    Examples:
        >>> _run_live_budget_smoke.__name__
        '_run_live_budget_smoke'
    """
    max_rows = max(1, token_budget // _LIVE_REPLAY_TOKENS_PER_ROW)
    stub_on = _triager_stub_enabled()
    if not stub_on and not _live_triager_available():
        return LiveReplaySmokeResult(
            status="failed",
            reason=(
                f"live_budget mode requires triager provider or SEVN_TRIAGER_STUB=1 "
                f"(budget={token_budget}, bundle={job_bundle!s})"
            ),
        )
    result = run_golden_routing_replay(
        repo_root=repo_root,
        intent_threshold=intent_threshold,
        sample_size=min(max_rows, _default_golden_sample_size()),
    )
    detail = f"live_budget tokens={token_budget} cap_rows={max_rows}; {result.segment.detail}"
    if result.segment.status == "passed":
        return LiveReplaySmokeResult(status="passed", reason=detail)
    return LiveReplaySmokeResult(status="failed", reason=detail)


def _empty_metrics(*, total: int = 0) -> GoldenRoutingMetrics:
    """Return zeroed metrics for failed or empty replays.

    Args:
        total (int): Corpus row count when known.

    Returns:
        GoldenRoutingMetrics: Zero accuracy counters.

    Examples:
        >>> _empty_metrics().intent_match_rate
        0.0
    """
    return GoldenRoutingMetrics(
        sampled=0,
        total=total,
        intent_matches=0,
        complexity_matches=0,
        intent_match_rate=0.0,
        complexity_match_rate=0.0,
        tools_matches=0,
        tools_match_rate=0.0,
        mismatches=(),
    )


def _load_golden_rows(path: Path) -> list[dict[str, Any]]:
    """Load parsed JSON objects from a golden routing JSONL file.

    Args:
        path (Path): Path to ``golden_routing.jsonl``.

    Returns:
        list[dict[str, Any]]: One dict per non-empty line.

    Examples:
        >>> _load_golden_rows.__name__
        '_load_golden_rows'
    """
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    return [json.loads(line) for line in lines]


def _validate_golden_schema(rows: list[dict[str, Any]]) -> str | None:
    """Validate a stratified golden sample against ``TriageResult`` schema.

    Args:
        rows (list[dict[str, Any]]): Full golden corpus rows.

    Returns:
        str | None: Error detail when invalid, else ``None``.

    Examples:
        >>> _validate_golden_schema([]) is None
        True
    """
    from sevn.agent.triager.models import TriageResult

    sample = _stratified_sample(
        rows,
        max_rows=_GOLDEN_SCHEMA_SAMPLE_ROWS,
        seed=_GOLDEN_REPLAY_SEED,
    )
    for idx, row in enumerate(sample):
        if "message" not in row or "labels" not in row:
            return f"row {idx} missing message/labels keys"
        labels = row["labels"]
        payload = _labels_to_triage_payload(labels)
        try:
            TriageResult.model_validate(payload, context={"relax_greeting_lists": False})
        except Exception as exc:
            return f"row {idx} labels invalid: {exc}"
    return None


def _canonicalize_corpus_intent(raw_intent: str) -> str:
    """Map Wave 5 corpus intent labels to ``Intent`` enum strings.

    Args:
        raw_intent (str): Label from ``golden_routing.jsonl``.

    Returns:
        str: Canonical intent accepted by ``TriageResult``.

    Examples:
        >>> _canonicalize_corpus_intent("FOLLOW_UP")
        'FOLLOWUP'
    """
    token = raw_intent.strip().upper()
    return _CORPUS_INTENT_CANONICAL.get(token, "UNKNOWN")


def _labels_to_triage_payload(labels: dict[str, Any]) -> dict[str, Any]:
    """Build a ``TriageResult``-compatible payload from golden labels.

    Args:
        labels (dict[str, Any]): ``labels`` object from a golden row.

    Returns:
        dict[str, Any]: Payload for validation or stub injection.

    Examples:
        >>> _labels_to_triage_payload({"intent": "GREETING", "complexity": "A"})["intent"]
        'GREETING'
    """
    canonical_intent = _canonicalize_corpus_intent(str(labels["intent"]))
    payload = {
        "intent": canonical_intent,
        "complexity": labels["complexity"],
        "first_message": "fixture",
        "tools": labels.get("tools", []),
        "skills": labels.get("skills", []),
        "mcp_servers_required": labels.get("mcp_servers_required", []),
        "confidence": 0.5,
        "requires_vision": False,
        "requires_document": False,
        "disregard": labels.get("disregard", False),
    }
    if canonical_intent == "GREETING":
        payload["tools"] = []
        payload["skills"] = []
    return payload


def _labels_to_stub_json(labels: dict[str, Any]) -> str:
    """Serialize label-derived stub JSON for ``SEVN_TRIAGER_STUB_JSON``.

    Args:
        labels (dict[str, Any]): Golden row labels.

    Returns:
        str: JSON body for stub transport.

    Examples:
        >>> '"intent"' in _labels_to_stub_json({"intent": "GREETING", "complexity": "A"})
        True
    """
    payload = _labels_to_triage_payload(labels)
    payload["first_message"] = "Replay stub reply."
    return json.dumps(payload)


def _default_golden_sample_size() -> int:
    """Resolve default golden replay sample size for the current environment.

    Returns:
        int: Row cap (50 on CI, 200 locally, or ``SEVN_EVAL_GOLDEN_SAMPLE``).

    Examples:
        >>> _default_golden_sample_size() >= 1
        True
    """
    override = os.environ.get("SEVN_EVAL_GOLDEN_SAMPLE", "").strip()
    if override.isdigit():
        return max(1, int(override))
    if os.environ.get("CI", "").strip().lower() in ("1", "true", "yes"):
        return _CI_GOLDEN_SAMPLE_SIZE
    if os.environ.get("GITHUB_ACTIONS", "").strip().lower() == "true":
        return _CI_GOLDEN_SAMPLE_SIZE
    return _LOCAL_GOLDEN_SAMPLE_SIZE


def _stratified_sample(
    rows: list[dict[str, Any]],
    *,
    max_rows: int,
    seed: int,
) -> list[dict[str, Any]]:
    """Pick up to ``max_rows`` rows with per-intent representation.

    Args:
        rows (list[dict[str, Any]]): Full golden corpus.
        max_rows (int): Maximum rows to return.
        seed (int): Deterministic shuffle seed.

    Returns:
        list[dict[str, Any]]: Stratified subset.

    Examples:
        >>> _stratified_sample([{"labels": {"intent": "GREETING"}}], max_rows=1, seed=1)
        [{'labels': {'intent': 'GREETING'}}]
    """
    if len(rows) <= max_rows:
        return list(rows)
    by_intent: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        intent = str(row.get("labels", {}).get("intent", "UNKNOWN"))
        by_intent[intent].append(row)
    rng = random.Random(seed)  # nosec B311 — deterministic eval sampling, not crypto
    intents = sorted(by_intent)
    per_intent = max(1, max_rows // max(1, len(intents)))
    picked: list[dict[str, Any]] = []
    for intent in intents:
        bucket = list(by_intent[intent])
        rng.shuffle(bucket)
        picked.extend(bucket[:per_intent])
    if len(picked) < max_rows:
        remaining = [row for row in rows if row not in picked]
        rng.shuffle(remaining)
        picked.extend(remaining[: max_rows - len(picked)])
    return picked[:max_rows]


def _build_eval_registry_snapshot(rows: list[dict[str, Any]]) -> RegistrySnapshot:
    """Build a registry snapshot covering tools/skills referenced in golden rows.

    Args:
        rows (list[dict[str, Any]]): Golden routing rows under evaluation.

    Returns:
        RegistrySnapshot: Snapshot so triager identifier filtering preserves labels.

    Examples:
        >>> snap = _build_eval_registry_snapshot([{"labels": {"tools": ["read"], "skills": []}}])
        >>> snap.tools[0].identifier
        'read'
    """
    tool_ids: set[str] = set()
    skill_ids: set[str] = set()
    mcp_ids: set[str] = set()
    for row in rows:
        labels = row.get("labels", {})
        if not isinstance(labels, dict):
            continue
        for tool in labels.get("tools", []):
            tool_ids.add(str(tool))
        for skill in labels.get("skills", []):
            skill_ids.add(str(skill))
        for mcp in labels.get("mcp_servers_required", []):
            mcp_ids.add(str(mcp))
    tools = [
        RegistryIndexEntry(sort_name=name, identifier=name, display_line=f"- {name}")
        for name in sorted(tool_ids)
    ]
    skills = [
        RegistryIndexEntry(sort_name=name, identifier=name, display_line=f"- {name}")
        for name in sorted(skill_ids)
    ]
    mcp_servers = [
        RegistryIndexEntry(sort_name=name, identifier=name, display_line=f"- {name}")
        for name in sorted(mcp_ids)
    ]
    return RegistrySnapshot(
        tools=tools,
        skills=skills,
        mcp_servers=mcp_servers,
        registry_version=1,
    )


def _run_golden_accuracy(
    rows: list[dict[str, Any]],
    *,
    corpus_total: int | None = None,
) -> GoldenRoutingMetrics:
    """Run Triager on sampled rows and compare intent/complexity vs labels.

    Args:
        rows (list[dict[str, Any]]): Sampled golden rows.
        corpus_total (int | None): Full corpus size for reporting.

    Returns:
        GoldenRoutingMetrics: Accuracy counters and mismatch samples.

    Examples:
        >>> _run_golden_accuracy([]).sampled
        0
    """
    if not rows:
        return _empty_metrics(total=corpus_total or 0)
    workspace = parse_workspace_config(
        {
            "schema_version": 1,
            "triager": {"fast_greeting_path": True, "relax_greeting_lists": False},
            "providers": {"tier_default": {"triager": "stub/model"}},
            "permissions": {"scope_narrowing": {"enabled": False}},
            "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},  # nosec B105
        },
    )
    intent_matches = 0
    complexity_matches = 0
    tools_matches = 0
    mismatches: list[dict[str, str]] = []
    registry_snapshot = _build_eval_registry_snapshot(rows)
    stub_on = _triager_stub_enabled()
    prev_stub_json = os.environ.get("SEVN_TRIAGER_STUB_JSON")
    prev_fixture = os.environ.get("SEVN_TRIAGER_STUB_FIXTURE_PATH")
    prev_eval_replay = os.environ.get("SEVN_TRIAGER_EVAL_REPLAY")
    try:
        os.environ["SEVN_TRIAGER_EVAL_REPLAY"] = "1"
        if stub_on:
            os.environ.pop("SEVN_TRIAGER_STUB_FIXTURE_PATH", None)
        for row in rows:
            labels = row["labels"]
            message = strip_corpus_locale_prefix(str(row.get("message", "")))
            if stub_on:
                os.environ["SEVN_TRIAGER_STUB_JSON"] = _labels_to_stub_json(labels)
            result = asyncio.run(
                triage_turn(
                    workspace=workspace,
                    session=SessionView(session_id="eval-replay", chat_member_count=1),
                    incoming=ApprovedUserTurn(text=message),
                    registry_snapshot=registry_snapshot,
                    triage_context=TriagePromptContext(
                        current_message=message,
                        turn_id=str(row.get("id", "replay")),
                    ),
                ),
            )
            expected_intent = _canonicalize_corpus_intent(str(labels["intent"]))
            expected_complexity = str(labels["complexity"])
            actual_intent = (
                result.intent.value if hasattr(result.intent, "value") else str(result.intent)
            )
            actual_complexity = (
                result.complexity.value
                if hasattr(result.complexity, "value")
                else str(result.complexity)
            )
            if actual_intent == expected_intent:
                intent_matches += 1
            else:
                mismatches.append(
                    {
                        "id": str(row.get("id", "")),
                        "expected_intent": expected_intent,
                        "actual_intent": actual_intent,
                    },
                )
            if actual_complexity == expected_complexity:
                complexity_matches += 1
            expected_tools = sorted(str(t) for t in labels.get("tools", []))
            actual_tools = sorted(str(t) for t in result.tools)
            if actual_tools == expected_tools:
                tools_matches += 1
    finally:
        if prev_eval_replay is None:
            os.environ.pop("SEVN_TRIAGER_EVAL_REPLAY", None)
        else:
            os.environ["SEVN_TRIAGER_EVAL_REPLAY"] = prev_eval_replay
        if prev_stub_json is None:
            os.environ.pop("SEVN_TRIAGER_STUB_JSON", None)
        else:
            os.environ["SEVN_TRIAGER_STUB_JSON"] = prev_stub_json
        if prev_fixture is None:
            os.environ.pop("SEVN_TRIAGER_STUB_FIXTURE_PATH", None)
        else:
            os.environ["SEVN_TRIAGER_STUB_FIXTURE_PATH"] = prev_fixture

    sampled = len(rows)
    intent_rate = intent_matches / sampled
    complexity_rate = complexity_matches / sampled
    tools_rate = tools_matches / sampled
    return GoldenRoutingMetrics(
        sampled=sampled,
        total=corpus_total if corpus_total is not None else sampled,
        intent_matches=intent_matches,
        complexity_matches=complexity_matches,
        intent_match_rate=intent_rate,
        complexity_match_rate=complexity_rate,
        tools_matches=tools_matches,
        tools_match_rate=tools_rate,
        mismatches=tuple(mismatches[:5]),
    )


def _triager_stub_enabled() -> bool:
    """Return whether ``SEVN_TRIAGER_STUB`` enables canned Triager responses.

    Returns:
        bool: ``True`` when stub transport is active.

    Examples:
        >>> isinstance(_triager_stub_enabled(), bool)
        True
    """
    raw = os.environ.get("SEVN_TRIAGER_STUB", "0")
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _live_triager_available() -> bool:
    """Return whether a non-stub triager provider appears configured.

    Returns:
        bool: ``True`` when ``resolve_main_model_id`` is not a stub placeholder.

    Examples:
        >>> isinstance(_live_triager_available(), bool)
        True
    """
    from sevn.config.model_resolution import resolve_main_model_id

    try:
        ws = parse_workspace_config(
            {"schema_version": 1, "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"}}  # nosec B105
        )
        model_id = resolve_main_model_id(ws)
    except Exception:
        return False
    token = str(model_id).strip().lower()
    return token not in ("", "stub/model", "stub")


def _resolve_repo_root(explicit: Path | None) -> Path:
    """Locate the repository root containing the golden routing corpus.

    Args:
        explicit (Path | None): Caller-provided root when known.

    Returns:
        Path: Best-effort repository checkout root.

    Examples:
        >>> from pathlib import Path
        >>> _resolve_repo_root(Path("/repo")).as_posix()
        '/repo'
    """
    if explicit is not None:
        return explicit
    env = os.environ.get("SEVN_REPO_ROOT", "").strip()
    if env:
        return Path(env)
    here = Path.cwd()
    for candidate in (here, *here.parents):
        if golden_routing_fixture_path(repo_root=candidate).is_file():
            return candidate
    return here
