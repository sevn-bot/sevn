"""Proxy-side credential ref expansion (``specs/06-secrets.md`` §2.2, §4.1).

Module: sevn.proxy.secrets_resolve
Depends: sevn.security.secrets.value_expand

Re-exports the async expanders implemented in ``sevn.security.secrets.value_expand``
so callers can keep importing from ``sevn.proxy.secrets_resolve`` while layering
ordering rules live beside the core secret stack (``specs/02 §2.4 env → secret``).
"""

from __future__ import annotations

from sevn.security.secrets.value_expand import (
    EnvUnresolvedError,
    expand_env_refs,
    expand_refs_env_then_secret,
    expand_secret_refs,
)

__all__ = [
    "EnvUnresolvedError",
    "expand_env_refs",
    "expand_refs_env_then_secret",
    "expand_secret_refs",
]
