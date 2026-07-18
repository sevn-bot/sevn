"""Proton Mail folder aliases."""

from __future__ import annotations

MAILBOX_LABEL_IDS: dict[str, str] = {
    "inbox": "0",
    "drafts": "8",
    "sent": "7",
    "trash": "3",
    "spam": "4",
    "archive": "6",
    "starred": "10",
    "scheduled": "12",
    "all": "5",
}

LABEL_TRASH = "3"
LABEL_STARRED = "10"


def resolve_folder(name: str) -> str:
    if not name:
        return MAILBOX_LABEL_IDS["inbox"]
    return MAILBOX_LABEL_IDS.get(name.lower(), name)
