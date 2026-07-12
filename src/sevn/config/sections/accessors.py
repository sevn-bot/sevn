"""Effective-config accessor helpers for parsed ``WorkspaceConfig``.

Module: sevn.config.sections.accessors
Depends: sevn.config.defaults, sevn.config.sections.gateway, sevn.config.sections.ops, sevn.config.sections.root

Exports:
    rlm_json_dict — JSON mapping of ``rlm`` for sandbox helpers.
    tier_b_skill_cap — effective ``triager.tier_b_skill_cap``.
    tier_b_rounds — effective ``gateway.budget.tier_b_rounds``.
    tier_b_rounds_expanded — effective ``gateway.budget.tier_b_rounds_expanded``.
    tier_b_count_planning — effective ``gateway.budget.count_planning``.
    tier_b_max_output_tokens — effective ``gateway.budget.tier_b_max_output_tokens``.
    agent_max_output_tokens_ceiling — per-agent ``sevn.json`` max-output ceiling.
    complexity_clamp_confidence_threshold — effective triager clamp threshold.
    complexity_clamp_short_word_limit — effective triager short-word limit.
    tier_b_executor_timeout_s — effective tier-B executor timeout.
    tier_cd_executor_timeout_s — effective tier-C/D executor timeout.
    cascade_budget_s — effective cascade wall-clock cap.
    tool_as_skill_auto_route_enabled — ``gateway.tool_as_skill_auto_route``.
    tool_debug_result_max_chars — effective ``logging.tool_debug_result_max_chars``.
    tier_b_answer_mode — effective ``gateway.output.tier_b_answer_mode``.
    show_intent_footer — effective ``gateway.output.show_intent_footer``.
    browser_settings — effective ``skills.browser.*``.
"""

from __future__ import annotations

from typing import Any

from sevn.config.defaults import (
    DEFAULT_COMPLEXITY_CLAMP_CONFIDENCE_THRESHOLD,
    DEFAULT_COMPLEXITY_CLAMP_SHORT_WORD_LIMIT,
    DEFAULT_TOOL_DEBUG_RESULT_MAX_CHARS,
    DEFAULT_TRIAGER_TIER_B_SKILL_CAP,
)
from sevn.config.sections.gateway import GatewayBudgetConfig, GatewayOutputConfig
from sevn.config.sections.ops import BrowserWorkspaceConfig
from sevn.config.sections.root import (
    WorkspaceConfig,  # noqa: TC001 — used in doctests and annotations
)


def rlm_json_dict(cfg: WorkspaceConfig) -> dict[str, Any]:
    """Return JSON-serialisable ``rlm.*`` mapping for sandbox drivers (`specs/21-executor-tier-cd.md` §5).

    Args:
        cfg (WorkspaceConfig): Parsed workspace root.

    Returns:
        dict[str, Any]: Empty dict when ``rlm`` unset; otherwise ``model_dump`` of the typed section.

    Examples:
        >>> rlm_json_dict(WorkspaceConfig.minimal()) == {}
        True
    """
    if cfg.rlm is None:
        return {}
    return cfg.rlm.model_dump(mode="json")


def tier_b_skill_cap(cfg: WorkspaceConfig | None) -> int:
    """Return effective ``triager.tier_b_skill_cap`` (`specs/12-skills-system.md` §5).

        Args:
    cfg (WorkspaceConfig | None): Parsed workspace config.

        Returns:
            int: At least ``1``; defaults to ``DEFAULT_TRIAGER_TIER_B_SKILL_CAP``.

        Examples:
            >>> tier_b_skill_cap(None) == DEFAULT_TRIAGER_TIER_B_SKILL_CAP
            True
            >>> tier_b_skill_cap(WorkspaceConfig.model_validate({
            ...     "schema_version": 1,
            ...     "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            ...     "triager": {"tier_b_skill_cap": 3},
            ... }))
            3
    """
    if cfg is None or cfg.triager is None:
        return DEFAULT_TRIAGER_TIER_B_SKILL_CAP
    return int(cfg.triager.tier_b_skill_cap)


def _gateway_budget(cfg: WorkspaceConfig | None) -> GatewayBudgetConfig:
    """Return the effective ``gateway.budget`` block, falling back to defaults.

    Args:
        cfg (WorkspaceConfig | None): Parsed workspace config or ``None``.

    Returns:
        GatewayBudgetConfig: Effective budget block (defaults when unset).

    Examples:
        >>> isinstance(_gateway_budget(None), GatewayBudgetConfig)
        True
    """
    if cfg is None or cfg.gateway is None or cfg.gateway.budget is None:
        return GatewayBudgetConfig()
    return cfg.gateway.budget


def tier_b_rounds(cfg: WorkspaceConfig | None) -> int:
    """Return effective ``gateway.budget.tier_b_rounds`` (`specs/14-executor-tier-b.md` §5).

    Args:
        cfg (WorkspaceConfig | None): Parsed workspace config or ``None``.

    Returns:
        int: Per-turn counted-round cap; defaults to ``TIER_B_MAX_ROUNDS``.

    Examples:
        >>> tier_b_rounds(None) == GatewayBudgetConfig().tier_b_rounds
        True
    """
    return int(_gateway_budget(cfg).tier_b_rounds)


def browser_settings(cfg: WorkspaceConfig | None) -> BrowserWorkspaceConfig:
    """Return effective ``skills.browser.*`` settings.

    Args:
        cfg (WorkspaceConfig | None): Parsed workspace config.

    Returns:
        BrowserWorkspaceConfig: Defaults when the section is absent.

    Examples:
        >>> browser_settings(None).idle_close_seconds
        0
        >>> browser_settings(WorkspaceConfig.model_validate({
        ...     "schema_version": 1,
        ...     "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
        ...     "skills": {"browser": {"headless": True, "idle_close_seconds": 300}},
        ... })).headless
        True
    """
    if cfg is None or cfg.skills is None:
        return BrowserWorkspaceConfig()
    block = cfg.skills.get("browser")
    if not isinstance(block, dict):
        return BrowserWorkspaceConfig()
    return BrowserWorkspaceConfig.model_validate(block)


def tier_b_rounds_expanded(cfg: WorkspaceConfig | None) -> int:
    """Return effective ``gateway.budget.tier_b_rounds_expanded`` (`specs/17-gateway.md` §2.6).

    Args:
        cfg (WorkspaceConfig | None): Parsed workspace config or ``None``.

    Returns:
        int: Expanded cap used on tier-C-unavailable retry; defaults to
        ``TIER_B_MAX_ROUNDS_EXPANDED``.

    Examples:
        >>> tier_b_rounds_expanded(None) == GatewayBudgetConfig().tier_b_rounds_expanded
        True
    """
    return int(_gateway_budget(cfg).tier_b_rounds_expanded)


def tier_b_count_planning(cfg: WorkspaceConfig | None) -> bool:
    """Return effective ``gateway.budget.count_planning`` (`specs/14-executor-tier-b.md` §5).

    Args:
        cfg (WorkspaceConfig | None): Parsed workspace config or ``None``.

    Returns:
        bool: Whether planning-only LLM rounds count toward the budget; defaults to
        ``TIER_B_COUNT_PLANNING`` (``False``).

    Examples:
        >>> tier_b_count_planning(None) == GatewayBudgetConfig().count_planning
        True
    """
    return bool(_gateway_budget(cfg).count_planning)


def tool_debug_result_max_chars(cfg: WorkspaceConfig | None) -> int | None:
    """Return effective ``logging.tool_debug_result_max_chars``.

    When ``None``, ``TracingToolExecutor`` logs the full tool result envelope on
    ``tool_call.finish`` DEBUG lines. A positive integer truncates with ``...``.

    Args:
        cfg (WorkspaceConfig | None): Parsed workspace; ``None`` uses defaults.

    Returns:
        int | None: Max result characters for DEBUG logs, or unlimited when ``None``.

    Examples:
        >>> tool_debug_result_max_chars(None) is None
        True
    """
    if cfg is None or cfg.logging is None:
        return DEFAULT_TOOL_DEBUG_RESULT_MAX_CHARS
    return cfg.logging.tool_debug_result_max_chars


def tool_as_skill_auto_route_enabled(cfg: WorkspaceConfig | None) -> bool:
    """Return whether tool names passed to ``run_skill_*`` auto-dispatch the tool.

    Args:
        cfg (WorkspaceConfig | None): Parsed workspace config.

    Returns:
        bool: ``gateway.tool_as_skill_auto_route`` (default ``False``).

    Examples:
        >>> tool_as_skill_auto_route_enabled(None)
        False
    """
    if cfg is None or cfg.gateway is None:
        return False
    return bool(cfg.gateway.tool_as_skill_auto_route)


def tier_b_max_output_tokens(cfg: WorkspaceConfig | None) -> int:
    """Return effective ``gateway.budget.tier_b_max_output_tokens``.

    Args:
        cfg (WorkspaceConfig | None): Parsed workspace config or ``None``.

    Returns:
        int: Provider-side max output token cap for tier-B; defaults to
        :data:`TIER_B_MAX_OUTPUT_TOKENS`.

    Examples:
        >>> tier_b_max_output_tokens(None) == GatewayBudgetConfig().tier_b_max_output_tokens
        True
    """
    return int(_gateway_budget(cfg).tier_b_max_output_tokens)


def agent_max_output_tokens_ceiling(cfg: WorkspaceConfig | None, agent: str) -> int:
    """Return the ``sevn.json`` max-output ceiling for one LLM agent key.

    Args:
        cfg (WorkspaceConfig | None): Parsed workspace config or ``None``.
        agent (str): One of :data:`sevn.config.llm_params.AGENT_NAMES`.

    Returns:
        int: ``gateway.budget.<agent>_max_output_tokens`` (``tier_b`` maps to
        ``tier_b_max_output_tokens``).

    Raises:
        ValueError: When ``agent`` is not a known LLM agent key.

    Examples:
        >>> agent_max_output_tokens_ceiling(None, "triager") == GatewayBudgetConfig().triager_max_output_tokens
        True
        >>> agent_max_output_tokens_ceiling(None, "tier_b") == GatewayBudgetConfig().tier_b_max_output_tokens
        True
    """
    budget = _gateway_budget(cfg)
    key = agent.strip().lower()
    field_map = {
        "triager": "triager_max_output_tokens",
        "tier_b": "tier_b_max_output_tokens",
        "tier_cd": "tier_cd_max_output_tokens",
        "guard": "guard_max_output_tokens",
        "lcm": "lcm_max_output_tokens",
        "dreaming": "dreaming_max_output_tokens",
        "user_model": "user_model_max_output_tokens",
    }
    field = field_map.get(key)
    if field is None:
        msg = f"unknown LLM agent for max_output_tokens ceiling: {agent!r}"
        raise ValueError(msg)
    return int(getattr(budget, field))


def complexity_clamp_confidence_threshold(cfg: WorkspaceConfig | None) -> float:
    """Return effective ``triager.complexity_clamp_confidence_threshold``.

    Args:
        cfg (WorkspaceConfig | None): Parsed workspace config or ``None``.

    Returns:
        float: Confidence floor above which C/D routes are kept; defaults to
        :data:`DEFAULT_COMPLEXITY_CLAMP_CONFIDENCE_THRESHOLD`.

    Examples:
        >>> complexity_clamp_confidence_threshold(None) == DEFAULT_COMPLEXITY_CLAMP_CONFIDENCE_THRESHOLD
        True
    """
    if cfg is None or cfg.triager is None:
        return DEFAULT_COMPLEXITY_CLAMP_CONFIDENCE_THRESHOLD
    return float(cfg.triager.complexity_clamp_confidence_threshold)


def complexity_clamp_short_word_limit(cfg: WorkspaceConfig | None) -> int:
    """Return effective ``triager.complexity_clamp_short_word_limit``.

    Args:
        cfg (WorkspaceConfig | None): Parsed workspace config or ``None``.

    Returns:
        int: Word-count ceiling for the complexity clamp; defaults to
        :data:`DEFAULT_COMPLEXITY_CLAMP_SHORT_WORD_LIMIT`.

    Examples:
        >>> complexity_clamp_short_word_limit(None) == DEFAULT_COMPLEXITY_CLAMP_SHORT_WORD_LIMIT
        True
    """
    if cfg is None or cfg.triager is None:
        return DEFAULT_COMPLEXITY_CLAMP_SHORT_WORD_LIMIT
    return int(cfg.triager.complexity_clamp_short_word_limit)


def tier_b_executor_timeout_s(cfg: WorkspaceConfig | None) -> float:
    """Return effective ``gateway.budget.tier_b_executor_timeout_s``.

    Args:
        cfg (WorkspaceConfig | None): Parsed workspace config or ``None``.

    Returns:
        float: Per-step tier-B wall-clock cap; defaults to
        :data:`DEFAULT_TIER_B_EXECUTOR_TIMEOUT_S`.

    Examples:
        >>> tier_b_executor_timeout_s(None) == GatewayBudgetConfig().tier_b_executor_timeout_s
        True
    """
    return float(_gateway_budget(cfg).tier_b_executor_timeout_s)


def tier_cd_executor_timeout_s(cfg: WorkspaceConfig | None) -> float:
    """Return effective ``gateway.budget.tier_cd_executor_timeout_s``.

    Args:
        cfg (WorkspaceConfig | None): Parsed workspace config or ``None``.

    Returns:
        float: Per-step tier-C/D wall-clock cap; defaults to
        :data:`DEFAULT_TIER_CD_EXECUTOR_TIMEOUT_S`.

    Examples:
        >>> tier_cd_executor_timeout_s(None) == GatewayBudgetConfig().tier_cd_executor_timeout_s
        True
    """
    return float(_gateway_budget(cfg).tier_cd_executor_timeout_s)


def cascade_budget_s(cfg: WorkspaceConfig | None) -> float:
    """Return effective ``gateway.budget.cascade_budget_s``.

    Args:
        cfg (WorkspaceConfig | None): Parsed workspace config or ``None``.

    Returns:
        float: Cumulative cascade wall-clock cap; defaults to
        :data:`DEFAULT_CASCADE_BUDGET_S`.

    Examples:
        >>> cascade_budget_s(None) == GatewayBudgetConfig().cascade_budget_s
        True
    """
    return float(_gateway_budget(cfg).cascade_budget_s)


def tier_b_answer_mode(cfg: WorkspaceConfig | None) -> str:
    """Return effective ``gateway.output.tier_b_answer_mode`` (``PROBLEMS.md`` Priority 2).

    Args:
        cfg (WorkspaceConfig | None): Parsed workspace config or ``None``.

    Returns:
        str: ``"stream"`` or ``"two_message_finally"``; defaults to
        :data:`TIER_B_ANSWER_MODE_DEFAULT`.

    Examples:
        >>> tier_b_answer_mode(None) == GatewayOutputConfig().tier_b_answer_mode
        True
        >>> tier_b_answer_mode(WorkspaceConfig.model_validate({
        ...     "schema_version": 1,
        ...     "gateway": {
        ...         "token": "${SECRET:keychain:sevn.gateway.token}",
        ...         "output": {"tier_b_answer_mode": "two_message_finally"},
        ...     },
        ... }))
        'two_message_finally'
    """
    if cfg is None or cfg.gateway is None or cfg.gateway.output is None:
        return str(GatewayOutputConfig().tier_b_answer_mode)
    return str(cfg.gateway.output.tier_b_answer_mode)


def show_intent_footer(cfg: WorkspaceConfig | None) -> bool:
    """Return effective ``gateway.output.show_intent_footer`` (`PROBLEMS.md` §7).

    Args:
        cfg (WorkspaceConfig | None): Parsed workspace config or ``None``.

    Returns:
        bool: ``True`` when the renderer should attach the
        ``_intent=… · tier=… · conf=…_`` footer (read from
        ``gateway_turn_metadata``). Defaults to ``False`` so the debug
        classifier output stays out of user-facing chat.

    Examples:
        >>> show_intent_footer(None)
        False
        >>> show_intent_footer(WorkspaceConfig.model_validate({
        ...     "schema_version": 1,
        ...     "gateway": {
        ...         "token": "${SECRET:keychain:sevn.gateway.token}",
        ...         "output": {"show_intent_footer": True},
        ...     },
        ... }))
        True
    """
    if cfg is None or cfg.gateway is None or cfg.gateway.output is None:
        return False
    return bool(cfg.gateway.output.show_intent_footer)
