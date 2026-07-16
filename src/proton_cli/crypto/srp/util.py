"""SRP helpers and Proton mailbox password hashing."""

from __future__ import annotations

import base64
import os

import bcrypt

from proton_cli.crypto.srp.pmhash import PMHash

PM_VERSION = 4
SRP_LEN_BYTES = 256
SALT_LEN_BYTES = 10


def bcrypt_b64_encode(data: bytes) -> bytes:
    bcrypt_base64 = b"./ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    std_base64chars = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
    encoded = base64.b64encode(data)
    return encoded.translate(bytes.maketrans(std_base64chars, bcrypt_base64))


def hash_password_3(hash_class: type[PMHash], password: bytes, salt: bytes, modulus: bytes) -> bytes:
    salt = (salt + b"proton")[:16]
    salt = bcrypt_b64_encode(salt)[:22]
    hashed = bcrypt.hashpw(password, b"$2y$10$" + salt)
    return hash_class(hashed + modulus).digest()


def hash_password(
    hash_class: type[PMHash],
    password: bytes,
    salt: bytes,
    modulus: bytes,
    version: int,
) -> bytes:
    if version in (3, 4):
        return hash_password_3(hash_class, password, salt, modulus)
    msg = f"Unsupported auth version {version}"
    raise ValueError(msg)


def bytes_to_long(data: bytes) -> int:
    return int.from_bytes(data, "little")


def long_to_bytes(value: int, num_bytes: int) -> bytes:
    return value.to_bytes(num_bytes, "little")


def get_random(nbytes: int) -> int:
    return bytes_to_long(os.urandom(nbytes))


def get_random_of_length(nbytes: int) -> int:
    offset = (nbytes * 8) - 1
    return get_random(nbytes) | (1 << offset)


def custom_hash(hash_class: type[PMHash], *args: object) -> int:
    h = hash_class()
    for item in args:
        if item is None:
            continue
        if isinstance(item, int):
            data = long_to_bytes(item, SRP_LEN_BYTES)
        else:
            data = bytes(item)
        h.update(data)
    return bytes_to_long(h.digest())


def mailbox_password(password: bytes, salt: bytes) -> bytes:
    """Return full bcrypt hash bytes for mailbox password derivation."""
    encoded_salt = bcrypt_b64_encode(salt)
    salt_part = bcrypt_b64_encode((salt + b"proton")[:16])[:22]
    return bcrypt.hashpw(password, b"$2y$10$" + salt_part)


def mailbox_password_secret(password: bytes, salt_b64: str) -> str:
    """Derive the 31-char salted key password secret used to unlock PGP keys."""
    salt = base64.b64decode(salt_b64)
    hashed = mailbox_password(password, salt)
    return hashed[-31:].decode("ascii")
