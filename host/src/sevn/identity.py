"""Create or load the host Ed25519 identity."""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from typing import Protocol

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sevn.secrets.errors import SecretNotFound

_NAME = "host/identity"


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
    if not stored:
        private = Ed25519PrivateKey.generate()
        backend.set(_NAME, _pem(private))
        return _from_private(private)
    return _from_pem(stored)


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
