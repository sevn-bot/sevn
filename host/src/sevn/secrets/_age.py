# pyright: reportMissingTypeStubs=false, reportMissingImports=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportAttributeAccessIssue=false

"""age encrypt and decrypt. pyrage ships no type stubs."""

from __future__ import annotations

from pyrage import DecryptError, IdentityError
from pyrage import decrypt as age_decrypt
from pyrage import encrypt as age_encrypt
from pyrage.x25519 import Identity, Recipient


def generate_identity() -> str:
    return str(Identity.generate())


def recipient_for(secret: str) -> str:
    try:
        return str(Identity.from_str(secret).to_public())
    except IdentityError as exc:
        raise ValueError("invalid age identity") from exc


def encrypt(plaintext: bytes, recipient: str) -> bytes:
    encrypted = age_encrypt(plaintext, [Recipient.from_str(recipient)])
    if not isinstance(encrypted, bytes):
        raise TypeError("age encrypt returned a non-bytes payload")
    return encrypted


def decrypt(ciphertext: bytes, secret: str) -> bytes:
    try:
        decrypted = age_decrypt(ciphertext, [Identity.from_str(secret)])
    except (DecryptError, IdentityError) as exc:
        raise ValueError("cannot decrypt age secrets") from exc
    if not isinstance(decrypted, bytes):
        raise TypeError("age decrypt returned a non-bytes payload")
    return decrypted
