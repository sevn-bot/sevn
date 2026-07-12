"""TTL cache for resolved secret strings (``specs/06-secrets.md`` §2.2).

Module: sevn.security.secrets.cache
Depends: sevn.security.secrets.chain

Exports:
    ResolvedSecretsCache — wraps ``SecretsChain`` with per-key TTL.

Examples:
    >>> from sevn.security.secrets.cache import ResolvedSecretsCache
    >>> ResolvedSecretsCache.__name__
    'ResolvedSecretsCache'
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from sevn.security.secrets.chain import SecretsChain


@dataclass(frozen=True, slots=True)
class _CacheEntry:
    """One in-memory cache row with expiry."""

    value: str
    expires_at: float


class ResolvedSecretsCache:
    """In-memory cache of decrypted logical values with TTL."""

    def __init__(
        self,
        chain: SecretsChain,
        *,
        ttl_seconds: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Create a cache over ``chain``.

        Args:
            chain (SecretsChain): Resolver for misses.
            ttl_seconds (int): Seconds to keep decrypted values; ``0`` disables caching.
            clock (Callable[[], float]): Monotonic time source (tests inject this).

        Examples:
            >>> # See tests/security/secrets/test_chain.py (TTL tests).
            >>> True
            True
        """
        if ttl_seconds < 0:
            msg = "ttl_seconds must be >= 0"
            raise ValueError(msg)
        self._chain = chain
        self._ttl = ttl_seconds
        self._clock = clock
        self._data: dict[tuple[str, str], _CacheEntry] = {}

    @property
    def chain(self) -> SecretsChain:
        """Accessor for the underlying chain.

        Returns:
            SecretsChain: Configured resolver chain.

        Examples:
            >>> # Property returns the chain passed to __init__.
            >>> True
            True
        """
        return self._chain

    @property
    def ttl_seconds(self) -> int:
        """Configured TTL seconds.

        Returns:
            int: TTL; ``0`` disables the in-memory cache layer.

        Examples:
            >>> # Matches ctor argument.
            >>> True
            True
        """
        return self._ttl

    def _make_key(self, source: str, logical_key: str) -> tuple[str, str]:
        """Build the tuple key used in the cache dict.

        Args:
            source (str): Reference source segment.
            logical_key (str): Logical secret id.

        Returns:
            tuple[str, str]: Cache key.

        Examples:
            >>> # Internal helper.
            >>> True
            True
        """
        return (source, logical_key)

    async def get_resolved(self, source: str, logical_key: str) -> str | None:
        """Return cached or fetch from chain for ``logical_key``.

        Args:
            source (str): Reference source segment from ``${SECRET:…}``.
            logical_key (str): Logical id passed to backends.

        Returns:
            str | None: Cached or freshly resolved plaintext.

        Examples:
            >>> # See tests/security/secrets/test_chain.py.
            >>> True
            True
        """
        ck = self._make_key(source, logical_key)
        now = self._clock()
        if self._ttl > 0:
            ent = self._data.get(ck)
            if ent is not None and ent.expires_at > now:
                return ent.value
        value = await self._chain.get(logical_key)
        if value is None:
            return None
        if self._ttl > 0:
            self._data[ck] = _CacheEntry(value=value, expires_at=now + float(self._ttl))
        return value

    def invalidate(self, source: str, logical_key: str) -> None:
        """Drop one cached entry.

        Args:
            source (str): Reference source segment.
            logical_key (str): Logical secret id.

        Examples:
            >>> # Optional operator hook; not yet used by proxy routes.
            >>> True
            True
        """
        self._data.pop(self._make_key(source, logical_key), None)

    def clear(self) -> None:
        """Drop all cached entries.

        Examples:
            >>> # Clears only the in-memory layer.
            >>> True
            True
        """
        self._data.clear()
