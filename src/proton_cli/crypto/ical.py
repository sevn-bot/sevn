"""Minimal iCalendar field helpers for Proton Calendar."""

from __future__ import annotations


def field(ical_text: str, key: str) -> str:
    for line in ical_text.replace("\r\n", "\n").split("\n"):
        upper = line.upper()
        if upper.startswith(f"{key}:") or upper.startswith(f"{key};"):
            return line.split(":", 1)[1]
    return ""
