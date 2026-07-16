"""Proton Pass service — vaults and items."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field

from proton_cli.account.keys import Unlocked, decrypt_pgp_message
from proton_cli.crypto import aead
from proton_cli.proto.vault import decode_vault_name_description
from proton_cli.proton.client import Client, Request


@dataclass
class Vault:
    share_id: str
    vault_id: str
    name: str = ""
    description: str = ""
    owner: bool = False
    shared: bool = False
    members: int = 0
    address_id: str = ""


@dataclass
class Item:
    share_id: str
    item_id: str
    revision: int = 0
    state: int = 0
    type: str = ""
    name: str = ""
    username: str = ""
    email: str = ""
    password: str = ""
    note: str = ""
    urls: list[str] = field(default_factory=list)


class PassService:
    def __init__(self, client: Client) -> None:
        self._client = client

    def vaults_list(self, unlocked: Unlocked) -> list[Vault]:
        shares = self._get_shares()
        out: list[Vault] = []
        for raw in shares:
            sh = json.loads(raw)
            if int(sh.get("TargetType", 0)) != 1:
                continue
            vault = Vault(
                share_id=str(sh.get("ShareID", "")),
                vault_id=str(sh.get("VaultID", "")),
                owner=bool(sh.get("Owner")),
                shared=bool(sh.get("Shared")),
                members=int(sh.get("TargetMembers", 0) or 0),
                address_id=str(sh.get("AddressID", "")),
            )
            content = str(sh.get("Content", ""))
            if content:
                sk = self._decrypt_share_keys(str(sh.get("ShareID", "")), unlocked)
                if sk:
                    rotation = int(sh.get("ContentKeyRotation", 0) or 0)
                    key = sk.get(rotation)
                    if key:
                        name, desc = _decrypt_vault(content, key)
                        vault.name = name
                        vault.description = desc
            out.append(vault)
        return out

    def items_list(self, unlocked: Unlocked, vault_filter: str = "") -> list[Item]:
        vaults = self.vaults_list(unlocked)
        out: list[Item] = []
        for vault in vaults:
            if vault_filter and vault_filter not in (vault.share_id, vault.name):
                continue
            sk = self._decrypt_share_keys(vault.share_id, unlocked)
            if not sk:
                continue
            items = self._fetch_items(vault.share_id, sk, unlocked)
            out.extend(items)
        return out

    def item_get(self, unlocked: Unlocked, share_id: str, item_id: str) -> Item:
        payload: dict = {}
        self._client.decode(
            Request(method="GET", path=f"/pass/v1/share/{share_id}/item/{item_id}"),
            payload,
        )
        raw_item = payload.get("Item") or {}
        sk = self._decrypt_share_keys(share_id, unlocked)
        rotation = int(raw_item.get("KeyRotation", 0) or 0)
        share_key = sk.get(rotation)
        if not share_key:
            raise ValueError(f"no share key for rotation {rotation}")
        item_key = aead.decrypt(
            share_key,
            base64.b64decode(str(raw_item.get("ItemKey", ""))),
            aead.TAG_ITEM_KEY,
        )
        plain = aead.decrypt(
            item_key,
            base64.b64decode(str(raw_item.get("Content", ""))),
            aead.TAG_ITEM_CONTENT,
        )
        parsed = _decode_item_content(plain)
        return Item(
            share_id=share_id,
            item_id=str(raw_item.get("ItemID", "")),
            revision=int(raw_item.get("Revision", 0) or 0),
            state=int(raw_item.get("State", 0) or 0),
            type=parsed.get("type", ""),
            name=parsed.get("name", ""),
            username=parsed.get("username", ""),
            email=parsed.get("email", ""),
            password=parsed.get("password", ""),
            note=parsed.get("note", ""),
            urls=list(parsed.get("urls") or []),
        )

    def _get_shares(self) -> list[str]:
        payload: dict = {}
        self._client.decode(Request(method="GET", path="/pass/v1/share"), payload)
        shares = payload.get("Shares") or []
        return [json.dumps(s) if isinstance(s, dict) else str(s) for s in shares]

    def _decrypt_share_keys(self, share_id: str, unlocked: Unlocked) -> dict[int, bytes] | None:
        payload: dict = {}
        self._client.decode(
            Request(method="GET", path=f"/pass/v1/share/{share_id}/key", query={"Page": "0"}),
            payload,
        )
        keys_raw = (payload.get("ShareKeys") or {}).get("Keys") or []
        out: dict[int, bytes] = {}
        all_keys = unlocked.user_keys + [k for ks in unlocked.addr_keys.values() for k in ks]
        for raw in keys_raw:
            entry = raw if isinstance(raw, dict) else json.loads(raw)
            kb = base64.b64decode(str(entry.get("Key", "")))
            rotation = int(entry.get("KeyRotation", 0) or 0)
            try:
                plain = decrypt_pgp_message(all_keys, kb)
                out[rotation] = plain
            except Exception:
                continue
        return out or None

    def _fetch_items(self, share_id: str, share_keys: dict[int, bytes], unlocked: Unlocked) -> list[Item]:
        payload: dict = {}
        self._client.decode(Request(method="GET", path=f"/pass/v1/share/{share_id}/item"), payload)
        out: list[Item] = []
        for raw in payload.get("Items") or []:
            entry = raw if isinstance(raw, dict) else json.loads(raw)
            rotation = int(entry.get("ContentKeyRotation", 0) or 0)
            share_key = share_keys.get(rotation)
            if not share_key:
                continue
            try:
                item_key = aead.decrypt(
                    share_key,
                    base64.b64decode(str(entry.get("ItemKey", ""))),
                    aead.TAG_ITEM_KEY,
                )
                plain = aead.decrypt(
                    item_key,
                    base64.b64decode(str(entry.get("Content", ""))),
                    aead.TAG_ITEM_CONTENT,
                )
                parsed = _decode_item_content(plain)
            except Exception:
                parsed = {"type": "unknown", "name": ""}
            out.append(
                Item(
                    share_id=share_id,
                    item_id=str(entry.get("ItemID", "")),
                    revision=int(entry.get("Revision", 0) or 0),
                    state=int(entry.get("State", 0) or 0),
                    type=str(parsed.get("type", "")),
                    name=str(parsed.get("name", "")),
                    username=str(parsed.get("username", "")),
                    email=str(parsed.get("email", "")),
                )
            )
        return out


def _decrypt_vault(enc_content: str, share_key: bytes) -> tuple[str, str]:
    data = base64.b64decode(enc_content)
    plain = aead.decrypt(share_key, data, aead.TAG_VAULT_CONTENT)
    return decode_vault_name_description(plain)


def _decode_item_content(data: bytes) -> dict[str, object]:
    """Decode minimal item protobuf fields used by list/get."""
    result: dict[str, object] = {"type": "login", "urls": []}
    i = 0
    while i < len(data):
        tag, i = _read_varint(data, i)
        field = tag >> 3
        wire = tag & 0x7
        if wire == 2:
            length, i = _read_varint(data, i)
            chunk = data[i : i + length]
            i += length
            if field == 1:
                result["name"] = chunk.decode("utf-8", errors="replace")
            elif field == 2:
                result["note"] = chunk.decode("utf-8", errors="replace")
            elif field in (10, 11, 12):
                nested = _decode_login_chunk(chunk)
                result.update(nested)
        elif wire == 0:
            _, i = _read_varint(data, i)
        elif wire == 1:
            i += 8
        elif wire == 5:
            i += 4
        else:
            break
    return result


def _decode_login_chunk(data: bytes) -> dict[str, object]:
    out: dict[str, object] = {}
    i = 0
    while i < len(data):
        tag, i = _read_varint(data, i)
        field = tag >> 3
        wire = tag & 0x7
        if wire == 2:
            length, i = _read_varint(data, i)
            value = data[i : i + length].decode("utf-8", errors="replace")
            i += length
            if field == 1:
                out["email"] = value
            elif field == 2:
                out["password"] = value
            elif field == 6:
                out["username"] = value
        elif wire == 0:
            _, i = _read_varint(data, i)
        elif wire == 1:
            i += 8
        elif wire == 5:
            i += 4
        else:
            break
    return out


def _read_varint(data: bytes, i: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while i < len(data):
        b = data[i]
        i += 1
        result |= (b & 0x7F) << shift
        if (b & 0x80) == 0:
            return result, i
        shift += 7
    return result, i
