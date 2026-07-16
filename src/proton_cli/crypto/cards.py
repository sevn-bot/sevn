"""Proton signed/encrypted card helpers (Contacts, Calendar)."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

from pgpy import PGPKey, PGPMessage

from proton_cli.service.drive import blocks

CARD_CLEAR = 0
CARD_ENCRYPTED = 1
CARD_SIGNED = 2
CARD_ENCRYPTED_SIGNED = 3


@dataclass
class Card:
    type: int
    data: str
    signature: str = ""


def card_from_api(raw: dict[str, Any]) -> Card:
    return Card(
        type=int(raw.get("Type", 0) or 0),
        data=str(raw.get("Data", "")),
        signature=str(raw.get("Signature", "")),
    )


def decrypt_cards(
    cards: list[dict[str, Any]],
    decryption_key: PGPKey,
    verification_key: PGPKey,
    key_packet: bytes | None = None,
) -> list[str]:
    out: list[str] = []
    for raw in cards:
        card = card_from_api(raw)
        if card.type == CARD_CLEAR or card.type == CARD_SIGNED:
            out.append(card.data)
        elif card.type in (CARD_ENCRYPTED, CARD_ENCRYPTED_SIGNED):
            plain = _decrypt_card_data(card.data, key_packet, decryption_key)
            out.append(plain)
        else:
            out.append(card.data)
    return out


def sign_card(data: str, signing_key: PGPKey) -> dict[str, Any]:
    with signing_key.unlock(None):
        sig = signing_key.sign(PGPMessage.new(data))
    return {"Type": CARD_SIGNED, "Data": data, "Signature": str(sig)}


def encrypt_and_sign_card(data: str, encryption_key: PGPKey, signing_key: PGPKey) -> dict[str, Any]:
    msg = PGPMessage.new(data)
    with encryption_key.unlock(None):
        enc = encryption_key.encrypt(msg)
    with signing_key.unlock(None):
        sig = signing_key.sign(msg)
    return {"Type": CARD_ENCRYPTED_SIGNED, "Data": str(enc), "Signature": str(sig)}


def encrypt_and_sign_card_split(
    signed_data: str,
    encrypted_data: str,
    encryption_key: PGPKey,
    signing_key: PGPKey,
    existing_key_packet_b64: str = "",
) -> tuple[dict[str, Any], dict[str, Any], str, blocks.SessionKey]:
    """Produce signed + encrypted calendar cards and optional shared key packet."""
    signed = sign_card(signed_data, signing_key)
    enc_msg = PGPMessage.new(encrypted_data)
    if existing_key_packet_b64:
        key_packet = base64.b64decode(existing_key_packet_b64)
        session_key = blocks.decrypt_session_key_packet(key_packet, encryption_key)
        data_packet = blocks.encrypt_data_packet(encrypted_data.encode(), session_key)
        key_packet_b64 = ""
    else:
        session_key = blocks.make_session_key()
        key_packet = blocks.encrypt_session_key_packet(encryption_key, session_key)
        data_packet = blocks.encrypt_data_packet(encrypted_data.encode(), session_key)
        key_packet_b64 = base64.b64encode(key_packet).decode()
    with signing_key.unlock(None):
        sig = signing_key.sign(enc_msg)
    encrypted = {
        "Type": CARD_ENCRYPTED_SIGNED,
        "Data": base64.b64encode(data_packet).decode(),
        "Signature": str(sig),
    }
    return signed, encrypted, key_packet_b64, session_key


def encrypt_part_with_session_key(
    data: str,
    session_key: blocks.SessionKey,
    signing_key: PGPKey,
) -> dict[str, Any]:
    msg = PGPMessage.new(data)
    data_packet = blocks.encrypt_data_packet(data.encode(), session_key)
    with signing_key.unlock(None):
        sig = signing_key.sign(msg)
    return {
        "Type": CARD_ENCRYPTED_SIGNED,
        "Data": base64.b64encode(data_packet).decode(),
        "Signature": str(sig),
    }


def _decrypt_card_data(data: str, key_packet: bytes | None, key: PGPKey) -> str:
    if key_packet is not None:
        try:
            raw = base64.b64decode(data)
        except Exception:
            msg = PGPMessage.from_blob(data)
            with key.unlock(None):
                dec = key.decrypt(msg)
            return _as_text(dec.message)
        sk = blocks.decrypt_session_key_packet(key_packet, key)
        body = blocks._packet_body(raw) if raw and raw[0] in (0xC0, 0xD2, 0xD0) else raw
        if body and body[0] == 1:
            plain = blocks.decrypt_block(raw if raw[0] in (0xC0, 0xD2) else _wrap_seipd(body), sk)
            return plain.decode("utf-8", errors="replace")
        with key.unlock(None):
            msg = PGPMessage.from_blob(data)
            dec = key.decrypt(msg)
        return _as_text(dec.message)
    msg = PGPMessage.from_blob(data)
    with key.unlock(None):
        dec = key.decrypt(msg)
    return _as_text(dec.message)


def _wrap_seipd(body: bytes) -> bytes:
    return bytes([0xD2]) + bytes([len(body)]) + body


def _as_text(value: object) -> str:
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).decode("utf-8", errors="replace")
    return str(value)
