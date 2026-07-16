"""Session local key wrap/unwrap via server-held client key."""

from __future__ import annotations

import base64

from proton_cli.crypto import aead
from proton_cli.proton.client import Client, Request

LOCAL_KEY_PATH = "/auth/v4/sessions/local/key"
AAD = b"proton-cli.session-key"


def generate() -> bytes:
    return aead.new_key()


def put(client: Client, key: bytes) -> None:
    client.decode(
        Request(
            method="PUT",
            path=LOCAL_KEY_PATH,
            body={"Key": base64.b64encode(key).decode()},
        )
    )


def get(client: Client) -> bytes:
    payload: dict = {}
    client.decode(Request(method="GET", path=LOCAL_KEY_PATH), payload)
    encoded = str(payload.get("ClientKey", ""))
    if not encoded:
        raise ValueError("server returned no client key")
    return base64.b64decode(encoded)


def wrap(salted_key_pass: str, key: bytes) -> str:
    ct = aead.encrypt(key, salted_key_pass.encode(), AAD)
    return base64.b64encode(ct).decode()


def unwrap(blob: str, key: bytes) -> str:
    raw = base64.b64decode(blob)
    pt = aead.decrypt(key, raw, AAD)
    return pt.decode()
