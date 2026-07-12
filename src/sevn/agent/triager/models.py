"""Structured triage output and ontology helpers (`specs/10-schema-ontology.md` §2-§3).

Also defines ``COMPLEXITY_TIERS`` plus ``SessionVisibility`` / ``SessionVisibilityLiteral``;
import those from ``sevn.agent.triager`` for the stable public surface (`specs/10-schema-ontology.md` §2.1).

Module: sevn.agent.triager.models
Depends: pydantic

Exports:
    Intent — Triager intent labels (§3.1).
    ComplexityTier — dispatch tier A-D (§3.2).
    MessageKind — transcript / security row kind (§3.4.2).
    SessionVisibility / SessionVisibilityLiteral — session visibility enums (§2.1).
    TelegramFollowupAnchor — Telegram FOLLOWUP anchor payload (§2.2).
    WebUIFollowupAnchor — Web UI FOLLOWUP anchor payload (§2.2).
    TriageResult — Pydantic structured output from the Triager LLM pass (§2.2).

Examples:
    >>> r = TriageResult(
    ...     intent=Intent.NEW_REQUEST,
    ...     complexity=ComplexityTier.B,
    ...     first_message="Working on it.",
    ...     tools=[],
    ...     skills=[],
    ...     mcp_servers_required=[],
    ...     confidence=0.85,
    ...     requires_vision=False,
    ...     requires_document=False,
    ... )
    >>> r.complexity == ComplexityTier.B
    True
    >>> Intent.GREETING == "GREETING"
    True
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Final, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)
from pydantic.functional_validators import ModelWrapValidatorHandler  # noqa: TC002


class Intent(StrEnum):
    """Conversational role for one Triager emission (`specs/10-schema-ontology.md` §3.1)."""

    GREETING = "GREETING"
    FOLLOWUP = "FOLLOWUP"
    NEW_REQUEST = "NEW_REQUEST"
    UNKNOWN = "UNKNOWN"


class ComplexityTier(StrEnum):
    """Executor dispatch tier (`specs/10-schema-ontology.md` §3.2)."""

    A = "A"
    B = "B"
    C = "C"
    D = "D"


COMPLEXITY_TIERS: Final[tuple[ComplexityTier, ...]] = (
    ComplexityTier.A,
    ComplexityTier.B,
    ComplexityTier.C,
    ComplexityTier.D,
)


class MessageKind(StrEnum):
    """Lifecycle label for history / stub rows (`specs/10-schema-ontology.md` §3.4.2)."""

    MESSAGE = "message"
    COMMAND = "command"
    BLOCKED = "blocked"


type SessionVisibilityLiteral = Literal["self", "tree", "all"]
type SessionVisibility = SessionVisibilityLiteral


class TelegramFollowupAnchor(BaseModel):
    """Telegram FOLLOWUP anchor (`specs/10-schema-ontology.md` §2.2; `specs/18-channel-telegram.md`).

    Attributes:
        channel (Literal["telegram"]): Discriminator literal for the union.
        chat_id (int): Telegram chat id the followup attaches to.
        topic_id (int | None): Forum topic id, ``None`` for chat-level threads.
        message_id (int | None): Anchor message id (current user message).
        reply_to_message_id (int | None): ``reply_to_message.message_id`` when set.
    """

    model_config = ConfigDict(extra="forbid")

    channel: Literal["telegram"] = "telegram"
    chat_id: int
    topic_id: int | None = None
    message_id: int | None = None
    reply_to_message_id: int | None = None


class WebUIFollowupAnchor(BaseModel):
    """Web UI / WebChat FOLLOWUP anchor (`specs/10-schema-ontology.md` §2.2; `specs/19-channel-webui.md`).

    Attributes:
        channel (Literal["webui"]): Discriminator literal for the union.
        session_id (str): Gateway session id the followup attaches to.
        message_id (str | None): Anchor message id within the SPA transcript.
    """

    model_config = ConfigDict(extra="forbid")

    channel: Literal["webui"] = "webui"
    session_id: str
    message_id: str | None = None


FollowupAnchor = Annotated[
    TelegramFollowupAnchor | WebUIFollowupAnchor,
    Field(discriminator="channel"),
]


class TriageResult(BaseModel):
    """Validated structured output from the Triager LLM call (`specs/10-schema-ontology.md` §2.2)."""

    model_config = ConfigDict(extra="forbid")

    intent: Intent
    followup_anchor: FollowupAnchor | None = None
    complexity: ComplexityTier
    first_message: str
    tools: list[str]
    skills: list[str]
    mcp_servers_required: list[str]
    permission_scope_narrowing: str | None = None
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    requires_vision: bool
    requires_document: bool
    disregard: bool = False
    replay_provider_history: bool = False

    @field_validator("first_message")
    @classmethod
    def _strip_first_message(cls, value: str) -> str:
        """Strip whitespace (`specs/10-schema-ontology.md` §2.2).

        Args:
            cls (type): Model class.
            value (str): Raw ``first_message``.

        Returns:
            str: Stripped text (may be empty when ``disregard`` is true; enforced in a model validator).

        Examples:
            >>> TriageResult(
            ...     intent=Intent.NEW_REQUEST,
            ...     complexity=ComplexityTier.A,
            ...     first_message="  hi  ",
            ...     tools=[],
            ...     skills=[],
            ...     mcp_servers_required=[],
            ...     confidence=0.5,
            ...     requires_vision=False,
            ...     requires_document=False,
            ... ).first_message
            'hi'
        """
        return value.strip()

    @model_validator(mode="after")
    def _first_message_nonempty_unless_disregard(self) -> Self:
        """Require non-empty reply text except for group short-circuit (`specs/13-rlm-triager.md` §2.2).

        Args:
            self (TriageResult): Validated instance.

        Returns:
            TriageResult: Unchanged ``self``.

        Raises:
            ValueError: When ``first_message`` is empty and ``disregard`` is false.

        Examples:
            >>> r = TriageResult(
            ...     intent=Intent.NEW_REQUEST,
            ...     complexity=ComplexityTier.A,
            ...     first_message="ok",
            ...     tools=[],
            ...     skills=[],
            ...     mcp_servers_required=[],
            ...     confidence=0.5,
            ...     requires_vision=False,
            ...     requires_document=False,
            ... )
            >>> r.first_message
            'ok'
        """
        if not self.disregard and not self.first_message:
            msg = "first_message must be non-empty after strip unless disregard is true"
            raise ValueError(msg)
        return self

    @model_validator(mode="wrap")
    @classmethod
    def _greeting_tool_skill_policy(
        cls,
        value: Any,
        handler: ModelWrapValidatorHandler[TriageResult],
        info: ValidationInfo,
    ) -> TriageResult:
        """Enforce GREETING list policy; allow waiver via validation context (`specs/13-rlm-triager.md` §2.2).

        Args:
            cls (type): Model class.
            value (Any): Raw input to the inner validator.
            handler (ModelWrapValidatorHandler["TriageResult"]): Inner model pipeline.
            info (ValidationInfo): Validation context carrying ``relax_greeting_lists``.

        Returns:
            TriageResult: Validated instance.

        Raises:
            ValueError: When GREETING lists are non-empty without ``relax_greeting_lists`` in context.

        Examples:
            >>> TriageResult.model_validate(
            ...     {
            ...         "intent": "GREETING",
            ...         "complexity": "A",
            ...         "first_message": "Hi",
            ...         "tools": ["t"],
            ...         "skills": [],
            ...         "mcp_servers_required": [],
            ...         "confidence": 1.0,
            ...         "requires_vision": False,
            ...         "requires_document": False,
            ...     },
            ...     context={"relax_greeting_lists": True},
            ... ).tools
            ['t']
        """
        result = handler(value)
        ctx = info.context or {}
        relax = bool(ctx.get("relax_greeting_lists"))
        if result.intent == Intent.GREETING and (result.tools or result.skills) and not relax:
            msg = "GREETING requires empty tools and skills lists"
            raise ValueError(msg)
        return result
