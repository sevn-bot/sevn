"""D3 handshake bytes against ``contracts/vectors/handshake_ws.json`` (plan 0055 W1.2).

The file is the cross-language contract: the Python reference (``sevn.identity.handshake``),
the web signer (``web/src/client/keys.ts``) and later Swift must all match it byte for byte.

Pinned reference API (W2):
- ``challenge_message(nonce: bytes, origin: str) -> bytes``
- ``auth_message(nonce: bytes, origin: str, host_fp: str) -> bytes``
- ``sign_challenge(host_key: Ed25519PrivateKey, nonce, origin) -> str`` (b64url, no padding)
- ``sign_auth(device_key: Ed25519PrivateKey, nonce, origin, host_fp) -> str``
- ``verify_challenge(host_pubkey: bytes, nonce, origin, host_sig: str) -> None``
- ``verify_auth(device_pubkey: bytes, nonce, origin, host_fp, device_sig: str) -> None``
  (both raise ``sevn.identity.handshake.BadSignature`` with message ``"bad signature"``)
- ``fingerprint(pubkey: bytes) -> str``; ``new_nonce() -> bytes`` (32 random bytes)
- ``scripts/gen_vectors.py`` exposes ``render_vectors() -> str``, equal to the file text.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from support.pairing import auth_bytes, b64u, challenge_bytes, fingerprint, raw_public, unb64u
from support.repo import repo_root

VECTORS = repo_root() / "contracts" / "vectors" / "handshake_ws.json"


def _load() -> dict[str, Any]:
    return json.loads(VECTORS.read_text(encoding="utf-8"))


_DOC = _load()
_CASES = _DOC["cases"]
_IDS = [case["name"] for case in _CASES]


def _host_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(_DOC["host"]["seed_hex"]))


def _device_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(_DOC["device"]["seed_hex"]))


def _host_fp() -> str:
    return _DOC["host"]["pubkey_fp"]


# --- the file itself (green now: independent of product code) ---------------------------------


def test_vectors_file_is_self_consistent() -> None:
    """The committed vectors match D3, recomputed with ``cryptography`` only."""
    host, device = _host_key(), _device_key()
    host_pub, device_pub = raw_public(host), raw_public(device)
    assert _DOC["host"]["pubkey"] == b64u(host_pub)
    assert _DOC["device"]["pubkey"] == b64u(device_pub)
    assert _DOC["host"]["pubkey_fp"] == fingerprint(host_pub)
    assert len(_CASES) >= 3
    assert len({case["nonce"] for case in _CASES}) == len(_CASES)
    for case in _CASES:
        nonce = unb64u(case["nonce"])
        assert len(nonce) == 32
        origin = case["origin"]
        assert case["origin_sha256_hex"] == hashlib.sha256(origin.encode()).hexdigest()
        chal = challenge_bytes(nonce, origin)
        auth = auth_bytes(nonce, origin, _host_fp())
        assert case["challenge_message_hex"] == chal.hex()
        assert case["auth_message_hex"] == auth.hex()
        assert case["host_sig"] == b64u(host.sign(chal))
        assert case["device_sig"] == b64u(device.sign(auth))
        Ed25519PublicKey.from_public_bytes(host_pub).verify(unb64u(case["host_sig"]), chal)
        Ed25519PublicKey.from_public_bytes(device_pub).verify(unb64u(case["device_sig"]), auth)


def test_vectors_seeds_are_marked_test_only() -> None:
    assert "test-only" in _DOC["description"].lower()
    assert bytes.fromhex(_DOC["host"]["seed_hex"]).startswith(b"sevn-test-vector-")
    assert bytes.fromhex(_DOC["device"]["seed_hex"]).startswith(b"sevn-test-vector-")


def test_a_changed_origin_or_nonce_breaks_the_vector_signatures() -> None:
    """Sanity for the negative cases below: the reference rejects tampering too."""
    host_pub = raw_public(_host_key())
    case = _CASES[0]
    nonce = unb64u(case["nonce"])
    sig = unb64u(case["host_sig"])
    verifier = Ed25519PublicKey.from_public_bytes(host_pub)
    with pytest.raises(InvalidSignature):
        verifier.verify(sig, challenge_bytes(nonce, case["origin"] + ":443"))
    with pytest.raises(InvalidSignature):
        verifier.verify(sig, challenge_bytes(bytes(32), case["origin"]))


# --- sevn.identity.handshake (W2) -------------------------------------------------------------


@pytest.mark.parametrize("case", _CASES, ids=_IDS)
def test_messages_match_vectors(case: dict[str, Any]) -> None:
    from sevn.identity import handshake

    nonce = unb64u(case["nonce"])
    assert handshake.challenge_message(nonce, case["origin"]).hex() == case["challenge_message_hex"]
    assert (
        handshake.auth_message(nonce, case["origin"], _host_fp()).hex() == case["auth_message_hex"]
    )


@pytest.mark.parametrize("case", _CASES, ids=_IDS)
def test_signatures_match_vectors_byte_for_byte(case: dict[str, Any]) -> None:
    from sevn.identity import handshake

    nonce = unb64u(case["nonce"])
    assert handshake.sign_challenge(_host_key(), nonce, case["origin"]) == case["host_sig"]
    assert (
        handshake.sign_auth(_device_key(), nonce, case["origin"], _host_fp()) == case["device_sig"]
    )


@pytest.mark.parametrize("case", _CASES, ids=_IDS)
def test_vector_signatures_verify(case: dict[str, Any]) -> None:
    from sevn.identity import handshake

    nonce = unb64u(case["nonce"])
    host_pub = unb64u(_DOC["host"]["pubkey"])
    device_pub = unb64u(_DOC["device"]["pubkey"])
    handshake.verify_challenge(host_pub, nonce, case["origin"], case["host_sig"])
    handshake.verify_auth(device_pub, nonce, case["origin"], _host_fp(), case["device_sig"])


def _tamper_origin(case: dict[str, Any]) -> tuple[bytes, str, str]:
    return unb64u(case["nonce"]), "wss://evil.example", _host_fp()


def _tamper_nonce(case: dict[str, Any]) -> tuple[bytes, str, str]:
    nonce = bytearray(unb64u(case["nonce"]))
    nonce[0] ^= 0x01
    return bytes(nonce), case["origin"], _host_fp()


def _tamper_fp(case: dict[str, Any]) -> tuple[bytes, str, str]:
    return unb64u(case["nonce"]), case["origin"], "AAAAAAAAAAAAAAAAAAAAAA"


@pytest.mark.parametrize("case", _CASES, ids=_IDS)
@pytest.mark.parametrize(
    "tamper", [_tamper_origin, _tamper_nonce], ids=["changed-origin", "changed-nonce"]
)
def test_changed_origin_or_nonce_fails_challenge(case: dict[str, Any], tamper: Any) -> None:
    from sevn.identity import handshake

    nonce, origin, _fp = tamper(case)
    with pytest.raises(handshake.BadSignature) as exc:
        handshake.verify_challenge(unb64u(_DOC["host"]["pubkey"]), nonce, origin, case["host_sig"])
    assert str(exc.value) == "bad signature"


@pytest.mark.parametrize("case", _CASES, ids=_IDS)
@pytest.mark.parametrize(
    "tamper",
    [_tamper_origin, _tamper_nonce, _tamper_fp],
    ids=["changed-origin", "changed-nonce", "changed-host-fp"],
)
def test_changed_origin_nonce_or_host_fails_auth(case: dict[str, Any], tamper: Any) -> None:
    from sevn.identity import handshake

    nonce, origin, host_fp = tamper(case)
    with pytest.raises(handshake.BadSignature) as exc:
        handshake.verify_auth(
            unb64u(_DOC["device"]["pubkey"]), nonce, origin, host_fp, case["device_sig"]
        )
    assert str(exc.value) == "bad signature"


def test_wrong_key_fails_and_garbage_signature_fails() -> None:
    from sevn.identity import handshake

    case = _CASES[0]
    nonce = unb64u(case["nonce"])
    other = raw_public(Ed25519PrivateKey.generate())
    with pytest.raises(handshake.BadSignature):
        handshake.verify_challenge(other, nonce, case["origin"], case["host_sig"])
    with pytest.raises(handshake.BadSignature):
        handshake.verify_challenge(
            unb64u(_DOC["host"]["pubkey"]), nonce, case["origin"], "not-a-signature"
        )


def test_fingerprint_and_nonce_helpers() -> None:
    from sevn.identity import handshake

    assert handshake.fingerprint(unb64u(_DOC["host"]["pubkey"])) == _DOC["host"]["pubkey_fp"]
    first, second = handshake.new_nonce(), handshake.new_nonce()
    assert len(first) == 32 and len(second) == 32
    assert first != second


def test_host_identity_from_vector_seed_matches_host_id() -> None:
    """``load_or_create`` derives the vector's ``host_id`` and fingerprint from the seed."""
    from cryptography.hazmat.primitives import serialization
    from sevn.identity import load_or_create

    pem = (
        _host_key()
        .private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        .decode("ascii")
    )

    class _Store:
        def get(self, _name: str) -> str:
            return pem

        def set(self, _name: str, _value: str) -> None:
            raise AssertionError("the stored key must be reused")

    identity = load_or_create(_Store())
    assert identity.host_id == _DOC["host"]["host_id"]
    assert identity.host_pubkey_fp == _DOC["host"]["pubkey_fp"]


def test_gen_vectors_reproduces_the_committed_file() -> None:
    script = repo_root() / "scripts" / "gen_vectors.py"
    spec = importlib.util.spec_from_file_location("sevn_gen_vectors", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.render_vectors() == Path(VECTORS).read_text(encoding="utf-8")
