"""Ordered backend chain with read/write policy (``specs/06-secrets.md`` §2.2, §5).

Module: sevn.security.secrets.chain
Depends: sevn.security.secrets.protocol

Exports:
    SecretsChain — fallback ``get``; ``set`` / ``delete`` per ``write_targets``.
    SecretsChainWriteError — raised when no writable backend matches policy.
    get_secret_resilient — read across backends, skipping locked encrypted stores.

Examples:
    >>> from sevn.security.secrets.chain import SecretsChain, SecretsChainWriteError
    >>> SecretsChainWriteError.__name__
    'SecretsChainWriteError'
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Literal

from sevn.security.secrets.errors import SecretsStoreCorruptError, is_encrypted_store_unlock_error

if TYPE_CHECKING:
    from sevn.security.secrets.protocol import SecretsBackend


class SecretsChain:
    """Try backends in order for ``get``; route writes per policy."""

    def __init__(
        self,
        backends: list[SecretsBackend],
        *,
        write_targets: list[str] | Literal["first_writable"] = "first_writable",
        backend_labels: list[str] | None = None,
    ) -> None:
        """Build a chain.

        Args:
            backends (list[SecretsBackend]): Ordered stores (read fallback order).
            write_targets (list[str] | Literal["first_writable"]): Policy label list or
                ``first_writable`` (§5).
            backend_labels (list[str] | None): Per-backend labels matching ``write_targets``.

        Examples:
            >>> # See tests/security/secrets/test_chain.py.
            >>> True
            True
        """
        if not backends:
            msg = "SecretsChain requires at least one backend"
            raise ValueError(msg)
        self._backends = backends
        self._write_targets = write_targets
        self._labels = backend_labels or [f"b{i}" for i in range(len(backends))]

    @property
    def backends(self) -> tuple[SecretsBackend, ...]:
        """Return ordered backends for inspection.

        Returns:
            tuple[SecretsBackend, ...]: Snapshot of configured backends.

        Examples:
            >>> # Populated in tests via fakes.
            >>> True
            True
        """
        return tuple(self._backends)

    async def get(self, key: str) -> str | None:
        """Return the first hit across backends.

        Args:
            key (str): Logical secret id.

        Returns:
            str | None: Plaintext from the first backend that has the key.

        Examples:
            >>> # Covered by tests/security/secrets/test_chain.py.
            >>> True
            True
        """
        for backend in self._backends:
            value = await backend.get(key)
            if value is not None:
                return value
        return None

    async def get_resilient(self, key: str) -> str | None:
        """Return the first hit, skipping encrypted stores that need an unlock passphrase.

        Args:
            key (str): Logical secret id.

        Returns:
            str | None: Plaintext from env or the first backend that yields a value.

        Examples:
            >>> # Covered by tests/security/secrets/test_chain.py.
            >>> True
            True
        """
        return await get_secret_resilient(self, key)

    def _iter_write_backends(self) -> list[tuple[str, SecretsBackend]]:
        """Resolve write targets to (label, backend) pairs.

        Returns:
            list[tuple[str, SecretsBackend]]: Writable backends in policy order.

        Examples:
            >>> # Internal; exercised via SecretsChain.set.
            >>> True
            True
        """
        if self._write_targets == "first_writable":
            return [(self._labels[0], self._backends[0])]
        out: list[tuple[str, SecretsBackend]] = []
        for label, backend in zip(self._labels, self._backends, strict=True):
            if label in self._write_targets:
                out.append((label, backend))
        return out

    async def set(self, key: str, value: str) -> None:
        """Persist using ``write_targets`` policy.

        Args:
            key (str): Logical secret id.
            value (str): UTF-8 plaintext.

        Examples:
            >>> # See tests/security/secrets/test_chain.py.
            >>> True
            True
        """
        targets = self._iter_write_backends()
        if not targets:
            msg = "no writable backend configured for SecretsChain.set"
            raise SecretsChainWriteError(msg)
        for _label, backend in targets:
            await backend.set(key, value)

    async def delete(self, key: str) -> None:
        """Remove from writable target(s).

        Args:
            key (str): Logical secret id.

        Examples:
            >>> # See tests/security/secrets/test_chain.py.
            >>> True
            True
        """
        targets = self._iter_write_backends()
        if not targets:
            msg = "no writable backend configured for SecretsChain.delete"
            raise SecretsChainWriteError(msg)
        for _label, backend in targets:
            await backend.delete(key)


class SecretsChainWriteError(RuntimeError):
    """``set``/``delete`` could not target a backend."""


async def get_secret_resilient(chain: SecretsChain, key: str) -> str | None:
    """Read one logical key across a chain, skipping locked encrypted-file backends.

    Args:
        chain (SecretsChain): Workspace secrets chain.
        key (str): Logical secret id.

    Returns:
        str | None: Plaintext when found in process env or any backend.

    Examples:
        >>> # Covered by tests/security/secrets/test_chain.py.
        >>> True
        True
    """
    env_val = os.environ.get(key, "").strip()
    if env_val:
        return env_val
    for backend in chain.backends:
        try:
            value = await backend.get(key)
        except SecretsStoreCorruptError as exc:
            # A *locked* backend (no key material) is skipped so the next chain entry can answer.
            # A *wrong-key* / *corrupt* store re-raises: silently skipping it degrades resolution
            # to "secret missing" and hides misconfiguration (see is_encrypted_store_unlock_error).
            if is_encrypted_store_unlock_error(exc):
                continue
            raise
        if value is not None:
            return value
    return None
