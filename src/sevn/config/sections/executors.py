"""Executors, RLM, and plan_approval subtree models for ``sevn.json``.

Module: sevn.config.sections.executors
Depends: pydantic, sevn.config.defaults

Exports:
    PlanApprovalWorkspaceConfig — ``plan_approval`` subtree (`specs/21-executor-tier-cd.md` §5).
    TierCdLambdaRlmConfig — ``executors.tier_cd.lambda_rlm`` opt-in gate (same §5).
    TierCdExecutorConfig — ``executors.tier_cd`` subtree (same).
    ExecutorsWorkspaceConfig — ``executors`` subtree (same).
    RlmWorkspaceConfig — typed ``rlm`` subtree for C/D backends (same §5).
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sevn.config.defaults import (
    DEFAULT_PLAN_APPROVAL_ENABLED,
    DEFAULT_RLM_C_D_BACKEND,
    DEFAULT_RLM_REPL_LIFETIME,
    DEFAULT_TIER_CD_LAMBDA_RLM_ENABLED,
)


class PlanApprovalWorkspaceConfig(BaseModel):
    """``plan_approval`` subtree (`specs/21-executor-tier-cd.md` §5)."""

    model_config = ConfigDict(extra="allow")

    enabled: bool = Field(default=DEFAULT_PLAN_APPROVAL_ENABLED)


class TierCdLambdaRlmConfig(BaseModel):
    """``executors.tier_cd.lambda_rlm`` — opt-in λ-RLM gate (`specs/21-executor-tier-cd.md` §5)."""

    model_config = ConfigDict(extra="allow")

    enabled: bool = Field(default=DEFAULT_TIER_CD_LAMBDA_RLM_ENABLED)


class TierCdExecutorConfig(BaseModel):
    """``executors.tier_cd`` subtree for C/D harness knobs."""

    model_config = ConfigDict(extra="allow")

    lambda_rlm: TierCdLambdaRlmConfig | None = None


class ExecutorsWorkspaceConfig(BaseModel):
    """``executors`` subtree (`specs/21-executor-tier-cd.md` §5)."""

    model_config = ConfigDict(extra="allow")

    tier_cd: TierCdExecutorConfig | None = None


class RlmWorkspaceConfig(BaseModel):
    """Typed ``rlm`` subtree for C/D backends + REPL knobs (`specs/21-executor-tier-cd.md` §5)."""

    model_config = ConfigDict(extra="allow")

    c_d_backend: Literal["dspy", "lambda_rlm"] = Field(default=DEFAULT_RLM_C_D_BACKEND)
    lambda_tool_allowlist: list[str] = Field(default_factory=list)
    repl_lifetime: Literal["per_turn", "per_session", "per_run"] = Field(
        default=DEFAULT_RLM_REPL_LIFETIME,
    )
    docker_image: str | None = None
    sandbox: Literal["docker", "pyodide_deno"] | None = None

    @model_validator(mode="after")
    def _lambda_backend_requires_allowlist(self) -> Self:
        """Fail fast when λ-RLM is enabled without combinator leaves (`specs/21-executor-tier-cd.md` §5).

        Args:
            self (RlmWorkspaceConfig): Validated ``rlm`` subtree.

        Returns:
            RlmWorkspaceConfig: Unchanged ``self`` when validation passes.

        Raises:
            ValueError: When ``c_d_backend`` is ``lambda_rlm`` and the allowlist is empty.

        Examples:
            >>> m = RlmWorkspaceConfig(
            ...     c_d_backend="lambda_rlm",
            ...     lambda_tool_allowlist=["echo"],
            ... )
            >>> m.c_d_backend
            'lambda_rlm'
        """

        if self.c_d_backend == "lambda_rlm" and not self.lambda_tool_allowlist:
            msg = (
                "rlm.lambda_tool_allowlist must be non-empty when rlm.c_d_backend is "
                "lambda_rlm (specs/21-executor-tier-cd.md §5)"
            )
            raise ValueError(msg)
        return self
