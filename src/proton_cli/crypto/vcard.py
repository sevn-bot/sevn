"""Minimal vCard helpers for Proton Contacts."""

from __future__ import annotations

from proton_cli.crypto import ical as ical_crypto


def contact_uid() -> str:
    return ical_crypto.contact_uid()


def signed_vcard(name: str, emails: list[str], uid: str) -> str:
    contact = ical_crypto.SignedContact(
        name=name,
        uid=uid,
        emails=[ical_crypto.SignedEmail(address=email) for email in emails if email],
    )
    return ical_crypto.build_signed_vcard(contact)


def field(vcard: str, key: str) -> str:
    return ical_crypto.field(vcard, key)


def fields(vcard: str, key: str) -> list[str]:
    return ical_crypto.fields(vcard, key)
