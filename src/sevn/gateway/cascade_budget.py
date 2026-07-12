"""Cumulative wall-clock budget for the tier B → C/D cascade (`specs/17-gateway.md` §3.4).

Module: sevn.gateway.cascade_budget
Depends: time

Exports:
    CascadeBudget — cap-minus-elapsed accounting with injectable ``time_ns`` clock.
"""

from __future__ import annotations

from collections.abc import Callable
from time import time_ns


class CascadeBudget:
    """Track remaining seconds in the per-turn cascade wall-clock budget.

    Mirrors the legacy ``_remaining_budget_s`` closure in ``agent_turn.py``:
    ``start_ns`` is captured at construction; ``remaining_s()`` returns
    ``max(0.0, cap_s - elapsed)`` using an injectable ``clock_ns`` for tests.

    Args:
        cap_s (float): Configured cumulative cascade cap in seconds.
        clock_ns (Callable[[], int], optional): Monotonic nanosecond clock;
            defaults to :func:`time.time_ns`.

    Examples:
        >>> state = {"ns": 1_000_000_000}
        >>> def fake_clock() -> int:
        ...     return state["ns"]
        >>> budget = CascadeBudget(10.0, clock_ns=fake_clock)
        >>> budget.remaining_s()
        10.0
        >>> state["ns"] += 3_000_000_000
        >>> budget.remaining_s()
        7.0
        >>> budget.clamp(180.0)
        7.0
        >>> state["ns"] += 8_000_000_000
        >>> budget.exhausted()
        True
        >>> budget.remaining_s()
        0.0
    """

    def __init__(
        self,
        cap_s: float,
        *,
        clock_ns: Callable[[], int] = time_ns,
    ) -> None:
        """Capture the cascade cap and wall-clock start anchor.

        Args:
            cap_s (float): Configured cumulative cascade cap in seconds.
            clock_ns (Callable[[], int], optional): Monotonic nanosecond clock;
                defaults to :func:`time.time_ns`.

        Examples:
            >>> CascadeBudget(60.0) is not None
            True
        """
        self._cap_s = cap_s
        self._clock_ns = clock_ns
        self._start_ns = clock_ns()

    def remaining_s(self) -> float:
        """Return seconds left in the cascade budget (floored at zero).

        Returns:
            float: ``max(0.0, cap_s - elapsed)`` where elapsed is derived from
            ``(clock_ns() - start_ns) / 1e9``.

        Examples:
            >>> state = {"ns": 0}
            >>> budget = CascadeBudget(5.0, clock_ns=lambda: state["ns"])
            >>> budget.remaining_s()
            5.0
            >>> state["ns"] = 2_000_000_000
            >>> budget.remaining_s()
            3.0
        """
        elapsed = (self._clock_ns() - self._start_ns) / 1e9
        return max(0.0, self._cap_s - elapsed)

    def exhausted(self) -> bool:
        """Return ``True`` when no cascade budget remains.

        Returns:
            bool: ``True`` when ``remaining_s()`` is zero after flooring.

        Examples:
            >>> state = {"ns": 0}
            >>> budget = CascadeBudget(1.0, clock_ns=lambda: state["ns"])
            >>> budget.exhausted()
            False
            >>> state["ns"] = 1_000_000_000
            >>> budget.exhausted()
            True
        """
        return self.remaining_s() <= 0.0

    def clamp(self, phase_timeout_s: float) -> float:
        """Return ``min(phase_timeout_s, remaining_s())``.

        Args:
            phase_timeout_s (float): Executor or phase wall-clock cap.

        Returns:
            float: Effective timeout bounded by remaining cascade budget.

        Examples:
            >>> state = {"ns": 0}
            >>> budget = CascadeBudget(30.0, clock_ns=lambda: state["ns"])
            >>> budget.clamp(180.0)
            30.0
            >>> state["ns"] = 25_000_000_000
            >>> budget.clamp(180.0)
            5.0
        """
        return min(phase_timeout_s, self.remaining_s())
