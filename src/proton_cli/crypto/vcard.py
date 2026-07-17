"""Minimal vCard helpers for Proton Contacts."""

from __future__ import annotations

import uuid


def contact_uid() -> str:
    return str(uuid.uuid4())


def signed_vcard(name: str, emails: list[str], uid: str) -> str:
    lines = ["BEGIN:VCARD", "VERSION:4.0", f"FN:{name}", f"UID:{uid}"]
    for email in emails:
        if email:
            lines.append(f"EMAIL:{email}")
    lines.append("END:VCARD")
    return "\r\n".join(lines)


def field(vcard: str, key: str) -> str:
    for line in vcard.replace("\r\n", "\n").split("\n"):
        if line.upper().startswith(f"{key}:"):
            return line.split(":", 1)[1]
    return ""


def fields(vcard: str, key: str) -> list[str]:
    out: list[str] = []
    for line in vcard.replace("\r\n", "\n").split("\n"):
        if line.upper().startswith(f"{key}:"):
            out.append(line.split(":", 1)[1])
    return out
