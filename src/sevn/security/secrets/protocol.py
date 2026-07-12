"""``SecretsBackend`` protocol (``specs/06-secrets.md`` §2.1).

Module: sevn.security.secrets.protocol
Depends: typing

Exports:
    SecretsBackend — async protocol for one physical store.

Examples:
    >>> from sevn.security.secrets.protocol import SecretsBackend
    >>> hasattr(SecretsBackend, "get")
    True
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class SecretsBackend(Protocol):
    """One physical store (keychain slice, file, OpenBao mount, …)."""

    async def get(self, key: str) -> str | None:
        """Return decrypted text for ``key``, or ``None`` if absent.

        Args:
            key (str): Logical secret id.

        Returns:
            str | None: Plaintext when found.

        Examples:
            >>> # Implemented by concrete backends.
            >>> True
            True
        """
        ...

    async def set(self, key: str, value: str) -> None:
        """Persist ``value`` for ``key`` (replace semantics).

        Args:
            key (str): Logical secret id.
            value (str): UTF-8 plaintext to store.

        Examples:
            >>> # Implemented by concrete backends.
            >>> True
            True
        """
        ...

    async def delete(self, key: str) -> None:
        """Remove ``key`` if present (idempotent).

        Args:
            key (str): Logical secret id.

        Examples:
            >>> # Implemented by concrete backends.
            >>> True
            True
        """
        ...
