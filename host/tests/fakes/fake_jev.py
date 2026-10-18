"""Scripted jev ``system_one`` client for router tests.

``FakeJev(answers)`` records every request and returns the scripted choice,
score, or noul with its confidence. No network.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

type AnswerValue = tuple[str, float] | float
type AnswerMap = Mapping[str, AnswerValue]


class FakeJevRequest:
    """One recorded ``system_one`` call."""

    def __init__(self, state: object, questions: dict[str, object], model: str | None) -> None:
        self.state = state
        self.questions = questions
        self.model = model

    def text(self) -> str:
        """Stable text of the state and questions, for redaction checks."""
        return json.dumps(
            {"model": self.model, "state": self.state, "questions": self.questions},
            default=str,
            ensure_ascii=False,
        )


class _ChoiceAnswer:
    def __init__(self, choice: str, confidence: float) -> None:
        self.choice = choice
        self.confidence = confidence
        self.probabilities = {choice: confidence}


class _NoulAnswer:
    def __init__(self, noul: float) -> None:
        self.noul = noul


class _ScoreAnswer:
    def __init__(self, score: str, confidence: float) -> None:
        self.score = score
        self.confidence = confidence


class FakeJevResponse:
    """Answer bags shaped like the typesafe ``SystemOneResponse``."""

    def __init__(
        self,
        *,
        choices: dict[str, _ChoiceAnswer],
        nouls: dict[str, _NoulAnswer],
        scores: dict[str, _ScoreAnswer],
        model: str | None,
    ) -> None:
        self.choices = choices
        self.nouls = nouls
        self.scores = scores
        self.model = model


class FakeJev:
    """In-memory jev client.

    ``answers`` maps a question name to ``(label, confidence)`` or, for a noul,
    a float in ``[0, 1]``. ``script`` is one map per call; later calls repeat
    the last map. An unscripted question returns confidence ``0.0``.
    """

    def __init__(
        self,
        answers: AnswerMap | None = None,
        *,
        script: Sequence[AnswerMap] | None = None,
    ) -> None:
        self.requests: list[FakeJevRequest] = []
        if script is not None:
            self._script = [dict(item) for item in script]
        elif answers is not None:
            self._script = [dict(answers)]
        else:
            self._script = [{}]
        self._call = 0

    async def __aenter__(self) -> FakeJev:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def system_one(
        self,
        state: object,
        questions: Mapping[str, object],
        *,
        model: str | None = None,
        **_extra: object,
    ) -> FakeJevResponse:
        """Record ``state`` and ``questions``, then return the scripted answers."""
        view = {name: _question_view(question) for name, question in questions.items()}
        self.requests.append(FakeJevRequest(state, view, model))
        chosen = self._script[min(self._call, len(self._script) - 1)]
        self._call += 1
        return _response(questions, chosen, model)


def _response(
    questions: Mapping[str, object],
    answers: AnswerMap,
    model: str | None,
) -> FakeJevResponse:
    choices: dict[str, _ChoiceAnswer] = {}
    nouls: dict[str, _NoulAnswer] = {}
    scores: dict[str, _ScoreAnswer] = {}
    for name, question in questions.items():
        kind = _kind(question)
        raw = answers.get(name)
        if kind == "noul" or isinstance(raw, float):
            nouls[name] = _NoulAnswer(float(raw) if isinstance(raw, int | float) else 0.0)
            continue
        label, confidence = _pair(raw)
        if kind == "score":
            scores[name] = _ScoreAnswer(label, confidence)
        else:
            choices[name] = _ChoiceAnswer(label, confidence)
    return FakeJevResponse(choices=choices, nouls=nouls, scores=scores, model=model)


def _pair(raw: AnswerValue | None) -> tuple[str, float]:
    if isinstance(raw, tuple):
        return str(raw[0]), float(raw[1])
    return "none", 0.0


def _kind(question: object) -> str:
    found = _attr(question, "type")
    if isinstance(found, str) and found != "":
        return found
    return "choice"


def _attr(question: object, name: str) -> object:
    if isinstance(question, dict):
        return question.get(name)
    return getattr(question, name, None)


def _question_view(question: object) -> dict[str, object]:
    if isinstance(question, dict):
        return dict(question)
    view: dict[str, object] = {}
    for name in ("type", "criteria", "instructions", "legend"):
        value = getattr(question, name, None)
        if value is not None:
            view[name] = _plain(value)
    return view


def _plain(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(item) for item in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)


def dump_requests(client: FakeJev) -> str:
    """Serialize recorded requests. Canary checks search this string."""
    return "\n".join(request.text() for request in client.requests)


__all__ = ["FakeJev", "FakeJevRequest", "FakeJevResponse", "dump_requests"]
