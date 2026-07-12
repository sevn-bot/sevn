"""Structured-output patch author agent (`specs/33-self-improvement.md` §2.1).

Module: sevn.self_improve.proposer.agent
Depends: pydantic, pydantic_ai, sevn.agent.adapters.native_model, sevn.config.model_resolution,
    sevn.config.settings

Exports:
    PatchProposal — structured agent output schema.
    run_patch_proposal_agent — invoke tier-B model for one-shot patch proposal.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from sevn.agent.adapters.native_model import (
    default_native_model_context,
    resolve_pydantic_model_for_slot,
)
from sevn.config.model_resolution import ModelSlot, _providers_dict, resolve_model_slot
from sevn.config.settings import ProcessSettings

if TYPE_CHECKING:
    from sevn.agent.tracing.sink import TraceSink
    from sevn.config.workspace_config import WorkspaceConfig
    from sevn.workspace.layout import WorkspaceLayout

_PATCH_AUTHOR_SYSTEM = (
    "You are the sevn.bot self-improve patch author. Propose one safe, bounded edit "
    "under the allowlisted workspace paths. Respond only via the structured output schema."
)


class PatchProposal(BaseModel):
    """Structured patch proposal returned by the tier-B author agent."""

    target_path: str = Field(description="Repo-relative path under allowed_globs")
    content: str = Field(description="Full file content after the proposed change")


async def run_patch_proposal_agent(
    *,
    workspace: WorkspaceConfig,
    layout: WorkspaceLayout,
    job_id: str,
    user_prompt: str,
    trace: TraceSink | None = None,
    process: ProcessSettings | None = None,
) -> PatchProposal:
    """Run one structured-output patch proposal via ``ModelSlot.tier_b``.

    Args:
        workspace (WorkspaceConfig): Parsed workspace configuration.
        layout (WorkspaceLayout): Resolved filesystem layout.
        job_id (str): Improve job id used for trace correlation.
        user_prompt (str): Assembled user prompt from shortlist/context/plan.
        trace (TraceSink | None): Optional trace sink for provider spans.
        process (ProcessSettings | None): Process settings for proxy URL resolution.

    Returns:
        PatchProposal: Parsed structured proposal from the model.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(run_patch_proposal_agent)
        True
    """
    proc = process or ProcessSettings()
    proxy_base = (proc.proxy_url or "http://127.0.0.1:8787").rstrip("/")
    model_id = resolve_model_slot(workspace, ModelSlot.tier_b)
    ctx = default_native_model_context(
        slot=ModelSlot.tier_b,
        model_id=model_id,
        proxy_base=proxy_base,
        session_id=f"seimprove-{job_id}",
        turn_id=f"seimprove-{job_id}-patch",
        agent="self_improve_patch_author",
        trace=trace,
        content_root=layout.content_root,
        providers_obj=_providers_dict(workspace),
        tier="B",
    )
    model = resolve_pydantic_model_for_slot(workspace=workspace, ctx=ctx)
    agent = Agent(
        model,
        output_type=PatchProposal,
        instructions=_PATCH_AUTHOR_SYSTEM,
    )
    result = await agent.run(user_prompt)
    return result.output


__all__ = ["PatchProposal", "run_patch_proposal_agent"]
