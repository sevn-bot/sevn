"""D1 optional backend placeholder (`specs/03-storage.md`)."""

from __future__ import annotations

from sevn.storage.d1_backend import D1BackendConfig, D1StorageBackend


def test_d1_backend_ping_configured() -> None:
    backend = D1StorageBackend(D1BackendConfig("acct", "db", "tok"))
    assert backend.ping() == "d1:configured"
