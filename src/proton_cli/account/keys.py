"""Unlock Proton PGP key hierarchy for encrypted operations."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field

import pgpy
from pgpy import PGPKey, PGPMessage

from proton_cli.account import localkey
from proton_cli.crypto.srp.util import mailbox_password_secret
from proton_cli.proton.client import Client, Request


@dataclass
class Key:
    id: str
    private_key: str
    token: str = ""
    signature: str = ""
    primary: int = 0
    active: int = 1


@dataclass
class Address:
    id: str
    email: str
    keys: list[Key] = field(default_factory=list)


@dataclass
class Unlocked:
    user_keys: list[PGPKey] = field(default_factory=list)
    addr_keys: dict[str, list[PGPKey]] = field(default_factory=dict)
    addresses: list[Address] = field(default_factory=list)

    def primary_addr(self) -> tuple[list[PGPKey], str, str]:
        for addr in self.addresses:
            keys = self.addr_keys.get(addr.id)
            if not keys:
                continue
            email = addr.email
            if email.endswith(("@proton.me", "@pm.me", "@protonmail.com")):
                return keys, addr.id, email
        for addr in self.addresses:
            keys = self.addr_keys.get(addr.id)
            if keys:
                return keys, addr.id, addr.email
        raise ValueError("no address keys available")


@contextmanager
def use_unlocked_key(key: PGPKey):
    """Use a session-unlocked private key or unlock it for one operation."""
    if key.is_unlocked:
        yield key
    else:
        with key.unlock(None):
            yield key


def persist_unlock(key: PGPKey, passphrase: bytes | str) -> PGPKey:
    """Unlock *key* for the remainder of the process (pgpy re-locks on context exit)."""
    key.unlock(passphrase).__enter__()
    return key


def unlock(client: Client, password: str) -> Unlocked:
    skp = client.salted_key_pass()
    if not skp and client.enc_key_blob():
        key = localkey.get(client)
        skp = localkey.unwrap(client.enc_key_blob(), key)
        client.set_salted_key_pass(skp)
    elif not skp:
        if not password:
            raise ValueError(
                "password required for encrypted operations; set PROTON_PASSWORD or --password"
            )
        skp = _derive_salted_key_pass(client, password)
        client.set_salted_key_pass(skp)
        _wrap_and_persist(client, skp)
    elif not client.enc_key_blob():
        _wrap_and_persist(client, skp)

    user = _get_user(client)
    user_keys = _unlock_keys(user.keys, skp.encode(), None)
    addrs = _get_addresses(client)
    addr_keys: dict[str, list[PGPKey]] = {}
    for addr in addrs:
        unlocked = _unlock_keys(addr.keys, skp.encode(), user_keys)
        if unlocked:
            addr_keys[addr.id] = unlocked
    if not addr_keys:
        raise ValueError("failed to unlock any address keys")
    return Unlocked(user_keys=user_keys, addr_keys=addr_keys, addresses=addrs)


def _derive_salted_key_pass(client: Client, password: str) -> str:
    payload: dict = {}
    client.decode(Request(method="GET", path="/core/v4/keys/salts"), payload)
    salts = payload.get("KeySalts") or []
    if not salts:
        raise ValueError("no key salts returned")
    salt_b64 = str(salts[0].get("KeySalt", ""))
    return mailbox_password_secret(password.encode(), salt_b64)


def _wrap_and_persist(client: Client, skp: str) -> None:
    try:
        key = localkey.generate()
        localkey.put(client, key)
        blob = localkey.wrap(skp, key)
        client.set_enc_key_blob(blob)
        client.persist()
    except Exception:
        pass


def _get_user(client: Client) -> object:
    payload: dict = {}
    client.decode(Request(method="GET", path="/core/v4/users"), payload)
    user = payload.get("User") or {}
    keys = [
        Key(
            id=str(k.get("ID", "")),
            private_key=str(k.get("PrivateKey", "")),
            token=str(k.get("Token", "")),
            signature=str(k.get("Signature", "")),
            primary=int(k.get("Primary", 0) or 0),
            active=int(k.get("Active", 0) or 0),
        )
        for k in user.get("Keys") or []
    ]

    @dataclass
    class _User:
        keys: list[Key]

    return _User(keys=keys)


def _get_addresses(client: Client) -> list[Address]:
    payload: dict = {}
    client.decode(Request(method="GET", path="/core/v4/addresses"), payload)
    out: list[Address] = []
    for raw in payload.get("Addresses") or []:
        keys = [
            Key(
                id=str(k.get("ID", "")),
                private_key=str(k.get("PrivateKey", "")),
                token=str(k.get("Token", "")),
                signature=str(k.get("Signature", "")),
                primary=int(k.get("Primary", 0) or 0),
                active=int(k.get("Active", 0) or 0),
            )
            for k in raw.get("Keys") or []
        ]
        out.append(Address(id=str(raw.get("ID", "")), email=str(raw.get("Email", "")), keys=keys))
    return out


def _unlock_keys(
    keys: list[Key], passphrase: bytes, user_keys: list[PGPKey] | None
) -> list[PGPKey]:
    unlocked: list[PGPKey] = []
    for key in keys:
        if key.active == 0 or not key.private_key:
            continue
        secret = passphrase
        if key.token and key.signature and user_keys:
            derived = _decrypt_token(key.token, key.signature, user_keys)
            if derived:
                secret = derived
        try:
            pgp_key, _ = PGPKey.from_blob(key.private_key)
            persist_unlock(pgp_key, secret)
            unlocked.append(pgp_key)
        except Exception:
            continue
    return unlocked


def _decrypt_token(token_arm: str, sig_arm: str, keys: list[PGPKey]) -> bytes | None:
    try:
        message = PGPMessage.from_blob(token_arm)
        signature = pgpy.PGPSignature.from_blob(sig_arm)
        for key in keys:
            with use_unlocked_key(key):
                decrypted = key.decrypt(message)
            if key.verify(decrypted, signature):
                return bytes(decrypted.message)
    except Exception:
        return None
    return None


def decrypt_pgp_message(keys: list[PGPKey], data: bytes) -> bytes:
    message = PGPMessage.from_blob(data)
    last_err: Exception | None = None
    for key in keys:
        try:
            with use_unlocked_key(key):
                decrypted = key.decrypt(message)
            return bytes(decrypted.message)
        except Exception as exc:
            last_err = exc
            continue
    if last_err:
        raise last_err
    raise ValueError("failed to decrypt PGP message")
