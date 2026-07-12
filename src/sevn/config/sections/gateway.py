"""Gateway, harness, replay, and dispatcher_state subtree models for ``sevn.json``.

Module: sevn.config.sections.gateway
Depends: pydantic, sevn.config.defaults

Exports:
    GatewayFirstSessionIntroConfig — ``gateway.first_session_intro`` BOOTSTRAP intro.
    GatewaySessionMirrorConfig — ``gateway.session_mirror`` JSONL mirror toggle.
    DispatcherStateWorkspaceConfig — ``dispatcher_state.ttl_seconds`` per-kind overrides.
    GatewayRestartConfig — ``gateway.restart`` (`specs/16-harness-discipline.md` §4.2).
    ReplayWorkspaceConfig — ``replay.max_per_day`` (same §5).
    HarnessSnapshotSubConfig — ``harness.snapshot.triager_tier_a`` (§5).
    HarnessWorkspaceConfig — ``harness`` subtree.
    GatewaySteerConfig — ``gateway.steer`` shape.
    GatewayBudgetConfig — ``gateway.budget`` per-turn tier-B caps (`specs/14-executor-tier-b.md` §5).
    GatewayOutputConfig — ``gateway.output`` (PRD `PROBLEMS.md` Priority 2 / Step 5a).
    GatewayConfig — ``gateway`` block subset.
"""

from __future__ import annotations

from typing import Literal, Self, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from sevn.config.defaults import (
    DEFAULT_CASCADE_BUDGET_S,
    DEFAULT_DISPATCHER_STATE_TTL_SECONDS,
    DEFAULT_GATEWAY_AUTO_RESUME_B,
    DEFAULT_HARNESS_SNAPSHOT_TRIAGER_TIER_A,
    DEFAULT_REPLAY_MAX_PER_DAY,
    DEFAULT_TIER_B_EXECUTOR_TIMEOUT_S,
    DEFAULT_TIER_CD_EXECUTOR_TIMEOUT_S,
    DREAMING_MAX_OUTPUT_TOKENS,
    FIRST_SESSION_INTRO_MAX_OUTPUT_TOKENS,
    GUARD_MAX_OUTPUT_TOKENS,
    LCM_MAX_OUTPUT_TOKENS,
    TIER_B_ANSWER_MODE_DEFAULT,
    TIER_B_COUNT_PLANNING,
    TIER_B_MAX_OUTPUT_TOKENS,
    TIER_B_MAX_ROUNDS,
    TIER_B_MAX_ROUNDS_EXPANDED,
    TIER_CD_MAX_OUTPUT_TOKENS,
    TRIAGER_MAX_OUTPUT_TOKENS,
    USER_MODEL_MAX_OUTPUT_TOKENS,
)


class GatewayFirstSessionIntroConfig(BaseModel):
    """``gateway.first_session_intro`` — BOOTSTRAP conversation on first scope message."""

    model_config = ConfigDict(extra="allow")

    enabled: bool = True
    max_questions: int = Field(default=6, ge=0, le=10)
    skip_quick_action: bool = True
    max_output_tokens: int = Field(
        default=FIRST_SESSION_INTRO_MAX_OUTPUT_TOKENS,
        ge=1,
        description=(
            "Provider max_tokens cap for the first-session tier-B intro turn only "
            "(default 4096; clamped to gateway.budget.tier_b_max_output_tokens)."
        ),
    )


class GatewaySessionMirrorConfig(BaseModel):
    """``gateway.session_mirror`` — append-only JSONL under workspace/sessions/."""

    model_config = ConfigDict(extra="allow")

    enabled: bool = True
    retention_days: int | None = Field(default=None, ge=1)


class DispatcherStateWorkspaceConfig(BaseModel):
    """``dispatcher_state`` subtree — per-kind row TTL overrides (`specs/17-gateway.md`)."""

    model_config = ConfigDict(extra="allow")

    ttl_seconds: dict[str, int] = Field(
        default_factory=lambda: dict(DEFAULT_DISPATCHER_STATE_TTL_SECONDS)
    )

    @field_validator("ttl_seconds", mode="before")
    @classmethod
    def _merge_dispatcher_state_ttl_defaults(cls, v: object) -> dict[str, int]:
        """Merge operator overrides onto shipped per-kind defaults.
        Args:
            cls (type): Model class.
            v (object): Raw JSON fragment.
        Returns:
            dict[str, int]: Full per-kind TTL map.
        Examples:
            >>> DispatcherStateWorkspaceConfig._merge_dispatcher_state_ttl_defaults(
            ...     {"plan_approval": 120},
            ... )["plan_approval"]
            120
        """
        merged = dict(DEFAULT_DISPATCHER_STATE_TTL_SECONDS)
        if v is None:
            return merged
        if not isinstance(v, dict):
            msg = f"invalid dispatcher_state.ttl_seconds type: {type(v).__name__}"
            raise ValueError(msg)
        for key, raw in v.items():
            if key not in merged:
                msg = f"unknown dispatcher_state.ttl_seconds kind: {key!r}"
                raise ValueError(msg)
            merged[key] = int(raw)
        return merged


class GatewayRestartConfig(BaseModel):
    """``gateway.restart`` — tier-B auto-resume (`specs/16-harness-discipline.md` §4.2)."""

    model_config = ConfigDict(extra="allow")

    auto_resume_b: bool = Field(default=DEFAULT_GATEWAY_AUTO_RESUME_B)


class ReplayWorkspaceConfig(BaseModel):
    """``replay`` — turn replay caps (`specs/16-harness-discipline.md` §5)."""

    model_config = ConfigDict(extra="allow")

    max_per_day: int = Field(default=DEFAULT_REPLAY_MAX_PER_DAY, ge=1)


class HarnessSnapshotSubConfig(BaseModel):
    """``harness.snapshot`` (`specs/16-harness-discipline.md` §5)."""

    model_config = ConfigDict(extra="allow")

    triager_tier_a: bool = Field(default=DEFAULT_HARNESS_SNAPSHOT_TRIAGER_TIER_A)


class HarnessWorkspaceConfig(BaseModel):
    """``harness`` subtree (`specs/16-harness-discipline.md`)."""

    model_config = ConfigDict(extra="allow")

    snapshot: HarnessSnapshotSubConfig | None = None


class GatewaySteerConfig(BaseModel):
    """Bounded steer buffer (`gateway.steer`)."""

    model_config = ConfigDict(extra="allow")

    max_pending: int | None = None
    degrade_to_cancel_after_ms: int | None = None


class GatewayBudgetConfig(BaseModel):
    """``gateway.budget`` — per-turn executor round caps (`specs/14-executor-tier-b.md` §5).

    Attributes:
        tier_b_rounds (int): Default per-turn cap for the tier-B outer loop.
        tier_b_rounds_expanded (int): Cap used when retrying tier B after tier-C
            escalation is unavailable (`specs/17-gateway.md` §2.6 step 9).
        count_planning (bool): When ``False`` (default), LLM rounds that produced
            no tool call do not consume the budget; when ``True``, every LLM
            round is counted.
    """

    model_config = ConfigDict(extra="allow")

    tier_b_rounds: int = Field(default=TIER_B_MAX_ROUNDS, ge=1)
    tier_b_rounds_expanded: int = Field(default=TIER_B_MAX_ROUNDS_EXPANDED, ge=1)
    count_planning: bool = Field(default=TIER_B_COUNT_PLANNING)
    tier_b_max_output_tokens: int = Field(default=TIER_B_MAX_OUTPUT_TOKENS, ge=1)
    triager_max_output_tokens: int = Field(default=TRIAGER_MAX_OUTPUT_TOKENS, ge=1)
    tier_cd_max_output_tokens: int = Field(default=TIER_CD_MAX_OUTPUT_TOKENS, ge=1)
    guard_max_output_tokens: int = Field(default=GUARD_MAX_OUTPUT_TOKENS, ge=1)
    lcm_max_output_tokens: int = Field(default=LCM_MAX_OUTPUT_TOKENS, ge=1)
    dreaming_max_output_tokens: int = Field(default=DREAMING_MAX_OUTPUT_TOKENS, ge=1)
    user_model_max_output_tokens: int = Field(default=USER_MODEL_MAX_OUTPUT_TOKENS, ge=1)
    tier_b_executor_timeout_s: float = Field(
        default=DEFAULT_TIER_B_EXECUTOR_TIMEOUT_S,
        ge=1.0,
        description="Per-step tier-B wall-clock cap within the cascade (`specs/17-gateway.md`).",
    )
    tier_cd_executor_timeout_s: float = Field(
        default=DEFAULT_TIER_CD_EXECUTOR_TIMEOUT_S,
        ge=1.0,
        description="Per-step tier-C/D wall-clock cap within the cascade (same).",
    )
    cascade_budget_s: float = Field(
        default=DEFAULT_CASCADE_BUDGET_S,
        ge=1.0,
        description=(
            "Cumulative wall-clock cap across the B→retry→C/D cascade (same). "
            "Must exceed ``tier_b_executor_timeout_s``."
        ),
    )


class GatewayOutputConfig(BaseModel):
    """``gateway.output`` — tier-B answer delivery mode (`PROBLEMS.md` Priority 2).

    Attributes:
        tier_b_answer_mode (Literal["stream", "two_message_finally"]): Picks how
            the tier-B executor's final answer reaches the user.

            - ``two_message_finally`` (Step 5): preamble + editable answer
              placeholder shipped at turn start; the answer row exists from the
              moment the executor begins. ``_finalize_answer(turn_id, status)``
              in the ``finally`` clause is the only edit site, eliminating the
              "missing second answer" bug structurally.
            - ``stream`` (Step 6, default): edits the placeholder progressively
              as tokens arrive (~1s cadence within Telegram's edit rate limit).
              Requires pydantic-ai ``run_stream`` integration; falls back to
              ``two_message_finally`` behavior until Step 6 wires streaming.
        show_intent_footer (bool): When ``True``, the per-channel renderer
            attaches the routing classifier output (``intent``, ``tier``,
            ``conf``) read from ``gateway_turn_metadata``. The footer used to
            live inside the assistant message ``content`` (where it survived
            into the LLM context window); Step §7 moved it to a sibling table
            so the persisted message body stays clean regardless of the
            toggle. Default ``False`` (`PROBLEMS.md` §7).
    """

    model_config = ConfigDict(extra="allow")

    tier_b_answer_mode: Literal["stream", "two_message_finally"] = Field(
        default=cast("Literal['stream', 'two_message_finally']", TIER_B_ANSWER_MODE_DEFAULT),
    )
    show_intent_footer: bool = False


class GatewayConfig(BaseModel):
    """HTTP gateway bind + queue behaviour."""

    model_config = ConfigDict(extra="allow")

    host: str | None = None
    port: int | None = None
    token: str = Field(min_length=1)
    proxy_headers: bool | None = None
    queue_mode: Literal["cancel", "steer", "multi"] | None = None
    steer: GatewaySteerConfig | None = None
    budget: GatewayBudgetConfig | None = None
    restart: GatewayRestartConfig | None = None
    shutdown_timeout_s: float | None = None
    voice_trigger_keywords: list[str] | None = None
    dispatcher_callbacks_ttl_s: int | None = Field(
        default=None,
        ge=0,
        description="Prune dispatcher_callbacks older than this many seconds (§17 §3.4).",
    )
    first_session_intro: GatewayFirstSessionIntroConfig | None = None
    session_mirror: GatewaySessionMirrorConfig | None = None
    output: GatewayOutputConfig | None = None
    tool_as_skill_auto_route: bool = Field(
        default=False,
        description=(
            "When true, ``run_skill_script`` / ``run_skill_runnable`` with a registered "
            "tool name auto-dispatch that tool (default off; error + redirect first)."
        ),
    )

    @model_validator(mode="after")
    def _intro_max_output_tokens_within_tier_b_budget(self) -> Self:
        """Require intro ``max_output_tokens`` ≤ ``budget.tier_b_max_output_tokens``.

        Mirrors the runtime clamp in ``first_session_intro_max_output_tokens``
        (`specs/17-gateway.md` §2.6, `specs/14-executor-tier-b.md` §5).

        Args:
            self (GatewayConfig): Validated gateway subtree.

        Returns:
            GatewayConfig: Unchanged ``self`` when validation passes.

        Raises:
            ValueError: When the intro cap exceeds the tier-B output budget.

        Examples:
            >>> GatewayConfig(
            ...     token="tok",
            ...     first_session_intro=GatewayFirstSessionIntroConfig(max_output_tokens=2048),
            ...     budget=GatewayBudgetConfig(tier_b_max_output_tokens=4096),
            ... ).first_session_intro is not None
            True
        """
        intro_cfg = self.first_session_intro or GatewayFirstSessionIntroConfig()
        budget_cfg = self.budget or GatewayBudgetConfig()
        intro_cap = int(intro_cfg.max_output_tokens)
        tier_cap = int(budget_cfg.tier_b_max_output_tokens)
        if intro_cap > tier_cap:
            msg = (
                "gateway.first_session_intro.max_output_tokens "
                f"({intro_cap}) must be ≤ gateway.budget.tier_b_max_output_tokens "
                f"({tier_cap})"
            )
            raise ValueError(msg)
        return self
