"""AES-256-GCM helpers for Proton Pass symmetric blobs."""

from __future__ import annotations

import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

TAG_ITEM_CONTENT = b"itemcontent"
TAG_ITEM_KEY = b"itemkey"
TAG_VAULT_CONTENT = b"vaultcontent"

KEY_LEN = 32
IV_LEN = 12


def decrypt(key: bytes, data: bytes, aad: bytes) -> bytes:
    if len(key) != KEY_LEN:
        msg = f"aead: invalid key length {len(key)}"
        raise ValueError(msg)
    if len(data) < IV_LEN:
        msg = "aead: ciphertext too short"
        raise ValueError(msg)
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(data[:IV_LEN], data[IV_LEN:], aad)


def encrypt(key: bytes, plaintext: bytes, aad: bytes) -> bytes:
    if len(key) != KEY_LEN:
        msg = f"aead: invalid key length {len(key)}"
        raise ValueError(msg)
    iv = os.urandom(IV_LEN)
    aesgcm = AESGCM(key)
    ct = aesgcm.encrypt(iv, plaintext, aad)
    return iv + ct


def new_key() -> bytes:
    return os.urandom(KEY_LEN)
