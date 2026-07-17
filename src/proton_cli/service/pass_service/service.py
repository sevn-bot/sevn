"""Proton Pass service — vaults and items (read + write)."""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass, field

from pgpy import PGPMessage

from proton_cli.account.keys import Unlocked, decrypt_pgp_message, use_unlocked_key
from proton_cli.crypto import aead
from proton_cli.errors import NotFound
from proton_cli.proto import item as item_proto
from proton_cli.proto.vault import decode_vault_name_description
from proton_cli.proton.client import Client, Request
from proton_cli.ref import pick

_logger = logging.getLogger(__name__)


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


@dataclass
class NewItem:
    type: str = "login"
    name: str = ""
    username: str = ""
    password: str = ""
    email: str = ""
    url: str = ""
    note: str = ""
    totp: str = ""


@dataclass
class ItemPatch:
    name: str | None = None
    username: str | None = None
    password: str | None = None
    email: str | None = None
    url: str | None = None
    note: str | None = None
    totp: str | None = None


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

    def resolve_vault(self, unlocked: Unlocked, name_or_id: str = "") -> str:
        vaults = self.vaults_list(unlocked)
        if not name_or_id:
            if not vaults:
                raise NotFound("vault")
            return vaults[0].share_id
        for v in vaults:
            if v.share_id == name_or_id or v.name == name_or_id:
                return v.share_id
        raise NotFound("vault", name_or_id)

    def vault_create(self, unlocked: Unlocked, name: str) -> str:
        raw_key = aead.new_key()
        addr_keys, addr_id, _email = unlocked.primary_addr()
        enc_key = _encrypt_binary(addr_keys, raw_key)
        vault_bytes = item_proto.encode_vault(name)
        ct = aead.encrypt(raw_key, vault_bytes, aead.TAG_VAULT_CONTENT)
        payload: dict = {}
        self._client.decode(
            Request(
                method="POST",
                path="/pass/v1/vault",
                body={
                    "AddressID": addr_id,
                    "ContentFormatVersion": 1,
                    "Content": base64.b64encode(ct).decode(),
                    "EncryptedVaultKey": base64.b64encode(enc_key).decode(),
                },
            ),
            payload,
        )
        share = payload.get("Share") or {}
        return str(share.get("ShareID", ""))

    def vault_rename(self, unlocked: Unlocked, share_id: str, new_name: str) -> None:
        shares = self._get_shares()
        content = ""
        rotation = 0
        for raw in shares:
            sh = json.loads(raw)
            if str(sh.get("ShareID")) == share_id and int(sh.get("TargetType", 0)) == 1:
                content = str(sh.get("Content", ""))
                rotation = int(sh.get("ContentKeyRotation", 0) or 0)
                break
        else:
            raise NotFound("vault", share_id)
        sk = self._decrypt_share_keys(share_id, unlocked)
        share_key = sk.get(rotation) if sk else None
        if not share_key:
            raise ValueError(f"no share key for rotation {rotation}")
        desc = ""
        if content:
            _, desc = _decrypt_vault(content, share_key)
        vault_bytes = item_proto.encode_vault(new_name, desc)
        ct = aead.encrypt(share_key, vault_bytes, aead.TAG_VAULT_CONTENT)
        self._client.decode(
            Request(
                method="PUT",
                path=f"/pass/v1/vault/{share_id}",
                body={
                    "Content": base64.b64encode(ct).decode(),
                    "ContentFormatVersion": 1,
                    "KeyRotation": rotation,
                },
            )
        )

    def vault_delete(self, share_id: str) -> None:
        self._client.decode(Request(method="DELETE", path=f"/pass/v1/vault/{share_id}"))

    def items_list(self, unlocked: Unlocked, vault_filter: str = "") -> list[Item]:
        vaults = self.vaults_list(unlocked)
        out: list[Item] = []
        for vault in vaults:
            if vault_filter and vault_filter not in (vault.share_id, vault.name):
                continue
            sk = self._decrypt_share_keys(vault.share_id, unlocked)
            if not sk:
                continue
            items = self._fetch_items(vault.share_id, sk)
            out.extend(items)
        return out

    def resolve_item(self, unlocked: Unlocked, args: list[str]) -> tuple[str, str]:
        if len(args) == 2:
            return args[0], args[1]
        needle = args[0].lower()
        items = self.items_list(unlocked, "")
        for it in items:
            if it.item_id == args[0]:
                return it.share_id, it.item_id
        matches = [
            it
            for it in items
            if needle in it.name.lower() or any(needle in u.lower() for u in it.urls)
        ]
        chosen = pick(
            "item",
            args[0],
            matches,
            lambda i: i.item_id,
            lambda i: f"{i.type}  {i.name}  (share {i.share_id})",
        )
        return chosen.share_id, chosen.item_id

    def item_get(self, unlocked: Unlocked, share_id: str, item_id: str) -> Item:
        return self._item_from_api(unlocked, share_id, item_id)

    def item_create(self, unlocked: Unlocked, share_id: str, new_item: NewItem) -> str:
        if new_item.type != "login":
            raise ValueError(f"unsupported item type {new_item.type!r} (PR2 supports login only)")
        sk = self._decrypt_share_keys(share_id, unlocked)
        share_key, rotation = _latest_key(sk)
        plain = item_proto.encode_login_item(
            name=new_item.name,
            note=new_item.note,
            username=new_item.username,
            email=new_item.email,
            password=new_item.password,
            url=new_item.url,
            totp=new_item.totp,
        )
        item_key = aead.new_key()
        ct = aead.encrypt(item_key, plain, aead.TAG_ITEM_CONTENT)
        ek = aead.encrypt(share_key, item_key, aead.TAG_ITEM_KEY)
        payload: dict = {}
        self._client.decode(
            Request(
                method="POST",
                path=f"/pass/v1/share/{share_id}/item",
                body={
                    "Content": base64.b64encode(ct).decode(),
                    "ContentFormatVersion": 7,
                    "ItemKey": base64.b64encode(ek).decode(),
                    "KeyRotation": rotation,
                },
            ),
            payload,
        )
        item = payload.get("Item") or {}
        return str(item.get("ItemID", ""))

    def item_edit(
        self,
        unlocked: Unlocked,
        share_id: str,
        item_id: str,
        patch: ItemPatch,
    ) -> None:
        payload: dict = {}
        self._client.decode(
            Request(method="GET", path=f"/pass/v1/share/{share_id}/item/{item_id}"),
            payload,
        )
        raw_item = payload.get("Item") or {}
        sk = self._decrypt_share_keys(share_id, unlocked)
        rotation = int(raw_item.get("KeyRotation", 0) or 0)
        share_key = sk.get(rotation) if sk else None
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
        parsed = item_proto.decode_item_content(plain)
        if parsed.get("type") != "login":
            msg = f"item_edit only supports login items (got {parsed.get('type')!r})"
            raise ValueError(msg)
        updated = item_proto.patch_login_item(
            plain,
            name=patch.name,
            note=patch.note,
            username=patch.username,
            email=patch.email,
            password=patch.password,
            url=patch.url,
            totp=patch.totp,
        )
        ct = aead.encrypt(item_key, updated, aead.TAG_ITEM_CONTENT)
        latest: dict = {}
        self._client.decode(
            Request(method="GET", path=f"/pass/v1/share/{share_id}/item/{item_id}/key/latest"),
            latest,
        )
        key_info = latest.get("Key") or {}
        self._client.decode(
            Request(
                method="PUT",
                path=f"/pass/v1/share/{share_id}/item/{item_id}",
                body={
                    "Content": base64.b64encode(ct).decode(),
                    "ContentFormatVersion": 7,
                    "KeyRotation": int(key_info.get("KeyRotation", rotation) or rotation),
                    "LastRevision": int(raw_item.get("Revision", 0) or 0),
                },
            )
        )

    def item_trash(self, share_id: str, item_id: str) -> None:
        rev = self._item_revision(share_id, item_id)
        self._client.decode(
            Request(
                method="POST",
                path=f"/pass/v1/share/{share_id}/item/trash",
                body={"Items": [{"ItemID": item_id, "Revision": rev}]},
            )
        )

    def item_restore(self, share_id: str, item_id: str) -> None:
        rev = self._item_revision(share_id, item_id)
        self._client.decode(
            Request(
                method="POST",
                path=f"/pass/v1/share/{share_id}/item/untrash",
                body={"Items": [{"ItemID": item_id, "Revision": rev}]},
            )
        )

    def item_delete(self, share_id: str, item_id: str) -> None:
        payload: dict = {}
        self._client.decode(
            Request(method="GET", path=f"/pass/v1/share/{share_id}/item/{item_id}"),
            payload,
        )
        raw_item = payload.get("Item") or {}
        state = int(raw_item.get("State", 0) or 0)
        revision = int(raw_item.get("Revision", 0) or 0)
        if state != 2:
            self.item_trash(share_id, item_id)
            payload = {}
            self._client.decode(
                Request(method="GET", path=f"/pass/v1/share/{share_id}/item/{item_id}"),
                payload,
            )
            raw_item = payload.get("Item") or {}
            revision = int(raw_item.get("Revision", 0) or 0)
        self._client.decode(
            Request(
                method="DELETE",
                path=f"/pass/v1/share/{share_id}/item",
                body={"Items": [{"ItemID": item_id, "Revision": revision}]},
            )
        )

    def find_login_by_name(
        self,
        unlocked: Unlocked,
        name: str,
        *,
        vault_filter: str = "",
    ) -> Item | None:
        for it in self.items_list(unlocked, vault_filter):
            if it.name == name and it.type == "login":
                return self.item_get(unlocked, it.share_id, it.item_id)
        return None

    def upsert_login_password(
        self,
        unlocked: Unlocked,
        *,
        name: str,
        password: str,
        vault_filter: str = "",
    ) -> str:
        """Create or update a login item; return item id."""
        share_id = self.resolve_vault(unlocked, vault_filter)
        existing = self.find_login_by_name(unlocked, name, vault_filter=share_id)
        if existing:
            self.item_edit(
                unlocked, existing.share_id, existing.item_id, ItemPatch(password=password)
            )
            return existing.item_id
        return self.item_create(
            unlocked,
            share_id,
            NewItem(type="login", name=name, password=password),
        )

    def _item_from_api(self, unlocked: Unlocked, share_id: str, item_id: str) -> Item:
        payload: dict = {}
        self._client.decode(
            Request(method="GET", path=f"/pass/v1/share/{share_id}/item/{item_id}"),
            payload,
        )
        raw_item = payload.get("Item") or {}
        sk = self._decrypt_share_keys(share_id, unlocked)
        rotation = int(raw_item.get("KeyRotation", 0) or 0)
        share_key = sk.get(rotation) if sk else None
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
        parsed = item_proto.decode_item_content(plain)
        return Item(
            share_id=share_id,
            item_id=str(raw_item.get("ItemID", "")),
            revision=int(raw_item.get("Revision", 0) or 0),
            state=int(raw_item.get("State", 0) or 0),
            type=str(parsed.get("type", "login")),
            name=str(parsed.get("name", "")),
            username=str(parsed.get("username", "")),
            email=str(parsed.get("email", "")),
            password=str(parsed.get("password", "")),
            note=str(parsed.get("note", "")),
            urls=list(parsed.get("urls") or []),
        )

    def _item_revision(self, share_id: str, item_id: str) -> int:
        payload: dict = {}
        self._client.decode(
            Request(method="GET", path=f"/pass/v1/share/{share_id}/item/{item_id}"),
            payload,
        )
        return int((payload.get("Item") or {}).get("Revision", 0) or 0)

    def _get_shares(self) -> list[str]:
        payload: dict = {}
        self._client.decode(Request(method="GET", path="/pass/v1/share"), payload)
        shares = payload.get("Shares") or []
        return [json.dumps(s) if isinstance(s, dict) else str(s) for s in shares]

    def _decrypt_share_keys(self, share_id: str, unlocked: Unlocked) -> dict[int, bytes]:
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
        return out

    def _fetch_items(self, share_id: str, share_keys: dict[int, bytes]) -> list[Item]:
        out: list[Item] = []
        since = ""
        for _page in range(100):
            query: dict[str, str] = {"Since": since} if since else {}
            payload: dict = {}
            self._client.decode(
                Request(method="GET", path=f"/pass/v1/share/{share_id}/item", query=query or None),
                payload,
            )
            items_env = payload.get("Items") or {}
            if isinstance(items_env, dict):
                revisions = items_env.get("RevisionsData") or []
                since = str(items_env.get("LastToken", "") or "")
            else:
                revisions = items_env if isinstance(items_env, list) else []
                since = ""
            if not revisions:
                break
            for raw in revisions:
                entry = raw if isinstance(raw, dict) else json.loads(raw)
                if int(entry.get("State", 0) or 0) != 1:
                    continue
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
                    parsed = item_proto.decode_item_content(plain)
                except (ValueError, json.JSONDecodeError, KeyError) as exc:
                    _logger.debug("failed to decrypt pass item %s: %s", entry.get("ItemID"), exc)
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
            if not since:
                break
        return out


def _decrypt_vault(enc_content: str, share_key: bytes) -> tuple[str, str]:
    data = base64.b64decode(enc_content)
    plain = aead.decrypt(share_key, data, aead.TAG_VAULT_CONTENT)
    return decode_vault_name_description(plain)


def _latest_key(sk: dict[int, bytes]) -> tuple[bytes, int]:
    if not sk:
        raise ValueError("no share keys")
    rotation = max(sk)
    return sk[rotation], rotation


def _encrypt_binary(keys: list, data: bytes) -> bytes:

    message = PGPMessage.new(data)
    last_err: Exception | None = None
    for key in keys:
        try:
            with use_unlocked_key(key):
                encrypted = key.encrypt(message)
            return bytes(encrypted)
        except Exception as exc:
            last_err = exc
    if last_err:
        raise last_err
    raise ValueError("failed to encrypt with address keys")
