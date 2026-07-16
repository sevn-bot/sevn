"""SRP-6a user side for Proton authentication."""

from __future__ import annotations

from proton_cli.crypto.srp.pmhash import PMHash
from proton_cli.crypto.srp.util import (
    PM_VERSION,
    SRP_LEN_BYTES,
    bytes_to_long,
    custom_hash,
    get_random_of_length,
    hash_password,
    long_to_bytes,
)


def get_ng(n_bin: bytes, g_hex: str) -> tuple[int, int]:
    return bytes_to_long(n_bin), int(g_hex, 16)


def hash_k(hash_class: type[PMHash], g: int, modulus: int, width: int) -> int:
    h = hash_class()
    h.update(g.to_bytes(width, "little"))
    h.update(modulus.to_bytes(width, "little"))
    return bytes_to_long(h.digest())


def calculate_x(
    hash_class: type[PMHash], salt: bytes, password: bytes, modulus: int, version: int
) -> int:
    exp = hash_password(hash_class, password, salt, long_to_bytes(modulus, SRP_LEN_BYTES), version)
    return bytes_to_long(exp)


def calculate_client_proof(hash_class: type[PMHash], a: int, b: int, k: bytes) -> bytes:
    h = hash_class()
    h.update(long_to_bytes(a, SRP_LEN_BYTES))
    h.update(long_to_bytes(b, SRP_LEN_BYTES))
    h.update(k)
    return h.digest()


def calculate_server_proof(hash_class: type[PMHash], a: int, m: bytes, k: bytes) -> bytes:
    h = hash_class()
    h.update(long_to_bytes(a, SRP_LEN_BYTES))
    h.update(m)
    h.update(k)
    return h.digest()


class User:
    def __init__(
        self,
        password: str,
        n_bin: bytes,
        g_hex: bytes = b"2",
        bytes_a: bytes | None = None,
        bytes_a_pub: bytes | None = None,
    ) -> None:
        if bytes_a is not None and len(bytes_a) != 32:
            raise ValueError("32 bytes required for bytes_a")
        if not password:
            raise ValueError("Invalid password")

        self.N, self.g = get_ng(n_bin, g_hex.decode())
        self.hash_class = PMHash
        self.k = hash_k(self.hash_class, self.g, self.N, SRP_LEN_BYTES)
        self.p = password.encode()

        if bytes_a is not None:
            self.a = bytes_to_long(bytes_a)
        else:
            self.a = get_random_of_length(32)

        if bytes_a_pub is not None:
            self.A = bytes_to_long(bytes_a_pub)
        else:
            self.A = pow(self.g, self.a, self.N)

        self._authenticated = False
        self.bytes_s: bytes | None = None
        self.B: int | None = None
        self.u: int | None = None
        self.x: int | None = None
        self.v: int | None = None
        self.S: int | None = None
        self.K: bytes | None = None
        self.M: bytes | None = None
        self.expected_server_proof: bytes | None = None

    def authenticated(self) -> bool:
        return self._authenticated

    def get_challenge(self) -> bytes:
        return long_to_bytes(self.A, SRP_LEN_BYTES)

    def process_challenge(
        self,
        bytes_s: bytes,
        bytes_server_challenge: bytes,
        version: int = PM_VERSION,
    ) -> bytes | None:
        self.bytes_s = bytes_s
        self.B = bytes_to_long(bytes_server_challenge)

        if (self.B % self.N) == 0:
            return None

        self.u = custom_hash(self.hash_class, self.A, self.B)
        if self.u == 0:
            return None

        self.x = calculate_x(self.hash_class, self.bytes_s, self.p, self.N, version)
        self.v = pow(self.g, self.x, self.N)
        self.S = pow((self.B - self.k * self.v), (self.a + self.u * self.x), self.N)
        self.K = long_to_bytes(self.S, SRP_LEN_BYTES)
        self.M = calculate_client_proof(self.hash_class, self.A, self.B, self.K)
        self.expected_server_proof = calculate_server_proof(self.hash_class, self.A, self.M, self.K)
        return self.M

    def verify_session(self, server_proof: bytes) -> None:
        if self.expected_server_proof == server_proof:
            self._authenticated = True
