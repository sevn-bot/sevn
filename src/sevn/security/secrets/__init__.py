"""Secrets abstraction for the trust boundary (``specs/06-secrets.md``).

Module: sevn.security.secrets
Depends: sevn.security.secrets.{protocol,chain,cache,factory,backends}

Exports:
    SecretsBackend — protocol.
    SecretsChain — ordered stores.
    ResolvedSecretsCache — TTL cache.
    secrets_chain_from_workspace — build chain from ``sevn.json`` secrets_backend.
    resolve_backend — alias for onboarding sentinel probes.
"""

from __future__ import annotations

from sevn.security.secrets.cache import ResolvedSecretsCache
from sevn.security.secrets.chain import SecretsChain
from sevn.security.secrets.factory import resolve_backend, secrets_chain_from_workspace
from sevn.security.secrets.protocol import SecretsBackend

__all__ = [
    "ResolvedSecretsCache",
    "SecretsBackend",
    "SecretsChain",
    "resolve_backend",
    "secrets_chain_from_workspace",
]
