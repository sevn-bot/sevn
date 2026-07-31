"""Shared Telegram form step prompt helpers (#71 / D19).

Module: sevn.gateway.commands.form_prompts
Depends: none

Exports:
    form_prompt_with_cancel — append cancel affordance to a form step prompt.
"""

from __future__ import annotations

_FORM_CANCEL_HINT = "Send cancel or abort to exit."


def form_prompt_with_cancel(prompt: str) -> str:
    """Append the canonical form cancel affordance to a step prompt.

    Args:
        prompt (str): Base step prompt text.

    Returns:
        str: Prompt with cancel vocabulary appended.

    Examples:
        >>> "cancel" in form_prompt_with_cancel("Send tunnel mode:").lower()
        True
    """
    return f"{prompt}\n\n{_FORM_CANCEL_HINT}"


__all__ = ["form_prompt_with_cancel"]
