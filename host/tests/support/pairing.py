"""Pairing and direct-handshake helpers (plan 0055 D1-D3).

Everything here is an independent reference: the byte layouts are rebuilt from
D3 with ``cryptography`` so a test never checks the product against itself.
Product imports stay inside functions, so collection works before W2 exists.

Pinned names this module drives (see the 0055 test plan):
- methods ``pairing.start`` (mutating, owner) and ``devices.*``;
- ``sevn.contracts.frames.PairComplete`` (``t = "pair.complete"``) and ``Paired``;
- ``sevn.identity.pairing.complete(frame, identity=...) -> Paired``.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from support.memory import MemoryHost, recv_frame, send_frame, send_req

ALLOWED_HOST = "mac.tailnet.ts.net"
ORIGIN = "wss://mac.tailnet.ts.net"
CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

_CHAL = b"sevn-v1|chal|ws|"
_AUTH = b"sevn-v1|auth|ws|"


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def unb64u(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def raw_public(key: Ed25519PrivateKey) -> bytes:
    return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def fingerprint(pubkey: bytes) -> str:
    """``host_pubkey_fp`` as 0001's identity computes it."""
    return b64u(hashlib.sha256(pubkey).digest()[:16])


def challenge_bytes(nonce: bytes, origin: str) -> bytes:
    return _CHAL + nonce + hashlib.sha256(origin.encode("utf-8")).digest()


def auth_bytes(nonce: bytes, origin: str, host_fp: str) -> bytes:
    return _AUTH + nonce + hashlib.sha256(origin.encode("utf-8")).digest() + host_fp.encode("utf-8")


def sign_auth(key: Ed25519PrivateKey, nonce: bytes, origin: str, host_fp: str) -> str:
    return b64u(key.sign(auth_bytes(nonce, origin, host_fp)))


def verify_host_sig(host_pubkey: bytes, nonce: bytes, origin: str, host_sig: str) -> None:
    """Raises ``cryptography.exceptions.InvalidSignature`` on a bad ``host_sig``."""
    Ed25519PublicKey.from_public_bytes(host_pubkey).verify(
        unb64u(host_sig), challenge_bytes(nonce, origin)
    )


def op_id() -> str:
    return "op_" + secrets.token_hex(8)


@dataclass
class Device:
    key: Ed25519PrivateKey
    id: str = ""
    scope: str = ""

    @property
    def pubkey(self) -> str:
        return b64u(raw_public(self.key))


def new_device() -> Device:
    return Device(key=Ed25519PrivateKey.generate())


def complete_frame(
    ticket: str,
    device: Device,
    *,
    name: str = "Phone",
    platform: str = "web",
) -> dict[str, Any]:
    return {
        "t": "pair.complete",
        "ticket": ticket,
        "device_pubkey_ed25519": device.pubkey,
        "device_name": name,
        "platform": platform,
    }


def register_methods() -> None:
    """Importing ``sevn.http`` registers every protocol method, pairing and devices too."""
    import sevn.http as http

    assert http.__name__ == "sevn.http"


async def owner_client(host: MemoryHost) -> Any:
    """A loopback token session (owner)."""
    from support.memory import handshake

    register_methods()
    client, _session = host.open()
    welcome = await handshake(client, host.token)
    assert welcome["t"] == "welcome", welcome
    return client


async def call(client: Any, method: str, params: dict[str, Any]) -> dict[str, Any]:
    """One request; returns the whole ``res`` frame."""
    req_id = "r_" + secrets.token_hex(4)
    await send_req(client, req_id, method, params)
    while True:
        frame = await recv_frame(client)
        if frame.get("t") == "res" and frame.get("id") == req_id:
            return frame


async def start_pairing(
    client: Any,
    *,
    scope: str | None = None,
    name: str | None = None,
    direct_url: str | None = None,
) -> dict[str, Any]:
    """``pairing.start`` result; fails the test on an error response."""
    params: dict[str, Any] = {"op_id": op_id()}
    if scope is not None:
        params["scope"] = scope
    if name is not None:
        params["name"] = name
    if direct_url is not None:
        params["direct_url"] = direct_url
    res = await call(client, "pairing.start", params)
    assert "r" in res, res
    return res["r"]


async def complete(host: MemoryHost, frame: dict[str, Any]) -> Any:
    """Domain-level ``pair.complete`` (W2): returns the ``Paired`` frame model."""
    from sevn.contracts.frames import PairComplete
    from sevn.identity.pairing import complete as pairing_complete

    parsed = PairComplete.model_validate(frame)
    return await pairing_complete(parsed, identity=host.hub.identity)


async def pair_device(
    host: MemoryHost,
    owner: Any,
    *,
    scope: str = "member",
    name: str = "Phone",
) -> Device:
    """Start a ticket on ``owner`` and complete it for a new device key."""
    started = await start_pairing(owner, scope=scope)
    device = new_device()
    paired = await complete(host, complete_frame(started["ticket"], device, name=name))
    device.id = paired.device_id
    device.scope = paired.scope
    return device


def hello(device_id: str, origin: str | None = ORIGIN) -> dict[str, Any]:
    frame: dict[str, Any] = {
        "t": "hello",
        "proto": [1, 1],
        "client": "web",
        "device": device_id,
        "last_seq": 0,
        "caps": [],
    }
    if origin is not None:
        frame["origin"] = origin
    return frame


async def authenticate(
    host: MemoryHost,
    client: Any,
    device: Device,
    *,
    origin: str = ORIGIN,
) -> dict[str, Any]:
    """D3 handshake from the device side. Returns the frame after ``auth``."""
    await send_frame(client, hello(device.id, origin))
    challenge = await recv_frame(client)
    assert challenge["t"] == "challenge", challenge
    nonce = unb64u(challenge["nonce"])
    identity = host.hub.identity
    verify_host_sig(identity.public_key, nonce, origin, challenge["host_sig"])
    await send_frame(
        client,
        {"t": "auth", "device_sig": sign_auth(device.key, nonce, origin, identity.host_pubkey_fp)},
    )
    return await recv_frame(client)
