"""Shared tier-B / pydantic-ai retry error predicates.

Module: sevn.agent.executors.retry_errors
Depends: (none)

Exports:
    is_empty_output_retry_error — detect pydantic-ai empty-output retry exhaustion.
"""

from __future__ import annotations

__all__ = ["is_empty_output_retry_error"]


def is_empty_output_retry_error(exc: BaseException) -> bool:
    """Return True when pydantic-ai exhausted retries on empty model output.

    Args:
        exc (BaseException): Error raised from ``agent.run``.

    Returns:
        bool: True when the message signals ``maximum output retries``.

    Examples:
        >>> is_empty_output_retry_error(RuntimeError("Exceeded maximum output retries (3)"))
        True
        >>> is_empty_output_retry_error(ValueError("bad json"))
        False
    """
    return "maximum output retries" in str(exc).lower()
