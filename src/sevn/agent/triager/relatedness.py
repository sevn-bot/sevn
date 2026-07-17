"""Bounded relatedness classification for ``multi`` queue mode (D6, `specs/36-sub-agents.md`).

Module: sevn.agent.triager.relatedness
Depends: asyncio, os, pydantic, sevn.agent.triager.run, sevn.config.workspace_config

Exports:
    RelatednessInput — classifier inputs (in-flight summary, queued summaries, new message).
    RelatednessResult — label plus whether a timeout/failure fallback was used.
    RelatednessDecision — pydantic structured-output row for the triager transport.
    classify_relatedness — async classifier with strict timeout and ``new_task`` fallback.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

from sevn.config.workspace_config import WorkspaceConfig

if TYPE_CHECKING:
    from sevn.agent.tracing.sink import TraceSink

RelatednessLabel = Literal["related_steer", "supersede_cancel", "new_task"]


@dataclass(frozen=True, slots=True)
class RelatednessResult:
    """Classifier output plus whether a timeout/failure fallback was used (D6)."""

    label: RelatednessLabel
    fallback: bool = False


_RELATEDNESS_LABELS: Final[frozenset[str]] = frozenset(
    {"related_steer", "supersede_cancel", "new_task"},
)

_DEFAULT_TIMEOUT_S: Final[float] = 5.0

_STUB_ENV_KEY: Final[str] = "SEVN_RELATEDNESS_STUB"
_STUB_LABEL_ENV_KEY: Final[str] = "SEVN_RELATEDNESS_STUB_LABEL"


class RelatednessDecision(BaseModel):
    """Structured classifier output — exactly one routing label (D6)."""

    model_config = ConfigDict(extra="forbid")

    label: RelatednessLabel = Field(
        description=(
            "related_steer when the new message continues the in-flight task; "
            "supersede_cancel when it replaces/cancels it; "
            "new_task when it is an unrelated parallel ask."
        ),
    )


@dataclass(frozen=True, slots=True)
class RelatednessInput:
    """Inputs for one ``multi``-mode busy-session classification pass."""

    in_flight_task_summary: str
    queued_task_summaries: tuple[str, ...]
    new_message: str


def _normalize_label(raw: object) -> RelatednessLabel:
    """Coerce a raw label string to a known ``RelatednessLabel`` or steer-fallback.

    Args:
        raw (object): Parsed label value.

    Returns:
        RelatednessLabel: Normalized label; unknown values become ``related_steer``.

    Examples:
        >>> _normalize_label("new_task")
        'new_task'
        >>> _normalize_label("bogus")
        'related_steer'
    """
    if isinstance(raw, str):
        normalized = raw.strip().lower()
        if normalized in _RELATEDNESS_LABELS:
            return normalized  # type: ignore[return-value]
    return "related_steer"


def _build_relatedness_prompt(inp: RelatednessInput) -> str:
    """Build the bounded classifier user prompt.

    Args:
        inp (RelatednessInput): In-flight, queued, and new-message context.

    Returns:
        str: Single user blob for the triager transport.

    Examples:
        >>> "in-flight task" in _build_relatedness_prompt(
        ...     RelatednessInput("summarize logs", (), "also check disk")
        ... )
        True
    """
    queued = (
        "\n".join(f"- {line}" for line in inp.queued_task_summaries if line.strip()) or "(none)"
    )
    schema = json.dumps(RelatednessDecision.model_json_schema(), sort_keys=True)
    return (
        "Classify how a new user message relates to work already in progress.\n\n"
        f"In-flight task summary:\n{inp.in_flight_task_summary.strip() or '(unknown)'}\n\n"
        f"Queued task summaries:\n{queued}\n\n"
        f"New user message:\n{inp.new_message.strip()}\n\n"
        "Return JSON matching this schema with exactly one label:\n"
        f"{schema}\n"
    )


async def _classify_via_triager_transport(
    *,
    workspace: WorkspaceConfig,
    inp: RelatednessInput,
    content_root: Path | None,
    trace: TraceSink | None,
    session_id: str,
    turn_id: str,
) -> RelatednessLabel:
    """Run the live triager-model structured call for one relatedness decision.

    Args:
        workspace (WorkspaceConfig): Parsed workspace configuration.
        inp (RelatednessInput): Classification inputs.
        content_root (Path | None): Workspace content root for persona/params lookup.
        trace (TraceSink | None): Optional trace sink.
        session_id (str): Owning gateway session id.
        turn_id (str): Turn correlation id for trace linkage.

    Returns:
        RelatednessLabel: Model-selected label (invalid JSON → ``related_steer``).

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_classify_via_triager_transport)
        True
    """
    from sevn.agent.triager.run import (
        resolve_triager_model_id,
        resolve_triager_transport_name,
        structured_output_call,
    )
    from sevn.config.sections.providers import providers_section_dict

    model_id = resolve_triager_model_id(workspace)
    transport_name = resolve_triager_transport_name(
        providers_section_dict(getattr(workspace, "providers", None)),
        model_id,
    )
    prompt = _build_relatedness_prompt(inp)
    result = await structured_output_call(
        workspace=workspace,
        model_id=model_id,
        transport_name=transport_name,
        user_prompt=prompt,
        seed=None,
        content_root=content_root,
        turn_span_id=None,
        trace=trace,
        session_id=session_id,
        turn_id=turn_id,
    )
    try:
        decision = RelatednessDecision.model_validate_json(result.json)
    except Exception:
        logger.warning(
            "relatedness_classifier_invalid_json session_id={} turn_id={}",
            session_id,
            turn_id,
        )
        return "related_steer"
    return _normalize_label(decision.label)


async def classify_relatedness(
    *,
    workspace: WorkspaceConfig,
    inp: RelatednessInput,
    session_id: str,
    turn_id: str,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
    content_root: Path | None = None,
    trace: TraceSink | None = None,
    classifier: Callable[[RelatednessInput], Awaitable[object]] | None = None,
) -> RelatednessResult:
    """Classify a busy-session message; timeout/failure → ``new_task`` (D15).

    On timeout or transport failure the message is treated as its own turn
    (``new_task``) rather than silently merged into an unrelated in-flight
    task via ``related_steer``.

    Args:
        workspace (WorkspaceConfig): Parsed workspace configuration.
        inp (RelatednessInput): In-flight, queued, and new-message context.
        session_id (str): Owning gateway session id.
        turn_id (str): Turn correlation id (for tracing / stub routing).
        timeout_s (float): Hard wall-clock cap in seconds (default 5s).
        content_root (Path | None): Workspace content root for triager transport.
        trace (TraceSink | None): Optional trace sink.
        classifier (object | None): Test override — async callable
            ``(inp: RelatednessInput) -> RelatednessLabel | RelatednessResult``.

    Returns:
        RelatednessResult: Label plus ``fallback=True`` when ``new_task`` was
        chosen because the classifier timed out or failed.

    Examples:
        >>> import asyncio
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> async def _stub(_inp: RelatednessInput) -> str:
        ...     return "new_task"
        >>> inp = RelatednessInput("a", (), "b")
        >>> asyncio.run(classify_relatedness(
        ...     workspace=WorkspaceConfig.minimal(),
        ...     inp=inp,
        ...     session_id="s",
        ...     turn_id="t",
        ...     classifier=_stub,
        ... )).label
        'new_task'
    """
    if classifier is not None:
        raw: object = await classifier(inp)
        if isinstance(raw, RelatednessResult):
            return raw
        return RelatednessResult(label=_normalize_label(raw), fallback=False)

    if os.environ.get(_STUB_ENV_KEY, "").strip().lower() in ("1", "true", "yes"):
        stub_label = os.environ.get(_STUB_LABEL_ENV_KEY, "related_steer")
        return RelatednessResult(label=_normalize_label(stub_label), fallback=False)

    try:
        label = await asyncio.wait_for(
            _classify_via_triager_transport(
                workspace=workspace,
                inp=inp,
                content_root=content_root,
                trace=trace,
                session_id=session_id,
                turn_id=turn_id,
            ),
            timeout=timeout_s,
        )
        return RelatednessResult(label=label, fallback=False)
    except TimeoutError:
        logger.info(
            "relatedness_classifier_timeout session_id={} turn_id={} timeout_s={}",
            session_id,
            turn_id,
            timeout_s,
        )
        return RelatednessResult(label="new_task", fallback=True)
    except Exception:
        logger.exception(
            "relatedness_classifier_failed session_id={} turn_id={}",
            session_id,
            turn_id,
        )
        return RelatednessResult(label="new_task", fallback=True)


__all__ = [
    "RelatednessDecision",
    "RelatednessInput",
    "RelatednessResult",
    "classify_relatedness",
]
