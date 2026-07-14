"""Gateway hook registration for user-model extraction (Batch D lane #6).

Module: sevn.gateway.user.user_model_hooks
Depends: sevn.gateway.hooks.post_turn_hooks, sevn.gateway.user.user_model_turn

Exports:
    register_user_model_hooks — register post-turn extraction hook via CW-1.
"""

from __future__ import annotations

from sevn.gateway.hooks.post_turn_hooks import register_post_turn_hook
from sevn.gateway.user.user_model_turn import maybe_schedule_user_model_extraction_after_turn


def register_user_model_hooks() -> None:
    """Register user-model post-turn hook via CW-1 registry.

    Examples:
        >>> "register_user_model_hooks" in __all__
        True
    """
    register_post_turn_hook(
        "user_model_extraction",
        maybe_schedule_user_model_extraction_after_turn,
        priority=40,
    )


register_user_model_hooks()

__all__ = ["register_user_model_hooks"]
