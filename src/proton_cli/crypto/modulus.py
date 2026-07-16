"""SRP modulus clear-signed message parsing and verification."""

from __future__ import annotations

import base64

from pgpy import PGPKey, PGPSignature

MODULUS_PUBKEY = """-----BEGIN PGP PUBLIC KEY BLOCK-----

xjMEXAHLgxYJKwYBBAHaRw8BAQdAFurWXXwjTemqjD7CXjXVyKf0of7n9Ctm
L8v9enkzggHNEnByb3RvbkBzcnAubW9kdWx1c8J3BBAWCgApBQJcAcuDBgsJ
BwgDAgkQNQWFxOlRjyYEFQgKAgMWAgECGQECGwMCHgEAAPGRAP9sauJsW12U
MnTQUZpsbJb53d0Wv55mZIIiJL2XulpWPQD/V6NglBd96lZKBmInSXX/kXat
Sv+y0io+LR8i2+jV+AbOOARcAcuDEgorBgEEAZdVAQUBAQdAeJHUz1c9+KfE
kSIgcBRE3WuXC4oj5a2/U3oASExGDW4DAQgHwmEEGBYIABMFAlwBy4MJEDUF
hcTpUY8mAhsMAAD/XQD8DxNI6E78meodQI+wLsrKLeHn32iLvUqJbVDhfWSU
WO4BAMcm1u02t4VKw++ttECPt+HUgPUq5pqQWe5Q2cW4TMsE
=Y4Mw
-----END PGP PUBLIC KEY BLOCK-----"""


class ModulusError(ValueError):
    pass


def read_clear_signed_message(signed_message: str) -> str:
    """Extract and verify modulus from Proton clear-signed armored block."""
    text = signed_message.replace("\r\n", "\n")
    begin = "-----BEGIN PGP SIGNED MESSAGE-----"
    sig_begin = "-----BEGIN PGP SIGNATURE-----"
    if begin not in text or sig_begin not in text:
        raise ModulusError("invalid clear-signed message")

    _, rest = text.split(begin, 1)
    header, remainder = rest.split("\n\n", 1)
    if "Hash:" not in header:
        raise ModulusError("missing hash header")

    body, sig_part = remainder.split(sig_begin, 1)
    if "-----END PGP SIGNED MESSAGE-----" in body:
        body = body.split("-----END PGP SIGNED MESSAGE-----", 1)[0]
    body = body.rstrip("\n")

    trailing = remainder.split("-----END PGP SIGNATURE-----", 1)
    if len(trailing) > 1 and trailing[1].strip():
        raise ModulusError("extra data after modulus")

    armored_sig = (
        sig_begin
        + sig_part.split("-----END PGP SIGNATURE-----", 1)[0]
        + "-----END PGP SIGNATURE-----"
    )
    key, _ = PGPKey.from_blob(MODULUS_PUBKEY)
    sig = PGPSignature.from_blob(armored_sig)
    with key.unlock(None):
        ok = key.verify(body.encode("utf-8"), sig)
    if not ok:
        raise ModulusError("invalid modulus signature")
    return body.strip()


def decode_modulus(signed_modulus: str) -> bytes:
    clear = read_clear_signed_message(signed_modulus)
    return base64.b64decode(clear)
