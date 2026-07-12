"""Configuration loading errors.

Module: sevn.config.errors
Depends: (none)

Exports:
    SevnConfigError — base class for workspace/process config failures.
    SevnJsonNotFoundError — no ``sevn.json`` discovered on search path.
    UnsupportedSchemaVersionError — ``schema_version`` not supported by this binary.
    TriagerUnavailable — main model / triager slot missing or unresolvable.

Examples:
    >>> issubclass(SevnJsonNotFoundError, SevnConfigError)
    True
"""

from __future__ import annotations


class SevnConfigError(Exception):
    """Base class for configuration resolution and validation failures."""


class SevnJsonNotFoundError(SevnConfigError):
    """Raised when no workspace config file can be located."""


class UnsupportedSchemaVersionError(SevnConfigError):
    """Raised when ``sevn.json`` references an unknown ``schema_version``."""


class TriagerUnavailable(Exception):
    """Main model / triager slot missing or unresolvable (`specs/13-rlm-triager.md` §6).

    Lives in :mod:`sevn.config.errors` so model-resolution helpers can raise without
    forcing an ``sevn.proxy`` → ``sevn.agent`` import edge. Re-exported from
    :mod:`sevn.agent.triager.errors` for backwards compatibility.
    """
