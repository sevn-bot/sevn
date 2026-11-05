"""Write contracts/vectors/handshake_ws.json from the D3 reference (plan 0055).

The seeds and nonces are fixed ASCII strings, so the output is deterministic.
They are test-only: never use these keys anywhere else.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sevn.identity import handshake
from sevn.identity.keys import host_id_for

_ROOT = Path(__file__).resolve().parents[1]
_OUT = _ROOT / "contracts" / "vectors" / "handshake_ws.json"

_HOST_SEED = b"sevn-test-vector-host-seed-00001"
_DEVICE_SEED = b"sevn-test-vector-device-seed-001"
_CASES: tuple[tuple[str, bytes, str], ...] = (
    ("tailscale_serve_https", b"sevn-test-vector-nonce-000000001", "wss://mac.tailnet.ts.net"),
    ("overlay_ipv4_plain_ws", b"sevn-test-vector-nonce-000000002", "ws://100.101.102.103:8787"),
    ("overlay_ipv6_port", b"sevn-test-vector-nonce-000000003", "wss://[fd7a:115c:a1e0::1]:8443"),
)
_LAYOUT = {
    "auth_message": (
        "utf8('sevn-v1|auth|ws|') || nonce(32 raw bytes) || sha256(utf8(origin))"
        " || utf8(host_pubkey_fp)"
    ),
    "challenge_message": "utf8('sevn-v1|chal|ws|') || nonce(32 raw bytes) || sha256(utf8(origin))",
    "encoding": (
        "nonce, public keys and signatures are base64url without padding;"
        " seeds and messages are lowercase hex"
    ),
    "host_id": "'host_' + lowercase(base32-nopad(sha256(host_pubkey)))[:26]",
    "host_pubkey_fp": "base64url-nopad(sha256(host_pubkey)[:16])",
    "signature": "Ed25519 (RFC 8032), 64 bytes",
}
_DESCRIPTION = (
    "D3 direct-transport handshake vectors (plan 0055)."
    " Test-only keys: never use these seeds anywhere else."
)


def _raw_public(key: Ed25519PrivateKey) -> bytes:
    return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def build_vectors() -> dict[str, object]:
    host = Ed25519PrivateKey.from_private_bytes(_HOST_SEED)
    device = Ed25519PrivateKey.from_private_bytes(_DEVICE_SEED)
    host_pub = _raw_public(host)
    host_fp = handshake.fingerprint(host_pub)
    cases: list[dict[str, str]] = []
    for name, nonce, origin in _CASES:
        cases.append(
            {
                "auth_message_hex": handshake.auth_message(nonce, origin, host_fp).hex(),
                "challenge_message_hex": handshake.challenge_message(nonce, origin).hex(),
                "device_sig": handshake.sign_auth(device, nonce, origin, host_fp),
                "host_sig": handshake.sign_challenge(host, nonce, origin),
                "name": name,
                "nonce": handshake.b64u(nonce),
                "origin": origin,
                "origin_sha256_hex": hashlib.sha256(origin.encode("utf-8")).hexdigest(),
            }
        )
    return {
        "cases": cases,
        "description": _DESCRIPTION,
        "device": {
            "pubkey": handshake.b64u(_raw_public(device)),
            "seed_hex": _DEVICE_SEED.hex(),
        },
        "host": {
            "host_id": host_id_for(host_pub),
            "pubkey": handshake.b64u(host_pub),
            "pubkey_fp": host_fp,
            "seed_hex": _HOST_SEED.hex(),
        },
        "layout": _LAYOUT,
        "version": 1,
    }


def render_vectors() -> str:
    """Canonical ``handshake_ws.json`` body, including the trailing newline."""
    return json.dumps(build_vectors(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Write the direct handshake test vectors")
    parser.add_argument("--out", type=Path, default=_OUT)
    args = parser.parse_args()
    out = args.out if isinstance(args.out, Path) else Path(str(args.out))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_vectors(), encoding="utf-8")


if __name__ == "__main__":
    main()
