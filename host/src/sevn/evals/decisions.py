"""Replay synthetic routing cases through the decider chain (D17)."""

from __future__ import annotations

import asyncio
import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from sevn.config import Settings
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
    scores, judge = asyncio.run(_evaluate(cases))
    path = _write_report(_accuracy(scores), judge)
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


async def _evaluate(cases: list[_Case]) -> tuple[list[RouteScore], dict[str, str]]:
    scores = await _replay(cases)
    return scores, await score_routes(scores)


async def _replay(cases: list[_Case]) -> list[RouteScore]:
    scores: list[RouteScore] = []
    for case in cases:
        now = _utcnow()
        decision = await decide(_message(case, now), _context(case, now), record=False)
        scores.append(
            RouteScore(
                text=case.text,
                intent=case.intent,
                predicted_intent=decision.intent,
                target=case.target,
                predicted_target=_target(decision.target_agent_id),
            )
        )
    return scores


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


def _write_report(accuracy: dict[str, float], judge: dict[str, str]) -> Path:
    path = _repo_root() / ".ignorelocal" / "evals" / f"{_report_day()}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    body: dict[str, object] = {"accuracy": accuracy, "judge": judge}
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
        agent_id=None,
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
