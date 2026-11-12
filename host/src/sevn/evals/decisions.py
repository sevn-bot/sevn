"""Replay synthetic routing cases through the decider chain (D17)."""

from __future__ import annotations

import asyncio
import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from sevn.config import Settings
from sevn.decisions.base import ContextProfile
from sevn.decisions.registry import decide
from sevn.domain.routing import OpenAgent, PendingQuestion, RoutedMessage, RouterContext
from sevn.evals.errors import EvalsError
from sevn.evals.judge import RouteScore, score_routes
from sevn.log import logger


class _Agent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    title: str
    summary: str = ""
    status: str = "idle"


def _no_agents() -> list[_Agent]:
    return []


class _Case(BaseModel):
    """One synthetic routing case. Messages are not taken from a user log."""

    model_config = ConfigDict(extra="ignore")

    intent: str
    target: str = "none"
    text: str
    open_agents: list[_Agent] = Field(default_factory=_no_agents)
    explicit_target: str | None = None
    delivery: Literal["steer", "queue"] | None = None
    profile: ContextProfile | None = None
    pending_agent_id: str | None = None
    pending_minutes_ago: int | None = None


@dataclass(frozen=True, slots=True)
class EvalOutcome:
    """Whether the harness stayed off, and the report path when it ran."""

    disabled: bool
    path: Path | None


def run_decisions() -> EvalOutcome:
    """Replay ``host/evals/decisions`` when ``evals_on`` is set. Otherwise do nothing."""
    if not Settings.load().decisions.evals_on:
        return EvalOutcome(disabled=True, path=None)
    cases = _load_cases()
    report = asyncio.run(_evaluate(cases))
    path = _write_report(report)
    logger.info("decision evals wrote a report")
    return EvalOutcome(disabled=False, path=path)


def _load_cases() -> list[_Case]:
    folder = _repo_root() / "host" / "evals" / "decisions"
    files = sorted(folder.glob("*.jsonl")) if folder.is_dir() else []
    if not files:
        raise EvalsError("decision eval datasets are missing")
    cases: list[_Case] = []
    for path in files:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip() == "":
                continue
            try:
                cases.append(_Case.model_validate_json(line))
            except ValidationError as exc:
                raise EvalsError(f"invalid eval case in {path.name}") from exc
    if not cases:
        raise EvalsError("decision eval datasets are empty")
    return cases


async def _evaluate(cases: list[_Case]) -> dict[str, object]:
    if not cases:
        raise EvalsError("decision eval datasets are empty")
    scores: list[RouteScore] = []
    matrix = {label: {"steer": 0, "queue": 0, "unresolved": 0} for label in ("steer", "queue")}
    source_hits = dict.fromkeys(ContextProfile.model_fields, 0)
    exact = profiles = 0
    for case in cases:
        now = _utcnow()
        decision = await decide(_message(case, now), _context(case, now), record=False)
        if case.delivery:
            matrix[case.delivery][decision.delivery_policy or "unresolved"] += 1
        if case.profile:
            profiles += 1
            actual = decision.context_profile.model_dump()
            exact += int(decision.context_profile == case.profile)
            for source, label in case.profile.model_dump().items():
                source_hits[source] += int(actual[source] == label)
        if case.delivery is None and case.profile is None:
            scores.append(
                RouteScore(
                    text=case.text,
                    intent=case.intent,
                    predicted_intent=decision.intent,
                    target=case.target,
                    predicted_target=_target(decision.target_agent_id),
                )
            )
    return {
        "accuracy": _accuracy(scores) if scores else {},
        "judge": (
            await score_routes(scores)
            if scores
            else {"status": "skipped", "reason": "no routing cases"}
        ),
        "delivery": _delivery_metrics(matrix),
        "context": {
            "cases": profiles,
            "exact_accuracy": exact / profiles if profiles else None,
            "source_accuracy": {
                key: hits / profiles for key, hits in source_hits.items() if profiles
            },
        },
    }


def _delivery_metrics(matrix: dict[str, dict[str, int]]) -> dict[str, object]:
    labels: dict[str, dict[str, float]] = {}
    for label, row in matrix.items():
        predicted = sum(counts[label] for counts in matrix.values())
        labels[label] = {
            "precision": row[label] / predicted if predicted else 0.0,
            "recall": row[label] / sum(row.values()) if sum(row.values()) else 0.0,
        }
    total = sum(sum(row.values()) for row in matrix.values())
    return {
        "confusion_matrix": matrix,
        "per_label": labels,
        "accuracy": sum(matrix[label][label] for label in matrix) / total if total else None,
        "always_queue_accuracy": sum(matrix["queue"].values()) / total if total else None,
    }


def _accuracy(scores: list[RouteScore]) -> dict[str, float]:
    total = len(scores)
    if total == 0:
        raise EvalsError("decision eval datasets are empty")
    intent_hits = sum(1 for row in scores if row.predicted_intent == row.intent)
    target_hits = sum(1 for row in scores if row.predicted_target == row.target)
    return {
        "message.intent": intent_hits / total,
        "message.target_agent": target_hits / total,
    }


def _write_report(body: dict[str, object]) -> Path:
    path = _repo_root() / ".ignorelocal" / "evals" / f"{_report_day()}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _message(case: _Case, now: dt.datetime) -> RoutedMessage:
    return RoutedMessage(
        text=case.text,
        author="user",
        created_at=now,
        source="eval",
        new_agent=False,
        reply_to=None,
        reply_to_agent_id=None,
        agent_id=case.explicit_target,
        bot_id="bot_eval",
    )


def _context(case: _Case, now: dt.datetime) -> RouterContext:
    agents = [
        OpenAgent(id=item.id, title=item.title, summary=item.summary, status=item.status)
        for item in case.open_agents
    ]
    pending: list[PendingQuestion] = []
    if case.pending_agent_id is not None and case.pending_minutes_ago is not None:
        pending.append(
            PendingQuestion(
                agent_id=case.pending_agent_id,
                asked_at=now - dt.timedelta(minutes=case.pending_minutes_ago),
            )
        )
    return RouterContext(
        bot_id="bot_eval",
        open_agents=agents,
        pending_questions=pending,
        recent_user_messages={},
        runtime="pydantic_ai",
    )


def _target(agent_id: str | None) -> str:
    if agent_id is None or agent_id == "":
        return "none"
    return agent_id


def _utcnow() -> dt.datetime:
    """Read the clock through the datetime module so a frozen clock still applies."""
    return dt.datetime.now(dt.UTC)


def _report_day() -> str:
    return _utcnow().date().isoformat()


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "host" / "src" / "sevn" / "config.py").is_file():
            return parent
    raise EvalsError("decision eval datasets are missing")
