"""Mail body PGP decrypt helpers."""

from __future__ import annotations

from pgpy import PGPMessage

from proton_cli.account.keys import use_unlocked_key


def decrypt_body(armored: str, addr_keys: list) -> tuple[str, str]:
    """Decrypt an armored mail body; return ``(plaintext, signature_status)``."""
    if not armored:
        return "", "unverified"
    try:
        message = PGPMessage.from_blob(armored)
    except Exception as exc:
        return f"(decryption failed: parse message: {exc})", "unverified"
    last_err: Exception | None = None
    for key in addr_keys:
        try:
            with use_unlocked_key(key):
                decrypted = key.decrypt(message)
                return str(decrypted.message), "verified"
        except Exception as exc:
            last_err = exc
            continue
    if last_err:
        return f"(decryption failed: {last_err})", "unverified"
    return "(decryption failed: no address key available)", "unverified"
