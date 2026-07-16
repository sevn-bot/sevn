"""Proton Contacts operations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from proton_cli.crypto import cards as card_crypto
from proton_cli.crypto import vcard as vcard_crypto
from proton_cli.proton.client import Client, Request
from proton_cli.ref import pick

if TYPE_CHECKING:
    from proton_cli.account.keys import Unlocked


@dataclass
class Contact:
    id: str
    name: str = ""
    email: str = ""
    phone: str = ""
    emails: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    org: str = ""
    note: str = ""
    title: str = ""


@dataclass
class NewContact:
    name: str = ""
    emails: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    note: str = ""
    org: str = ""
    title: str = ""


class ContactsService:
    def __init__(self, client: Client) -> None:
        self._client = client

    def list_contacts(self, unlocked: Unlocked) -> list[Contact]:
        user_key = unlocked.user_keys[0] if unlocked.user_keys else None
        if not user_key:
            raise ValueError("no user key available")
        out: list[Contact] = []
        for page in range(100):
            payload: dict = {}
            self._client.decode(
                Request(
                    method="GET",
                    path="/contacts/v4/contacts/export",
                    query={"Page": str(page), "PageSize": "50"},
                ),
                payload,
            )
            rows = payload.get("Contacts") or []
            if not rows:
                break
            for raw in rows:
                cid = str(raw.get("ID", ""))
                card_rows = raw.get("Cards") or []
                try:
                    decrypted = card_crypto.decrypt_cards(card_rows, user_key, user_key)
                    contact = _contact_from_cards(cid, decrypted)
                    out.append(contact)
                except Exception:
                    continue
            if len(rows) < 50:
                break
        return out

    def get_contact(self, unlocked: Unlocked, contact_id: str) -> Contact:
        user_key = unlocked.user_keys[0]
        payload: dict = {}
        self._client.decode(
            Request(method="GET", path=f"/contacts/v4/contacts/{contact_id}"),
            payload,
        )
        raw = payload.get("Contact") or {}
        decrypted = card_crypto.decrypt_cards(raw.get("Cards") or [], user_key, user_key)
        return _contact_from_cards(str(raw.get("ID", contact_id)), decrypted)

    def resolve_contact(self, unlocked: Unlocked, ref: str) -> str:
        if len(ref) > 20 and "-" in ref:
            return ref
        rows = self.list_contacts(unlocked)
        needle = ref.lower()
        matches = [
            c
            for c in rows
            if needle in c.name.lower() or any(needle in e.lower() for e in c.emails)
        ]
        chosen = pick(
            "contact",
            ref,
            matches,
            lambda c: c.id,
            lambda c: f"{c.name} <{c.email}>",
        )
        return chosen.id

    def create_contact(self, unlocked: Unlocked, nc: NewContact) -> str:
        if not nc.name and not nc.emails:
            raise ValueError("name or email is required")
        user_key = unlocked.user_keys[0]
        name = nc.name or nc.emails[0]
        signed = vcard_crypto.signed_vcard(name, nc.emails, vcard_crypto.contact_uid())
        card_rows = [card_crypto.sign_card(signed, user_key)]
        if nc.note or nc.org or nc.title or nc.phones:
            enc_body = _encrypted_vcard(nc)
            card_rows.append(card_crypto.encrypt_and_sign_card(enc_body, user_key, user_key))
        payload: dict = {}
        self._client.decode(
            Request(
                method="POST",
                path="/contacts/v4/contacts",
                body={"Contacts": [{"Cards": card_rows}], "Overwrite": 0, "Labels": 0},
            ),
            payload,
        )
        responses = payload.get("Responses") or []
        if responses:
            return str((responses[0].get("Response") or {}).get("Contact", {}).get("ID", ""))
        return ""

    def delete_contacts(self, ids: list[str]) -> None:
        self._client.decode(
            Request(
                method="PUT",
                path="/contacts/v4/contacts/delete",
                body={"IDs": ids},
            ),
        )


def _contact_from_cards(contact_id: str, cards: list[str]) -> Contact:
    joined = "\n".join(cards)
    emails = vcard_crypto.fields(joined, "EMAIL")
    phones = vcard_crypto.fields(joined, "TEL")
    contact = Contact(
        id=contact_id,
        name=vcard_crypto.field(joined, "FN"),
        emails=emails,
        phones=phones,
        org=vcard_crypto.field(joined, "ORG"),
        note=vcard_crypto.field(joined, "NOTE"),
        title=vcard_crypto.field(joined, "TITLE"),
    )
    if emails:
        contact.email = emails[0]
    if phones:
        contact.phone = phones[0]
    return contact


def _encrypted_vcard(nc: NewContact) -> str:
    lines = ["BEGIN:VCARD", "VERSION:4.0"]
    for phone in nc.phones:
        lines.append(f"TEL:{phone}")
    if nc.org:
        lines.append(f"ORG:{nc.org}")
    if nc.title:
        lines.append(f"TITLE:{nc.title}")
    if nc.note:
        lines.append(f"NOTE:{nc.note}")
    lines.append("END:VCARD")
    return "\r\n".join(lines)
