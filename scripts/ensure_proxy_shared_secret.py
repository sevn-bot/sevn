#!/usr/bin/env python3
"""Generate-once ``SEVN_PROXY_SHARED_SECRET`` file under the operator state root.

Thin CLI / test entry for :mod:`sevn.proxy.bootstrap_secret` (C1.2 / D37).
Compose ``sevn-operator-perms`` also creates the same path when absent; this
module is the authoritative helper for host onboarding and unit tests.

Usage::

    python scripts/ensure_proxy_shared_secret.py [/operator]

Exports the same callables as ``sevn.proxy.bootstrap_secret`` for W1.5 loading.
"""

from __future__ import annotations

from sevn.proxy.bootstrap_secret import (
    OPERATOR_SECRET_UID,
    PROXY_SHARED_SECRET_RELPATH,
    ensure_proxy_shared_secret_file,
    main,
    proxy_shared_secret_path,
    read_proxy_shared_secret_file,
    resolve_effective_proxy_shared_secret,
)

__all__ = [
    "OPERATOR_SECRET_UID",
    "PROXY_SHARED_SECRET_RELPATH",
    "ensure_proxy_shared_secret_file",
    "main",
    "proxy_shared_secret_path",
    "read_proxy_shared_secret_file",
    "resolve_effective_proxy_shared_secret",
]

if __name__ == "__main__":
    raise SystemExit(main())
