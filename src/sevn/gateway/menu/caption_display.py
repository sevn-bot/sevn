"""Telegram ``/config`` caption value resolution for CLI dot paths (#115, #116).

Module: sevn.gateway.menu.caption_display
Depends: sevn.cli.config_sections, sevn.config.model_resolution, sevn.config.workspace_config

Exports:
    telegram_config_dot_path_display — resolved model ids and repr-style caption suffixes.
"""

from __future__ import annotations

from typing import Any

from sevn.cli.config_sections import nested_get
from sevn.config.errors import TriagerUnavailable
from sevn.config.model_resolution import ModelSlot, resolve_model_slot, use_main_model_for_all
from sevn.config.workspace_config import WorkspaceConfig

_AGENT_CAPTION_MODEL_PATHS: dict[str, ModelSlot | tuple[ModelSlot, ModelSlot]] = {
    "agent.triager.model": ModelSlot.triager,
    "agent.tier_b.model": ModelSlot.tier_b,
    "agent.tier_cd.model": (ModelSlot.tier_c, ModelSlot.tier_d),
}


def telegram_config_dot_path_display(
    workspace: WorkspaceConfig,
    raw_doc: dict[str, Any],
    path: str,
) -> str:
    """Return a caption value for one CLI dot path (resolved models when applicable).

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings.
        raw_doc (dict[str, Any]): Raw ``sevn.json`` document.
        path (str): Dot-separated config path.

    Returns:
        str: ``repr``-style display fragment for the caption line suffix.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> ws = WorkspaceConfig.minimal(
        ...     providers={
        ...         "use_main_model_for_all": False,
        ...         "tier_default": {"triager": "openai/gpt-4o-mini", "B": "openai/gpt-4o-mini"},
        ...     },
        ... )
        >>> val = telegram_config_dot_path_display(ws, {}, "agent.tier_b.model")
        >>> val == "'openai/gpt-4o-mini'"
        True
    """
    slots = _AGENT_CAPTION_MODEL_PATHS.get(path)
    if slots is not None:
        try:
            if isinstance(slots, tuple):
                vals = [resolve_model_slot(workspace, slot) for slot in slots]
                if len(set(vals)) == 1:
                    return repr(vals[0])
                return repr(" / ".join(vals))
            return repr(resolve_model_slot(workspace, slots))
        except TriagerUnavailable:
            pass
    if path == "agent.unified_model.enabled":
        return repr(use_main_model_for_all(workspace))
    value = nested_get(raw_doc, path)
    return repr(value)


__all__ = ["telegram_config_dot_path_display"]
