"""Proton Contacts operations."""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pgpy import PGPKey

from proton_cli.crypto import cards as card_crypto
from proton_cli.crypto import ical as ical_crypto
from proton_cli.crypto import vcard as vcard_crypto
from proton_cli.errors import NotFound
from proton_cli.proton.client import Client, Request
from proton_cli.ref import pick

if TYPE_CHECKING:
    from proton_cli.account.keys import Unlocked

_logger = logging.getLogger(__name__)


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


@dataclass
class Group:
    id: str
    name: str = ""
    color: str = ""


@dataclass
class ContactCrypto:
    armored_keys: list[str] = field(default_factory=list)
    encrypt: bool | None = None
    sign: bool | None = None
    scheme: str = ""


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
                except Exception as exc:
                    _logger.warning(
                        "contact card decrypt failed contact_id=%s: %s",
                        cid,
                        exc,
                    )
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
        if not responses:
            raise ValueError("contact create returned empty Responses")
        cid = str((responses[0].get("Response") or {}).get("Contact", {}).get("ID", ""))
        if not cid:
            raise ValueError("contact create returned no Contact ID")
        return cid

    def delete_contacts(self, ids: list[str]) -> None:
        self._client.decode(
            Request(
                method="PUT",
                path="/contacts/v4/contacts/delete",
                body={"IDs": ids},
            ),
        )

    def groups_list(self) -> list[Group]:
        payload: dict = {}
        self._client.decode(
            Request(method="GET", path="/core/v4/labels", query={"Type": "2"}),
            payload,
        )
        return [
            Group(
                id=str(item.get("ID", "")),
                name=str(item.get("Name", "")),
                color=str(item.get("Color", "")),
            )
            for item in payload.get("Labels") or []
        ]

    def group_create(self, name: str, color: str = "") -> str:
        payload: dict = {}
        self._client.decode(
            Request(
                method="POST",
                path="/core/v4/labels",
                body={"Name": name, "Color": color, "Type": 2},
            ),
            payload,
        )
        return str((payload.get("Label") or {}).get("ID", ""))

    def group_delete(self, group_id: str) -> None:
        self._client.decode(
            Request(method="DELETE", path=f"/core/v4/labels/{group_id}"),
        )

    def group_add(self, group_id: str, contact_ids: list[str]) -> None:
        self._client.decode(
            Request(
                method="PUT",
                path="/contacts/v4/contacts/label",
                body={"LabelID": group_id, "ContactIDs": contact_ids},
            ),
        )

    def group_remove(self, group_id: str, contact_ids: list[str]) -> None:
        self._client.decode(
            Request(
                method="PUT",
                path="/contacts/v4/contacts/unlabel",
                body={"LabelID": group_id, "ContactIDs": contact_ids},
            ),
        )

    def pinned_keys_for(self, unlocked: Unlocked, email: str) -> ContactCrypto | None:
        contact_id, ok = self._contact_id_by_email(email)
        if not ok:
            return None
        try:
            self.get_contact(unlocked, contact_id)
            joined = "\n".join(
                card_crypto.decrypt_cards(
                    self._raw_contact_cards(contact_id),
                    unlocked.user_keys[0],
                    unlocked.user_keys[0],
                )
            )
        except Exception as exc:
            _logger.warning(
                "contacts_pinned_keys_lookup_failed email=%s contact_id=%s reason=%s",
                email,
                contact_id,
                exc,
            )
            return None
        group = ical_crypto.email_group(joined, email)
        if not group:
            return None
        armored = _decode_pinned_keys(ical_crypto.group_values(joined, group, "KEY"))
        if not armored:
            return None
        crypto = ContactCrypto(
            armored_keys=armored,
            scheme=ical_crypto.group_value(joined, group, "X-PM-SCHEME").lower(),
        )
        encrypt_raw = ical_crypto.group_value(joined, group, "X-PM-ENCRYPT")
        if encrypt_raw:
            crypto.encrypt = encrypt_raw.strip().lower() == "true"
        sign_raw = ical_crypto.group_value(joined, group, "X-PM-SIGN")
        if sign_raw:
            crypto.sign = sign_raw.strip().lower() == "true"
        return crypto

    def pin_key(
        self,
        unlocked: Unlocked,
        contact_id: str,
        email: str,
        armored_key: str,
        encrypt: bool | None = None,
        sign: bool | None = None,
        scheme: str = "",
    ) -> None:
        key_value = _encode_pinned_key(armored_key)
        model, others = self._editable_signed_card(unlocked, contact_id)
        entry = model.find_email(email)
        if entry is None:
            model.emails.append(ical_crypto.SignedEmail(address=email))
            entry = model.emails[-1]
        entry.key_values = _prepend_unique(entry.key_values, key_value)
        entry.encrypt = True if encrypt is None else encrypt
        entry.sign = True if sign is None else sign
        if scheme:
            entry.scheme = scheme
        self._put_signed_card(unlocked, contact_id, model, others)

    def unpin_key(self, unlocked: Unlocked, contact_id: str, email: str) -> None:
        model, others = self._editable_signed_card(unlocked, contact_id)
        entry = model.find_email(email)
        if entry is None or not entry.key_values:
            raise NotFound("pinned key", email)
        entry.key_values = []
        entry.encrypt = None
        entry.sign = None
        entry.scheme = ""
        self._put_signed_card(unlocked, contact_id, model, others)

    def _contact_id_by_email(self, email: str) -> tuple[str, bool]:
        payload: dict = {}
        self._client.decode(
            Request(
                method="GET",
                path="/contacts/v4/contacts/emails",
                query={"Email": email},
            ),
            payload,
        )
        rows = payload.get("ContactEmails") or []
        if not rows or int(rows[0].get("Defaults", 0) or 0) == 1:
            return "", False
        return str(rows[0].get("ContactID", "")), True

    def _raw_contact_cards(self, contact_id: str) -> list[dict]:
        payload: dict = {}
        self._client.decode(
            Request(method="GET", path=f"/contacts/v4/contacts/{contact_id}"),
            payload,
        )
        return list((payload.get("Contact") or {}).get("Cards") or [])

    def _editable_signed_card(
        self,
        unlocked: Unlocked,
        contact_id: str,
    ) -> tuple[ical_crypto.SignedContact, list[dict]]:
        cards = self._raw_contact_cards(contact_id)
        signed_data = ""
        others: list[dict] = []
        for card in cards:
            if int(card.get("Type", 0) or 0) == card_crypto.CARD_SIGNED and not signed_data:
                signed_data = str(card.get("Data", ""))
                continue
            others.append(
                {
                    "Type": card.get("Type", 0),
                    "Data": card.get("Data", ""),
                    "Signature": card.get("Signature", ""),
                }
            )
        if not signed_data:
            raise ValueError("contact has no signed card to edit")
        model = ical_crypto.parse_signed_vcard(signed_data)
        if not model.uid:
            model.uid = vcard_crypto.contact_uid()
        return model, others

    def _put_signed_card(
        self,
        unlocked: Unlocked,
        contact_id: str,
        model: ical_crypto.SignedContact,
        others: list[dict],
    ) -> None:
        signed = card_crypto.sign_card(ical_crypto.build_signed_vcard(model), unlocked.user_keys[0])
        cards: list[dict] = [signed]
        cards.extend(others)
        self._client.decode(
            Request(
                method="PUT",
                path=f"/contacts/v4/contacts/{contact_id}",
                body={"Cards": cards},
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


def _encode_pinned_key(armored: str) -> str:
    key, _ = PGPKey.from_blob(armored.strip())
    public = key if key.is_public else key.pubkey
    raw = bytes(public)
    return "data:application/pgp-keys;base64," + base64.b64encode(raw).decode()


def _decode_pinned_keys(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        if "," not in value:
            continue
        _, b64 = value.split(",", 1)
        try:
            raw = base64.b64decode(b64.strip())
            key, _ = PGPKey.from_blob(raw)
            public = key if key.is_public else key.pubkey
            out.append(str(public))
        except Exception:
            continue
    return out


def _prepend_unique(existing: list[str], value: str) -> list[str]:
    out = [value]
    for item in existing:
        if item != value:
            out.append(item)
    return out
