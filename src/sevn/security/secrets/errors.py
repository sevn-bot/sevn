"""Exception types for secrets resolution (see ``specs/06-secrets.md`` §6).

Module: sevn.security.secrets.errors
Depends: (none)

Exports:
    SecretsError — base class.
    SecretsBackendError — CLI / IO failure from a concrete backend.
    SecretsStoreCorruptError — AEAD / parse failure for encrypted file store.
    SecretUnresolvedError — ``${SECRET:…}`` could not be resolved on any backend.
    is_encrypted_store_unlock_error — True when encrypted file is *locked* (no key material).
    is_encrypted_store_decrypt_failure — True when key material is *wrong* or the store is corrupt.

Examples:
    >>> issubclass(SecretsBackendError, SecretsError)
    True
    >>> issubclass(SecretsStoreCorruptError, SecretsError)
    True
"""

from __future__ import annotations


class SecretsError(RuntimeError):
    """Base error for the secrets subsystem."""


class SecretsBackendError(SecretsError):
    """A concrete ``SecretsBackend`` failed (CLI exit, missing tool, …)."""


class SecretsStoreCorruptError(SecretsError):
    """Encrypted store exists but fails authenticated decryption or parsing."""


def is_encrypted_store_unlock_error(exc: SecretsStoreCorruptError) -> bool:
    """Return True when the encrypted file backend is *locked* — no key material to even try.

    These states mean the configured key material for this backend is absent, so callers may
    safely skip it and try the next chain entry. This is **distinct** from a *wrong-key* /
    *corrupt* store, which has key material that fails authenticated decryption and must surface
    loudly rather than be silently skipped (see :func:`is_encrypted_store_decrypt_failure`).

    Args:
        exc (SecretsStoreCorruptError): Raised while opening or decrypting the store.

    Returns:
        bool: True when callers should skip this backend and try the next chain entry.

    Examples:
        >>> is_encrypted_store_unlock_error(
        ...     SecretsStoreCorruptError("encrypted store needs passphrase or master_key")
        ... )
        True
        >>> is_encrypted_store_unlock_error(
        ...     SecretsStoreCorruptError("AEAD decrypt failed (corrupt or wrong key)")
        ... )
        False
    """
    msg = str(exc).lower()
    return (
        "needs passphrase" in msg or "missing passphrase" in msg or "needs static master_key" in msg
    )


def is_encrypted_store_decrypt_failure(exc: SecretsStoreCorruptError) -> bool:
    """Return True when the store has key material but fails decryption or parsing.

    Unlike :func:`is_encrypted_store_unlock_error` (a *locked* backend that should be skipped),
    a decrypt failure means the store is present and key material was supplied but is **wrong**
    (e.g. a stale ``SEVN_SECRETS_MASTER_KEY`` shadowing the passphrase) or the file is corrupt.
    Callers must not silently degrade on this — surface it at boot and in ``sevn doctor``.

    Args:
        exc (SecretsStoreCorruptError): Raised while opening or decrypting the store.

    Returns:
        bool: True when the failure indicates wrong key material or a corrupt store.

    Examples:
        >>> is_encrypted_store_decrypt_failure(
        ...     SecretsStoreCorruptError("AEAD decrypt failed (corrupt or wrong key)")
        ... )
        True
        >>> is_encrypted_store_decrypt_failure(
        ...     SecretsStoreCorruptError("encrypted store needs passphrase or master_key")
        ... )
        False
    """
    return not is_encrypted_store_unlock_error(exc)


class SecretUnresolvedError(SecretsError):
    """A ``${SECRET:…}`` reference had no value on any backend."""

    def __init__(self, message: str, *, logical_key: str, source: str) -> None:
        """Attach structured fields for logging (no secret material).

        Args:
            message (str): Human-readable error.
            logical_key (str): Parsed logical key segment.
            source (str): Parsed source namespace segment.

        Examples:
            >>> e = SecretUnresolvedError("x", logical_key="k", source="s")
            >>> e.logical_key
            'k'
        """
        super().__init__(message)
        self.logical_key = logical_key
        self.source = source
