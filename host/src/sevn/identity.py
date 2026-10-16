"""Create or load the host Ed25519 identity."""

from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass
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
        host_id=_host_id(public_key),
        host_pubkey_fp=_fingerprint(public_key),
    )


def _from_pem(pem: str) -> HostIdentity:
    loaded = serialization.load_pem_private_key(pem.encode("ascii"), password=None)
    if not isinstance(loaded, Ed25519PrivateKey):
        raise ValueError("host/identity is not an Ed25519 private key")
    return _from_private(loaded)


def _host_id(pubkey: bytes) -> str:
    encoded = base64.b32encode(hashlib.sha256(pubkey).digest()).decode("ascii")
    return "host_" + encoded.rstrip("=").lower()[:26]


def _fingerprint(pubkey: bytes) -> str:
    digest = hashlib.sha256(pubkey).digest()
    return base64.urlsafe_b64encode(digest[:16]).decode("ascii").rstrip("=")
