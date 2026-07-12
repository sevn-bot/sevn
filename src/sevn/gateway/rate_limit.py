"""Per-scope token bucket limiter (`specs/17-gateway.md` §4.3 step 3).

Parallel level-1 sub-agent replies in ``multi`` queue mode each call
:meth:`sevn.gateway.channel_router.ChannelRouter.route_outgoing`, which
consumes one token per ``scope`` via :meth:`TokenBucketLimiter.allow` — the
same path as classic single-turn sends, so interleaved multi-agent footers
do not bypass rate limiting.

Module: sevn.gateway.rate_limit
Depends: asyncio, time

Exports:
    TokenBucketLimiter — ``allow`` guard for ``scope`` keys.
"""

from __future__ import annotations

import asyncio
import time


class TokenBucketLimiter:
    """Cheap in-memory limiter keyed by session scope / user id."""

    def __init__(self, *, capacity: float, refill_per_second: float) -> None:
        """Initialise the limiter with bucket size and refill rate.

        Args:
            capacity (float): Maximum tokens per bucket.
            refill_per_second (float): Token regeneration rate per second.

        Examples:
            >>> TokenBucketLimiter(capacity=1.0, refill_per_second=1.0) is not None
            True
        """
        self._capacity = capacity
        self._refill = refill_per_second
        self._tokens: dict[str, float] = {}
        self._last_seen: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def allow(self, key: str) -> bool:
        """Return ``True`` when one token is available (consumes the token).

        Args:
            key (str): Bucket key (per-scope identifier).

        Returns:
            bool: ``True`` when a token was consumed, ``False`` when starved.

        Examples:
            >>> import asyncio
            >>> rl = TokenBucketLimiter(capacity=1.0, refill_per_second=0.0)
            >>> asyncio.run(rl.allow("k"))
            True
            >>> asyncio.run(rl.allow("k"))
            False
        """

        async with self._lock:
            now = time.monotonic()
            last = self._last_seen.get(key, now)
            elapsed = max(0.0, now - last)
            current = self._tokens.get(key, self._capacity)
            current = min(self._capacity, current + elapsed * self._refill)
            self._last_seen[key] = now
            EPS = 1e-9
            if current + EPS < 1.0:
                self._tokens[key] = current
                return False
            self._tokens[key] = current - 1.0
            return True
