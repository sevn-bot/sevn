"""Direct-transport handshake bytes (plan 0055 D3, spec D30). The Python reference.

``challenge_message = "sevn-v1|chal|ws|" || nonce || SHA-256(origin)`` is signed by the host;
``auth_message = "sevn-v1|auth|ws|" || nonce || SHA-256(origin) || host_pubkey_fp`` is signed
by the device. Nonces, public keys and signatures travel as base64url without padding.
``contracts/vectors/handshake_ws.json`` pins the exact bytes for every client.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import secrets
from collections.abc import Callable

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from sevn.contracts.errors import ProtocolError
from sevn.identity.keys import fingerprint as _key_fingerprint

NONCE_BYTES = 32
_CHAL = b"sevn-v1|chal|ws|"
_AUTH = b"sevn-v1|auth|ws|"
_SIG_BYTES = 64


class BadSignature(ProtocolError):
    """A handshake signature does not verify (or does not decode)."""

    def __init__(self) -> None:
        super().__init__("unauthorized", "bad signature")


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def unb64u(text: str) -> bytes:
    """Strict base64url (no padding) decode; raises ``ValueError`` on bad input."""
    try:
        return base64.b64decode(text + "=" * (-len(text) % 4), altchars=b"-_", validate=True)
    except binascii.Error as exc:
        raise ValueError("invalid base64url") from exc


def new_nonce() -> bytes:
    """32 random bytes. Sessions call this as a module attribute."""
    return secrets.token_bytes(NONCE_BYTES)


def fingerprint(pubkey: bytes) -> str:
    """``host_pubkey_fp`` (the ``k=`` value of a pairing URI)."""
    return _key_fingerprint(pubkey)


def challenge_message(nonce: bytes, origin: str) -> bytes:
    return _CHAL + _checked(nonce) + _origin_digest(origin)


def auth_message(nonce: bytes, origin: str, host_fp: str) -> bytes:
    return _AUTH + _checked(nonce) + _origin_digest(origin) + host_fp.encode("utf-8")


def sign_challenge(host_key: Ed25519PrivateKey, nonce: bytes, origin: str) -> str:
    return b64u(host_key.sign(challenge_message(nonce, origin)))


def sign_auth(device_key: Ed25519PrivateKey, nonce: bytes, origin: str, host_fp: str) -> str:
    return b64u(device_key.sign(auth_message(nonce, origin, host_fp)))


def verify_challenge(host_pubkey: bytes, nonce: bytes, origin: str, host_sig: str) -> None:
    _verify(host_pubkey, host_sig, lambda: challenge_message(nonce, origin))


def verify_auth(
    device_pubkey: bytes, nonce: bytes, origin: str, host_fp: str, device_sig: str
) -> None:
    _verify(device_pubkey, device_sig, lambda: auth_message(nonce, origin, host_fp))


def _verify(pubkey: bytes, signature: str, message: Callable[[], bytes]) -> None:
    try:
        raw = unb64u(signature)
        if len(raw) != _SIG_BYTES:
            raise BadSignature
        Ed25519PublicKey.from_public_bytes(pubkey).verify(raw, message())
    except (InvalidSignature, ValueError) as exc:
        raise BadSignature from exc


def _checked(nonce: bytes) -> bytes:
    if len(nonce) != NONCE_BYTES:
        raise ValueError(f"nonce must be {NONCE_BYTES} bytes")
    return nonce


def _origin_digest(origin: str) -> bytes:
    return hashlib.sha256(origin.encode("utf-8")).digest()
