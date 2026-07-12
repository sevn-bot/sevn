"""Storage layer exceptions.

Module: sevn.storage.errors

Exports:
    StorageError — non-specific persistence failure.
    MigrationError — migration DDL or bookkeeping failed.

Examples:
    >>> issubclass(MigrationError, StorageError)
    True
"""

from __future__ import annotations


class StorageError(RuntimeError):
    """Base class for workspace database errors."""


class MigrationError(StorageError):
    """Raised when a versioned migration cannot be applied cleanly."""
