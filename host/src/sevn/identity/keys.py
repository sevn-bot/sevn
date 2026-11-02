"""Create or load the host Ed25519 identity.

The private key lives in the secrets backend (or ``keys/host.pem`` when the
backend is read-only). ``HostIdentity`` keeps the loaded key in memory so the
host can sign handshake challenges; it is never part of ``repr``, equality or
any serialised form, and nothing here writes it anywhere else.
"""

from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass, field
from typing import Protocol

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sevn.paths import Paths
from sevn.secrets.errors import SecretBackendReadOnly, SecretNotFound
from sevn.secrets.registry import register

_NAME = "host/identity"
_LOCAL_FILE = "host.pem"


class SecretStore(Protocol):
    def get(self, name: str) -> str: ...

    def set(self, name: str, value: str) -> None: ...


@dataclass(frozen=True, slots=True)
class HostIdentity:
    public_key: bytes
    host_id: str
    host_pubkey_fp: str
    _key: Ed25519PrivateKey | None = field(default=None, repr=False, compare=False)

    def sign(self, message: bytes) -> bytes:
        """Ed25519 signature over ``message`` with the host key (64 bytes)."""
        if self._key is None:
            raise RuntimeError("host identity has no signing key")
        return self._key.sign(message)


def load_or_create(backend: SecretStore) -> HostIdentity:
    try:
        stored = backend.get(_NAME)
    except SecretNotFound:
        stored = ""
    if stored:
        return _from_pem(stored)
    private = Ed25519PrivateKey.generate()
    pem = _pem(private)
    try:
        backend.set(_NAME, pem)
    except SecretBackendReadOnly:
        # `host/identity` is not a legal env var name, so the read-only backend
        # cannot hold it. Keep the key on disk instead of aborting startup.
        existing = _read_local_pem()
        if existing:
            return _from_pem(existing)
        _write_local_pem(pem)
    return _from_private(private)


def _read_local_pem() -> str:
    path = Paths.from_env().keys / _LOCAL_FILE
    if not path.is_file():
        return ""
    pem = path.read_text(encoding="ascii").strip()
    if pem:
        register(_NAME, pem)
    return pem


def _write_local_pem(pem: str) -> None:
    path = Paths.from_env().keys / _LOCAL_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = pem if pem.endswith("\n") else pem + "\n"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(descriptor, payload.encode("ascii"))
    finally:
        os.close(descriptor)
    os.chmod(path, 0o600)
    register(_NAME, pem.strip())


def _pem(private: Ed25519PrivateKey) -> str:
    return private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")


def _from_private(private: Ed25519PrivateKey) -> HostIdentity:
    public_key = private.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    return HostIdentity(
        public_key=public_key,
        host_id=host_id_for(public_key),
        host_pubkey_fp=fingerprint(public_key),
        _key=private,
    )


def _from_pem(pem: str) -> HostIdentity:
    loaded = serialization.load_pem_private_key(pem.encode("ascii"), password=None)
    if not isinstance(loaded, Ed25519PrivateKey):
        raise ValueError("host/identity is not an Ed25519 private key")
    return _from_private(loaded)


def host_id_for(pubkey: bytes) -> str:
    """``host_`` plus 26 lowercase base32 characters of SHA-256(pubkey)."""
    encoded = base64.b32encode(hashlib.sha256(pubkey).digest()).decode("ascii")
    return "host_" + encoded.rstrip("=").lower()[:26]


def fingerprint(pubkey: bytes) -> str:
    """``host_pubkey_fp``: base64url (no padding) of the first 16 bytes of SHA-256."""
    digest = hashlib.sha256(pubkey).digest()
    return base64.urlsafe_b64encode(digest[:16]).decode("ascii").rstrip("=")
