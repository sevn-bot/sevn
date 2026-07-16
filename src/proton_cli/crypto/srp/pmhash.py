"""Proton PMHash — expanded SHA-512."""

from __future__ import annotations

import hashlib


class PMHash:
    digest_size = 256
    name = "PMHash"

    def __init__(self, data: bytes = b"") -> None:
        self._data = data

    def update(self, data: bytes) -> None:
        self._data += data

    def digest(self) -> bytes:
        return (
            hashlib.sha512(self._data + b"\0").digest()
            + hashlib.sha512(self._data + b"\1").digest()
            + hashlib.sha512(self._data + b"\2").digest()
            + hashlib.sha512(self._data + b"\3").digest()
        )

    def hexdigest(self) -> str:
        return self.digest().hex()

    def copy(self) -> PMHash:
        return PMHash(self._data)


def pmhash(data: bytes = b"") -> PMHash:
    return PMHash(data)
