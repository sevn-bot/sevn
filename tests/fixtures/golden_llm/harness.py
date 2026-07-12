"""Golden LLM case loader, workspace prep, record/replay runner (W11).

Module: tests.fixtures.golden_llm.harness
Depends: pydantic, pydantic_evals, sevn.agent.executors.b_harness, sevn.tools.registry

Exports:
    GoldenCase — validated case file schema.
    GoldenRecording — recorded provider trace + transport script.
    discover_cases — load JSON cases from ``cases/`` subdirs.
    prepare_workspace — copy template or inline files into ``tmp_path``.
    tool_names_from_provider_messages — extract tool_use names from provider rows.
    authoritative_tool_names_for_outcome — merge provider rows with successful_tools_called.
    run_golden_case_replay — tokenless tier-B run from a recording.
    save_recording — persist live run artefacts to ``recordings/``.
    cases_to_dataset — bridge cases into ``pydantic_evals.Dataset`` (W12 prep).
"""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field
from pydantic_evals import Case, Dataset

from sevn.agent.executors.b_harness import run_b_turn
from sevn.agent.executors.b_types import ResolvedTierBModel, SessionHandle
from sevn.agent.providers.budget import BudgetRegime, ModelBudget
from sevn.agent.providers.transport import ChatCompletionsTransport
from sevn.agent.triager.models import TriageResult
from sevn.config.workspace_config import WorkspaceConfig, parse_workspace_config
from sevn.tools.cache import LoadedBodyCache
from sevn.tools.context import ToolContext
from sevn.tools.permissions import AllowAllPermissionPolicy
from sevn.tools.registry import build_session_registry
from tests.fixtures.golden_llm import GOLDEN_LLM_ROOT

CASES_ROOT = GOLDEN_LLM_ROOT / "cases"
RECORDINGS_ROOT = GOLDEN_LLM_ROOT / "recordings"
WORKSPACE_TEMPLATE = GOLDEN_LLM_ROOT / "workspace_template"


class GoldenWorkspaceSpec(BaseModel):
    """Hermetic workspace payload for one golden case."""

    inline_files: dict[str, str] = Field(default_factory=dict)
    workspace_fixture: str | None = None


class GoldenAssertions(BaseModel):
    """Post-run checks against provider trace and assistant text."""

    tools_called: list[str] = Field(default_factory=list)
    tool_success: bool = True
    response_contains: list[str] = Field(default_factory=list)


class GoldenRequires(BaseModel):
    """Triager-listed tools/skills the case exercises."""

    tools: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)


class GoldenCase(BaseModel):
    """On-disk golden case schema (``cases/*/*.json``)."""

    id: str
    tier: Literal["B"] = "B"
    requires: GoldenRequires = Field(default_factory=GoldenRequires)
    user_messages: list[str]
    triage_stub: dict[str, Any]
    workspace: GoldenWorkspaceSpec = Field(default_factory=GoldenWorkspaceSpec)
    assertions: GoldenAssertions = Field(default_factory=GoldenAssertions)
    category: str = ""
    recording_id: str | None = None

    @property
    def recording_key(self) -> str:
        """Filename stem under ``recordings/``."""
        return self.recording_id or self.id


class GoldenRecording(BaseModel):
    """Recorded live or synthetic run for tokenless replay."""

    case_id: str
    version: int = 1
    transport_responses: list[dict[str, Any]]
    provider_turn_messages: list[dict[str, Any]] = Field(default_factory=list)
    final_text: str = ""


def golden_llm_live_enabled() -> bool:
    """Return whether live golden LLM runs are allowed."""
    return os.environ.get("SEVN_GOLDEN_LLM") == "1"


def discover_cases(*, category: str | None = None) -> list[GoldenCase]:
    """Load and validate all golden case JSON files.

    Args:
        category (str | None): When set, only ``cases/<category>/`` is scanned.

    Returns:
        list[GoldenCase]: Sorted by case id.

    Examples:
        >>> cases = discover_cases(category="tools")
        >>> all(c.category == "tools" for c in cases)
        True
    """
    roots: list[Path]
    if category:
        roots = [CASES_ROOT / category]
    else:
        roots = sorted(p for p in CASES_ROOT.iterdir() if p.is_dir())
    cases: list[GoldenCase] = []
    for root in roots:
        if not root.is_dir():
            continue
        cat = root.name
        for path in sorted(root.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            cases.append(GoldenCase.model_validate({**payload, "category": cat}))
    return sorted(cases, key=lambda c: c.id)


def load_recording(case: GoldenCase) -> GoldenRecording | None:
    """Load a recording for ``case`` when present."""
    path = RECORDINGS_ROOT / f"{case.recording_key}.json"
    if not path.is_file():
        return None
    return GoldenRecording.model_validate(json.loads(path.read_text(encoding="utf-8")))


def save_recording(recording: GoldenRecording) -> Path:
    """Write a recording JSON file under ``recordings/``."""
    RECORDINGS_ROOT.mkdir(parents=True, exist_ok=True)
    path = RECORDINGS_ROOT / f"{recording.case_id}.json"
    path.write_text(recording.model_dump_json(indent=2), encoding="utf-8")
    return path


def prepare_workspace(tmp_path: Path, case: GoldenCase) -> Path:
    """Materialize a hermetic workspace for one case.

    Args:
        tmp_path (Path): pytest ``tmp_path`` (parent for the workspace root).
        case (GoldenCase): Case carrying inline files or fixture name.

    Returns:
        Path: Workspace content root (contains ``sevn.json``).

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> case = GoldenCase(
        ...     id="x",
        ...     user_messages=["hi"],
        ...     triage_stub={"intent": "NEW_REQUEST", "complexity": "B", "first_message": "ok",
        ...                  "tools": [], "skills": [], "mcp_servers_required": [],
        ...                  "confidence": 0.9, "requires_vision": False},
        ...     workspace=GoldenWorkspaceSpec(inline_files={"a.txt": "A"}),
        ... )
        >>> root = prepare_workspace(Path(tempfile.mkdtemp()), case)
        >>> (root / "a.txt").read_text()
        'A'
    """
    root = tmp_path / "workspace"
    if case.workspace.workspace_fixture:
        fixture = GOLDEN_LLM_ROOT / case.workspace.workspace_fixture
        shutil.copytree(fixture, root)
    else:
        shutil.copytree(WORKSPACE_TEMPLATE, root)
    for rel_path, content in case.workspace.inline_files.items():
        dest = root / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
    return root


def tool_names_from_provider_messages(messages: list[dict[str, Any]]) -> list[str]:
    """Extract tool names from serialized ``provider_turn_messages``."""
    names: list[str] = []
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "tool_use":
                    name = part.get("name")
                    if isinstance(name, str):
                        names.append(name)
    return names


def authoritative_tool_names_for_outcome(
    provider_messages: list[dict[str, Any]],
    *,
    successful_tools_called: frozenset[str] | set[str] | None = None,
) -> list[str]:
    """Merge persisted provider tool_use names with executed tool ids.

    ``sanitize_provider_turn_messages_for_storage`` strips orphan assistant
    ``tool_use`` blocks, so replay assertions must also consult
    ``BTurnOutcome.successful_tools_called``.
    """
    names = tool_names_from_provider_messages(provider_messages)
    if successful_tools_called:
        seen = set(names)
        for tool in sorted(successful_tools_called):
            if tool not in seen:
                names.append(tool)
                seen.add(tool)
    return names


def tool_names_from_transport_responses(responses: list[dict[str, Any]]) -> list[str]:
    """Extract tool names from recorded OpenAI chat completion transport scripts."""
    names: list[str] = []
    for response in responses:
        choices = response.get("choices")
        if not isinstance(choices, list):
            continue
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            message = choice.get("message")
            if not isinstance(message, dict):
                continue
            tool_calls = message.get("tool_calls")
            if not isinstance(tool_calls, list):
                continue
            for call in tool_calls:
                if not isinstance(call, dict):
                    continue
                function = call.get("function")
                if isinstance(function, dict):
                    name = function.get("name")
                    if isinstance(name, str):
                        names.append(name)
    return names


def _tool_errors_from_provider_messages(messages: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    last_name = "?"
    for msg in messages:
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "tool_use":
                last_name = str(part.get("name", "?"))
            elif part.get("type") == "tool_result":
                body = part.get("content")
                if isinstance(body, str) and '"ok":false' in body.replace(" ", ""):
                    errors.append(last_name)
    return errors


class _ScriptedChatTransport(ChatCompletionsTransport):
    def __init__(self, fn: Callable[[dict[str, Any]], Any]) -> None:
        super().__init__(proxy_base_url="http://golden-llm.test.invalid")
        self._fn = fn

    async def complete(self, request: dict[str, object]) -> dict[str, object]:
        result = self._fn(dict(request))
        if hasattr(result, "__await__"):
            return await result  # type: ignore[misc]
        return result


def _triage_from_case(case: GoldenCase) -> TriageResult:
    stub = dict(case.triage_stub)
    stub.setdefault("tools", case.requires.tools)
    stub.setdefault("skills", case.requires.skills)
    return TriageResult.model_validate(stub, context={"relax_greeting_lists": False})


def _workspace_config(root: Path) -> WorkspaceConfig:
    raw = json.loads((root / "sevn.json").read_text(encoding="utf-8"))
    ws = parse_workspace_config(raw)
    return ws.model_copy(update={"workspace_root": str(root)})


class _GoldenStubChannelRouter:
    """Minimal router so ``send_file`` / ``message`` tools succeed in replay."""

    async def route_outgoing(self, _message: object) -> None:
        return None


def _golden_tool_context(
    *,
    session_id: str,
    workspace_root: Path,
    registry_version: int,
    turn_id: str,
) -> ToolContext:
    return ToolContext(
        session_id=session_id,
        workspace_path=workspace_root,
        workspace_id="golden-ws",
        registry_version=registry_version,
        trace=None,
        permissions=AllowAllPermissionPolicy(),
        turn_id=turn_id,
        channel_router=_GoldenStubChannelRouter(),
        delivery_channel="golden",
        outbound_user_id="golden-user",
    )


async def run_golden_case_replay(
    case: GoldenCase,
    workspace_root: Path,
    recording: GoldenRecording,
    *,
    session_id: str = "golden-sess",
    turn_id: str = "golden-turn",
) -> Any:
    """Run tier B tokenlessly using a pre-recorded transport script."""
    triage = _triage_from_case(case)
    ws = _workspace_config(workspace_root)
    exe, tool_set = build_session_registry(
        registry_version=1,
        workspace_config=ws,
        workspace_root=workspace_root,
    )
    plan: Iterator[dict[str, Any]] = iter(recording.transport_responses)

    async def _next(_req: dict[str, Any]) -> dict[str, Any]:
        try:
            return next(plan)
        except StopIteration as exc:
            msg = f"transport script exhausted for case {case.id}"
            raise AssertionError(msg) from exc

    transport = _ScriptedChatTransport(_next)
    bundle = ResolvedTierBModel(
        model_id="openai/gpt-golden",
        transport=transport,
        budget=ModelBudget(model_id="openai/gpt-golden", regime=BudgetRegime.FREE_LOCAL),
    )
    incoming = case.user_messages[-1]
    return await run_b_turn(
        workspace=ws,
        session=SessionHandle(session_id=session_id),
        turn_id=turn_id,
        triage=triage,
        incoming_text=incoming,
        tool_set=tool_set,
        body_cache=LoadedBodyCache(capacity=16),
        tool_executor=exe,
        transport_bundle=bundle,
        trace=None,
        steer_buffer=None,
        tool_context=_golden_tool_context(
            session_id=session_id,
            workspace_root=workspace_root,
            registry_version=tool_set.registry_version,
            turn_id=turn_id,
        ),
    )


def assert_golden_outcome(
    case: GoldenCase,
    outcome: Any,
    *,
    recording: GoldenRecording | None = None,
) -> None:
    """Apply case assertions to a tier-B outcome."""
    provider_msgs = [dict(m) for m in outcome.provider_turn_messages]
    if not provider_msgs and recording is not None:
        provider_msgs = list(recording.provider_turn_messages)
    tool_names = authoritative_tool_names_for_outcome(
        provider_msgs,
        successful_tools_called=getattr(outcome, "successful_tools_called", None),
    )
    attempted = getattr(outcome, "tools_attempted", None)
    if attempted:
        seen = set(tool_names)
        for tool in sorted(attempted):
            if tool not in seen:
                tool_names.append(tool)
                seen.add(tool)
    for expected in case.assertions.tools_called:
        assert expected in tool_names, f"case {case.id}: expected tool {expected!r} in {tool_names}"
    if case.assertions.tool_success:
        errors = _tool_errors_from_provider_messages(provider_msgs)
        assert not errors, f"case {case.id}: tool errors {errors}"
    if getattr(outcome, "status", None) == "failed" and not case.assertions.tool_success:
        return
    joined = " ".join(m.text for m in outcome.final_messages)
    for fragment in case.assertions.response_contains:
        assert fragment.lower() in joined.lower(), (
            f"case {case.id}: expected {fragment!r} in assistant text {joined!r}"
        )


@dataclass(frozen=True)
class RecordingCapture:
    """Mutable collector wired into a live-record transport."""

    responses: list[dict[str, Any]]


class _RecordingChatTransport(ChatCompletionsTransport):
    def __init__(
        self,
        *,
        proxy_base_url: str,
        inner: ChatCompletionsTransport,
        capture: RecordingCapture,
    ) -> None:
        super().__init__(proxy_base_url=proxy_base_url)
        self._inner = inner
        self._capture = capture

    async def complete(self, request: dict[str, object]) -> dict[str, object]:
        result = await self._inner.complete(request)
        self._capture.responses.append(dict(result))
        return result


async def run_golden_case_live(
    case: GoldenCase,
    workspace_root: Path,
    transport: ChatCompletionsTransport,
    *,
    session_id: str = "golden-live",
    turn_id: str = "golden-live-turn",
) -> tuple[Any, GoldenRecording]:
    """Run tier B against a live transport and build a recording payload."""
    capture = RecordingCapture(responses=[])
    wrapped = _RecordingChatTransport(
        proxy_base_url="http://golden-llm-live.test.invalid",
        inner=transport,
        capture=capture,
    )
    triage = _triage_from_case(case)
    ws = _workspace_config(workspace_root)
    exe, tool_set = build_session_registry(
        registry_version=1,
        workspace_config=ws,
        workspace_root=workspace_root,
    )
    bundle = ResolvedTierBModel(
        model_id="openai/gpt-golden-live",
        transport=wrapped,
        budget=ModelBudget(model_id="openai/gpt-golden-live", regime=BudgetRegime.FREE_LOCAL),
    )
    outcome = await run_b_turn(
        workspace=ws,
        session=SessionHandle(session_id=session_id),
        turn_id=turn_id,
        triage=triage,
        incoming_text=case.user_messages[-1],
        tool_set=tool_set,
        body_cache=LoadedBodyCache(capacity=16),
        tool_executor=exe,
        transport_bundle=bundle,
        trace=None,
        steer_buffer=None,
        tool_context=_golden_tool_context(
            session_id=session_id,
            workspace_root=workspace_root,
            registry_version=tool_set.registry_version,
            turn_id=turn_id,
        ),
    )
    final_text = " ".join(m.text for m in outcome.final_messages)
    recording = GoldenRecording(
        case_id=case.id,
        transport_responses=capture.responses,
        provider_turn_messages=[dict(m) for m in outcome.provider_turn_messages],
        final_text=final_text,
    )
    return outcome, recording


def cases_to_dataset(cases: list[GoldenCase]) -> Dataset[str, str, dict[str, Any]]:
    """Bridge golden cases into a ``pydantic_evals.Dataset`` (W12 prep).

    Args:
        cases (list[GoldenCase]): Loaded case files.

    Returns:
        Dataset: Inputs are the last user message; metadata holds the full case dict.
    """
    rows: list[Case[str, str, dict[str, Any]]] = []
    for case in cases:
        rows.append(
            Case(
                name=case.id,
                inputs=case.user_messages[-1],
                metadata={"case": case.model_dump(), "category": case.category},
            ),
        )
    return Dataset(name="golden_llm", cases=rows)


def openai_tool_response(name: str, arguments: str, *, call_id: str) -> dict[str, Any]:
    """Build one OpenAI chat completion with a single tool call."""
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {"name": name, "arguments": arguments},
                        },
                    ],
                },
            },
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }


def openai_text_response(text: str) -> dict[str, Any]:
    """Build one OpenAI chat completion with assistant text."""
    return {
        "choices": [{"message": {"role": "assistant", "content": text}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }


def build_recording_from_script(
    case_id: str,
    script: list[dict[str, Any]],
    *,
    final_text: str = "",
) -> GoldenRecording:
    """Synthesize a recording from a transport script (seed / stub helper)."""
    return GoldenRecording(
        case_id=case_id,
        transport_responses=script,
        provider_turn_messages=[],
        final_text=final_text,
    )


__all__ = [
    "GoldenAssertions",
    "GoldenCase",
    "GoldenRecording",
    "GoldenRequires",
    "GoldenWorkspaceSpec",
    "RecordingCapture",
    "assert_golden_outcome",
    "authoritative_tool_names_for_outcome",
    "build_recording_from_script",
    "cases_to_dataset",
    "discover_cases",
    "golden_llm_live_enabled",
    "load_recording",
    "openai_text_response",
    "openai_tool_response",
    "prepare_workspace",
    "run_golden_case_live",
    "run_golden_case_replay",
    "save_recording",
    "tool_names_from_provider_messages",
    "tool_names_from_transport_responses",
]
