"""iCalendar and vCard field helpers for Proton Calendar and Contacts."""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, field as dc_field
from datetime import datetime, timedelta, timezone


def field(ical_text: str, key: str) -> str:
    prefix = f"{key}:"
    prefix_param = f"{key};"
    for line in ical_text.replace("\r\n", "\n").split("\n"):
        line = line.strip()
        upper = line.upper()
        if upper.startswith(prefix.upper()):
            return line.split(":", 1)[1]
        if upper.startswith(prefix_param.upper()):
            idx = line.find(":")
            if idx >= 0:
                return line[idx + 1 :]
        if f".{key.upper()};" in upper or f".{key.upper()}:" in upper:
            idx = line.find(":")
            if idx >= 0:
                return line[idx + 1 :]
    return ""


def fields(text: str, key: str) -> list[str]:
    out: list[str] = []
    prefix = f"{key}:"
    prefix_param = f"{key};"
    for line in text.replace("\r\n", "\n").split("\n"):
        line = line.strip()
        upper = line.upper()
        if upper.startswith(prefix.upper()):
            out.append(line.split(":", 1)[1])
        elif upper.startswith(prefix_param.upper()):
            idx = line.find(":")
            if idx >= 0:
                out.append(line[idx + 1 :])
        elif f".{key.upper()};" in upper or f".{key.upper()}:" in upper:
            idx = line.find(":")
            if idx >= 0:
                out.append(line[idx + 1 :])
    return out


def canonical_email(email: str) -> str:
    return email.strip().lower()


def event_uid() -> str:
    return f"{time.time_ns()}@proton-cli"


def contact_uid() -> str:
    return f"proton-cli-{time.time_ns()}"


@dataclass
class Attendee:
    email: str
    token: str


def attendee_token(uid: str, email: str) -> str:
    digest = hashlib.sha1((uid + canonical_email(email)).encode()).hexdigest()
    return digest


def _event_dates(start: datetime, end: datetime, all_day: bool) -> tuple[str, str]:
    if all_day:
        return (
            f"DTSTART;VALUE=DATE:{start.strftime('%Y%m%d')}",
            f"DTEND;VALUE=DATE:{end.strftime('%Y%m%d')}",
        )
    start_utc = start.astimezone(timezone.utc)
    end_utc = end.astimezone(timezone.utc)
    return (
        f"DTSTART:{start_utc.strftime('%Y%m%dT%H%M%SZ')}",
        f"DTEND:{end_utc.strftime('%Y%m%dT%H%M%SZ')}",
    )


def _attendee_line(att: Attendee) -> str:
    return (
        f"ATTENDEE;CN={att.email};ROLE=REQ-PARTICIPANT;RSVP=TRUE;"
        f"PARTSTAT=NEEDS-ACTION;X-PM-TOKEN={att.token}:mailto:{att.email}"
    )


def signed_vevent(
    uid: str,
    start: datetime,
    end: datetime,
    all_day: bool,
    sequence: int,
    rrule: str,
    organizer: str,
) -> str:
    dtstamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dtstart, dtend = _event_dates(start, end, all_day)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//proton-cli//EN",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{dtstamp}",
        dtstart,
        dtend,
    ]
    if organizer:
        lines.append(f"ORGANIZER;CN={organizer}:mailto:{organizer}")
    if rrule:
        lines.append(f"RRULE:{rrule}")
    lines.extend([f"SEQUENCE:{sequence}", "END:VEVENT", "END:VCALENDAR"])
    return "\r\n".join(lines)


def encrypted_vevent(title: str, location: str, description: str) -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//proton-cli//EN",
        "BEGIN:VEVENT",
        f"SUMMARY:{title}",
    ]
    if location:
        lines.append(f"LOCATION:{location}")
    if description:
        lines.append(f"DESCRIPTION:{description}")
    lines.extend(["END:VEVENT", "END:VCALENDAR"])
    return "\r\n".join(lines)


def attendees_vevent(uid: str, attendees: list[Attendee]) -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//proton-cli//EN",
        "BEGIN:VEVENT",
        f"UID:{uid}",
    ]
    for att in attendees:
        lines.append(_attendee_line(att))
    lines.extend(["END:VEVENT", "END:VCALENDAR"])
    return "\r\n".join(lines)


def invite_ics(
    uid: str,
    summary: str,
    location: str,
    description: str,
    start: datetime,
    end: datetime,
    all_day: bool,
    organizer: str,
    attendees: list[Attendee],
) -> str:
    dtstamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dtstart, dtend = _event_dates(start, end, all_day)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//proton-cli//EN",
        "METHOD:REQUEST",
        "CALSCALE:GREGORIAN",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{dtstamp}",
        dtstart,
        dtend,
        f"SUMMARY:{summary}",
    ]
    if location:
        lines.append(f"LOCATION:{location}")
    if description:
        lines.append(f"DESCRIPTION:{description}")
    if organizer:
        lines.append(f"ORGANIZER;CN={organizer}:mailto:{organizer}")
    for att in attendees:
        lines.append(_attendee_line(att))
    lines.extend(["SEQUENCE:0", "END:VEVENT", "END:VCALENDAR"])
    return "\r\n".join(lines)


def reply_ics(
    uid: str,
    summary: str,
    location: str,
    organizer: str,
    attendee_email: str,
    partstat: str,
    start: datetime,
    end: datetime,
    all_day: bool,
    proton_reply: bool,
) -> str:
    dtstamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dtstart, dtend = _event_dates(start, end, all_day)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//proton-cli//EN",
        "METHOD:REPLY",
        "CALSCALE:GREGORIAN",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{dtstamp}",
        dtstart,
        dtend,
    ]
    if summary:
        lines.append(f"SUMMARY:{summary}")
    if location:
        lines.append(f"LOCATION:{location}")
    if organizer:
        lines.append(f"ORGANIZER;CN={organizer}:mailto:{organizer}")
    if proton_reply:
        lines.append("X-PM-PROTON-REPLY;TYPE=boolean:true")
    lines.append(f"ATTENDEE;PARTSTAT={partstat}:mailto:{attendee_email}")
    lines.extend(["SEQUENCE:0", "END:VEVENT", "END:VCALENDAR"])
    return "\r\n".join(lines)


def parse_time(value: str) -> datetime:
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    ):
        try:
            parsed = datetime.strptime(value, fmt)
            if parsed.tzinfo is None:
                return parsed
            return parsed.astimezone()
        except ValueError:
            continue
    raise ValueError(f"unrecognized time format: {value}")


def parse_duration(value: str) -> timedelta:
    match = re.fullmatch(r"(\d+)([smhd])", value.strip())
    if not match:
        raise ValueError(f"invalid duration {value!r}")
    amount = int(match.group(1))
    unit = match.group(2)
    if unit == "s":
        return timedelta(seconds=amount)
    if unit == "m":
        return timedelta(minutes=amount)
    if unit == "h":
        return timedelta(hours=amount)
    return timedelta(days=amount)


def ical_trigger(duration: str) -> str:
    delta = parse_duration(duration)
    if delta <= timedelta(0):
        raise ValueError("must be positive")
    if delta % timedelta(days=1) == timedelta(0):
        return f"-P{int(delta.days)}D"
    return f"-PT{int(delta.total_seconds() // 60)}M"


def build_reminders(reminders: list[str]) -> list[dict[str, object]]:
    if not reminders:
        return []
    out: list[dict[str, object]] = []
    for reminder in reminders:
        out.append({"Type": 1, "Trigger": ical_trigger(reminder)})
    return out


@dataclass
class SignedEmail:
    address: str
    key_values: list[str] = dc_field(default_factory=list)
    encrypt: bool | None = None
    sign: bool | None = None
    scheme: str = ""


@dataclass
class SignedContact:
    name: str
    uid: str
    emails: list[SignedEmail] = dc_field(default_factory=list)

    def find_email(self, addr: str) -> SignedEmail | None:
        want = canonical_email(addr)
        for entry in self.emails:
            if canonical_email(entry.address) == want:
                return entry
        return None


@dataclass
class _VcardLine:
    group: str
    field: str
    params: str
    value: str


def _parse_vcard_line(raw: str) -> _VcardLine | None:
    line = raw.strip()
    colon = line.find(":")
    if colon < 0:
        return None
    name, value = line[:colon], line[colon + 1 :]
    field_name, params = name, ""
    if ";" in name:
        field_name, params = name.split(";", 1)
    group = ""
    if "." in field_name:
        group, field_name = field_name.split(".", 1)
    return _VcardLine(group=group, field=field_name.upper(), params=params, value=value)


def email_group(text: str, email: str) -> str:
    want = canonical_email(email)
    for raw in text.replace("\r\n", "\n").split("\n"):
        parsed = _parse_vcard_line(raw)
        if parsed and parsed.field == "EMAIL" and parsed.group:
            if canonical_email(parsed.value) == want:
                return parsed.group
    return ""


def group_values(text: str, group: str, field_name: str) -> list[str]:
    field_name = field_name.upper()
    found: list[tuple[int, str]] = []
    for index, raw in enumerate(text.replace("\r\n", "\n").split("\n")):
        parsed = _parse_vcard_line(raw)
        if parsed and parsed.group == group and parsed.field == field_name:
            pref = _pref_param(parsed.params, index)
            found.append((pref, parsed.value))
    found.sort(key=lambda item: item[0])
    return [value for _, value in found]


def group_value(text: str, group: str, field_name: str) -> str:
    values = group_values(text, group, field_name)
    return values[0] if values else ""


def _pref_param(params: str, doc_index: int) -> int:
    for part in params.split(";"):
        if part.upper().startswith("PREF="):
            try:
                return int(part.split("=", 1)[1].strip())
            except ValueError:
                pass
    return 1_000_000 + doc_index


def parse_signed_vcard(text: str) -> SignedContact:
    contact = SignedContact(name=field(text, "FN"), uid=field(text, "UID"))
    seen: set[str] = set()
    for raw in text.replace("\r\n", "\n").split("\n"):
        parsed = _parse_vcard_line(raw)
        if not parsed or parsed.field != "EMAIL" or not parsed.group or parsed.group in seen:
            continue
        seen.add(parsed.group)
        entry = SignedEmail(
            address=parsed.value,
            key_values=group_values(text, parsed.group, "KEY"),
            scheme=group_value(text, parsed.group, "X-PM-SCHEME"),
        )
        encrypt_raw = group_value(text, parsed.group, "X-PM-ENCRYPT")
        if encrypt_raw:
            entry.encrypt = encrypt_raw.strip().lower() == "true"
        sign_raw = group_value(text, parsed.group, "X-PM-SIGN")
        if sign_raw:
            entry.sign = sign_raw.strip().lower() == "true"
        contact.emails.append(entry)
    return contact


def build_signed_vcard(contact: SignedContact) -> str:
    lines = ["BEGIN:VCARD", "VERSION:4.0", f"FN:{contact.name}", f"UID:{contact.uid}"]
    index = 0
    for entry in contact.emails:
        if not entry.address:
            continue
        index += 1
        group = f"item{index}"
        lines.append(f"{group}.EMAIL;PREF={index}:{entry.address}")
        for pref, key_value in enumerate(entry.key_values, start=1):
            lines.append(f"{group}.KEY;PREF={pref}:{key_value}")
        if entry.encrypt is not None:
            lines.append(f"{group}.X-PM-ENCRYPT:{str(entry.encrypt).lower()}")
        if entry.sign is not None:
            lines.append(f"{group}.X-PM-SIGN:{str(entry.sign).lower()}")
        if entry.scheme:
            lines.append(f"{group}.X-PM-SCHEME:{entry.scheme}")
    lines.append("END:VCARD")
    return "\r\n".join(lines)
