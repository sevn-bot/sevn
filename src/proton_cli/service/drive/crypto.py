"""Drive node-key crypto (names, passphrases, hash keys)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
from dataclasses import dataclass
from typing import Any

from pgpy import PGPKey, PGPMessage

from proton_cli.account.keys import persist_unlock, use_unlocked_key


@dataclass
class Link:
    link_id: str = ""
    parent_link_id: str = ""
    type: int = 0
    size: int = 0
    name: str = ""
    mime_type: str = ""
    node_key: str = ""
    node_passphrase: str = ""
    node_passphrase_signature: str = ""
    signature_email: str = ""
    create_time: int = 0
    modify_time: int = 0
    folder_properties: dict[str, Any] | None = None
    album_properties: dict[str, Any] | None = None
    file_properties: dict[str, Any] | None = None


@dataclass
class DriveContext:
    share_id: str
    volume_id: str
    root_link_id: str
    addr_id: str
    addr_email: str
    share_key: PGPKey
    addr_key: PGPKey


@dataclass
class Resolved:
    share_id: str
    link_id: str
    parent_key: PGPKey
    node_key: PGPKey
    name: str
    is_folder: bool


def link_from_api(raw: dict[str, Any]) -> Link:
    return Link(
        link_id=str(raw.get("LinkID", "")),
        parent_link_id=str(raw.get("ParentLinkID", "")),
        type=int(raw.get("Type", 0) or 0),
        size=int(raw.get("Size", 0) or 0),
        name=str(raw.get("Name", "")),
        mime_type=str(raw.get("MIMEType", "")),
        node_key=str(raw.get("NodeKey", "")),
        node_passphrase=str(raw.get("NodePassphrase", "")),
        node_passphrase_signature=str(raw.get("NodePassphraseSignature", "")),
        signature_email=str(raw.get("SignatureEmail", "")),
        create_time=int(raw.get("CreateTime", 0) or 0),
        modify_time=int(raw.get("ModifyTime", 0) or 0),
        folder_properties=raw.get("FolderProperties"),
        album_properties=raw.get("AlbumProperties"),
        file_properties=raw.get("FileProperties"),
    )


def unlock_share(
    unlocked_addrs: dict[str, list[PGPKey]],
    addresses: list[Any],
    share_payload: dict[str, Any],
) -> tuple[PGPKey, str, str]:
    address_id = str(share_payload.get("AddressID", ""))
    addr_keys = unlocked_addrs.get(address_id)
    if not addr_keys:
        raise ValueError(f"no key ring for address {address_id}")
    addr_key = addr_keys[0]
    addr_email = ""
    for addr in addresses:
        if addr.id == address_id:
            addr_email = addr.email
            break
    enc = PGPMessage.from_blob(str(share_payload.get("Passphrase", "")))
    with use_unlocked_key(addr_key):
        dec = addr_key.decrypt(enc)
    phrase = _message_bytes(dec.message)
    locked_share, _ = PGPKey.from_blob(str(share_payload.get("Key", "")))
    return persist_unlock(locked_share, phrase), address_id, addr_email


def unlock_node(link: Link, parent_key: PGPKey, addr_key: PGPKey | None = None) -> PGPKey:
    enc = PGPMessage.from_blob(link.node_passphrase)
    with use_unlocked_key(parent_key):
        dec = parent_key.decrypt(enc)
    phrase = _message_bytes(dec.message)
    locked, _ = PGPKey.from_blob(link.node_key)
    return persist_unlock(locked, phrase)


def decrypt_name(enc_name: str, parent_key: PGPKey) -> str:
    msg = PGPMessage.from_blob(enc_name)
    with use_unlocked_key(parent_key):
        dec = parent_key.decrypt(msg)
    text = dec.message
    return text.decode() if isinstance(text, (bytes, bytearray)) else str(text)


def encrypt_name(name: str, parent_key: PGPKey, addr_key: PGPKey) -> str:
    msg = PGPMessage.new(name)
    pub = parent_key.pubkey
    with use_unlocked_key(parent_key), use_unlocked_key(addr_key):
        enc = pub.encrypt(msg)
    return str(enc)


def hash_key_of(link: Link, node_key: PGPKey) -> bytes:
    armored = ""
    if link.album_properties and link.album_properties.get("NodeHashKey"):
        armored = str(link.album_properties["NodeHashKey"])
    elif link.folder_properties and link.folder_properties.get("NodeHashKey"):
        armored = str(link.folder_properties["NodeHashKey"])
    if not armored:
        raise ValueError("link has no hash key")
    msg = PGPMessage.from_blob(armored)
    with use_unlocked_key(node_key):
        dec = node_key.decrypt(msg)
    return bytes(dec.message)


def lookup_hash(name: str, hash_key: bytes) -> str:
    mac = hmac.new(hash_key, name.encode(), hashlib.sha256)
    return mac.hexdigest()


def gen_node_keys(parent_key: PGPKey, addr_key: PGPKey) -> tuple[str, str, str, PGPKey, bytes]:
    """Return armored node key, passphrase packet, signature, unlocked private key, phrase."""
    phrase_raw = os.urandom(32)
    phrase_text = base64.b64encode(phrase_raw).decode()
    locked_key, armored_key, lock_pass = generate_node_key_with_passphrase(phrase_text.encode())
    msg = PGPMessage.new(phrase_text)
    with use_unlocked_key(parent_key):
        arm_pass = str(parent_key.pubkey.encrypt(msg))
    with use_unlocked_key(addr_key):
        sig = addr_key.sign(msg)
    arm_sig = str(sig)
    persist_unlock(locked_key, lock_pass)
    return armored_key, arm_pass, arm_sig, locked_key, phrase_text.encode()


def generate_node_key_with_passphrase(lock_passphrase: bytes) -> tuple[PGPKey, str, bytes]:
    from proton_cli.service.drive.keygen import generate_armored_locked_key

    armored = generate_armored_locked_key(lock_passphrase)
    key, _ = PGPKey.from_blob(armored)
    return key, armored, lock_passphrase


def gen_node_hash_key(node_key: PGPKey) -> str:
    raw = os.urandom(32)
    token = base64.b64encode(raw).decode()
    msg = PGPMessage.new(token)
    with use_unlocked_key(node_key):
        enc = node_key.encrypt(msg)
    return str(enc)


def _message_bytes(value: object) -> bytes:
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    return str(value).encode()
