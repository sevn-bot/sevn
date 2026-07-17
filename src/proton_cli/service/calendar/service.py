"""Proton Calendar operations."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from pgpy import PGPKey, PGPMessage

from proton_cli.crypto import cards as card_crypto
from proton_cli.crypto import ical as ical_crypto
from proton_cli.errors import NotFound
from proton_cli.proton.client import Client, Request
from proton_cli.ref import pick

if TYPE_CHECKING:
    from proton_cli.account.keys import Unlocked


@dataclass
class Calendar:
    id: str
    name: str = ""
    color: str = ""
    description: str = ""
    member_count: int = 0


@dataclass
class Event:
    id: str
    calendar_id: str
    title: str = ""
    location: str = ""
    description: str = ""
    start: datetime | None = None
    end: datetime | None = None
    all_day: bool = False
    uid: str = ""


@dataclass
class _CalKeys:
    cal_key: PGPKey
    addr_key: PGPKey
    member_id: str
    email: str


class CalendarService:
    def __init__(self, client: Client) -> None:
        self._client = client

    def calendars_list(self) -> list[Calendar]:
        payload: dict = {}
        self._client.decode(Request(method="GET", path="/calendar/v1"), payload)
        out: list[Calendar] = []
        for raw in payload.get("Calendars") or []:
            members = raw.get("Members") or []
            name = color = desc = ""
            if members:
                m0 = members[0]
                name = str(m0.get("Name", ""))
                color = str(m0.get("Color", ""))
                desc = str(m0.get("Description", ""))
            out.append(
                Calendar(
                    id=str(raw.get("ID", "")),
                    name=name,
                    color=color,
                    description=desc,
                    member_count=len(members),
                )
            )
        return out

    def resolve_calendar_id(self, name_or_id: str) -> str:
        cals = self.calendars_list()
        if not name_or_id:
            if not cals:
                raise NotFound("calendar")
            return cals[0].id
        for cal in cals:
            if cal.id == name_or_id:
                return cal.id
        for cal in cals:
            if cal.name.lower() == name_or_id.lower():
                return cal.id
        raise NotFound("calendar", name_or_id)

    def events_list(
        self,
        unlocked: Unlocked,
        calendar_id: str,
        start: datetime,
        end: datetime,
    ) -> list[Event]:
        keys = self._unlock_calendar(unlocked, calendar_id)
        payload: dict = {}
        self._client.decode(
            Request(
                method="GET",
                path=f"/calendar/v1/{calendar_id}/events",
                query={
                    "Start": str(int(start.timestamp())),
                    "End": str(int(end.timestamp())),
                    "Timezone": "UTC",
                    "Type": "0",
                },
            ),
            payload,
        )
        out: list[Event] = []
        for raw in payload.get("Events") or []:
            out.append(self._event_from_raw(raw, keys))
        return out

    def event_get(self, unlocked: Unlocked, calendar_id: str, event_id: str) -> Event:
        keys = self._unlock_calendar(unlocked, calendar_id)
        payload: dict = {}
        self._client.decode(
            Request(method="GET", path=f"/calendar/v1/{calendar_id}/events/{event_id}"),
            payload,
        )
        return self._event_from_raw(payload.get("Event") or {}, keys)

    def event_delete(self, unlocked: Unlocked, calendar_id: str, event_id: str) -> None:
        keys = self._unlock_calendar(unlocked, calendar_id)
        self._client.decode(
            Request(
                method="PUT",
                path=f"/calendar/v1/{calendar_id}/events/sync",
                body={"MemberID": keys.member_id, "Events": [{"ID": event_id}]},
            ),
        )

    def resolve_event(self, unlocked: Unlocked, args: list[str]) -> tuple[str, str]:
        if len(args) == 2:
            return args[0], args[1]
        needle = args[0]
        start, end = default_range()
        matches: list[tuple[str, str, str]] = []
        for cal in self.calendars_list():
            try:
                events = self.events_list(unlocked, cal.id, start, end)
            except Exception:
                continue
            for ev in events:
                if ev.title and needle.lower() in ev.title.lower():
                    matches.append((cal.id, ev.id, f"{ev.start} {ev.title}"))
        if not matches:
            raise NotFound("event", needle)

        @dataclass
        class _Match:
            cal: str
            ev: str
            label: str

        items = [_Match(cal, ev, label) for cal, ev, label in matches]
        chosen = pick(
            "event",
            needle,
            items,
            lambda m: m.ev,
            lambda m: m.label,
        )
        return chosen.cal, chosen.ev

    def _unlock_calendar(self, unlocked: Unlocked, calendar_id: str) -> _CalKeys:
        mem_payload: dict = {}
        self._client.decode(
            Request(method="GET", path=f"/calendar/v1/{calendar_id}/members"),
            mem_payload,
        )
        addr_key: PGPKey | None = None
        member_id = ""
        email = ""
        for member in mem_payload.get("Members") or []:
            aid = str(member.get("AddressID", ""))
            keys = unlocked.addr_keys.get(aid)
            if keys:
                addr_key = keys[0]
                member_id = str(member.get("ID", ""))
                email = str(member.get("Email", ""))
                break
        if addr_key is None:
            raise ValueError(f"no matching address key for calendar {calendar_id}")

        pass_payload: dict = {}
        self._client.decode(
            Request(method="GET", path=f"/calendar/v1/{calendar_id}/passphrase"),
            pass_payload,
        )
        cal_pass: bytes | None = None
        for mp in (pass_payload.get("Passphrase") or {}).get("MemberPassphrases") or []:
            if str(mp.get("MemberID", "")) != member_id:
                continue
            msg = PGPMessage.from_blob(str(mp.get("Passphrase", "")))
            with addr_key.unlock(None):
                dec = addr_key.decrypt(msg)
            cal_pass = dec.message.encode() if isinstance(dec.message, str) else bytes(dec.message)
            break
        if cal_pass is None:
            raise ValueError(f"no passphrase found for member {member_id}")

        key_payload: dict = {}
        self._client.decode(
            Request(method="GET", path=f"/calendar/v1/{calendar_id}/keys"),
            key_payload,
        )
        cal_key: PGPKey | None = None
        for row in key_payload.get("Keys") or []:
            locked, _ = PGPKey.from_blob(str(row.get("PrivateKey", "")))
            try:
                with locked.unlock(cal_pass):
                    cal_key = locked
                    break
            except Exception:
                continue
        if cal_key is None:
            raise ValueError("failed to unlock calendar keys")
        return _CalKeys(cal_key=cal_key, addr_key=addr_key, member_id=member_id, email=email)

    def _event_from_raw(self, raw: dict, keys: _CalKeys) -> Event:
        cards = raw.get("SharedEvents") or raw.get("SharedEventContent") or []
        key_packet_b64 = str(raw.get("SharedKeyPacket", ""))
        key_packet = base64.b64decode(key_packet_b64) if key_packet_b64 else None
        decrypted = card_crypto.decrypt_cards(cards, keys.cal_key, keys.addr_key, key_packet)
        joined = "\n".join(decrypted)
        start_ts = int(raw.get("StartTime", 0) or 0)
        end_ts = int(raw.get("EndTime", 0) or 0)
        return Event(
            id=str(raw.get("ID", "")),
            calendar_id=str(raw.get("CalendarID", "")),
            title=ical_crypto.field(joined, "SUMMARY"),
            location=ical_crypto.field(joined, "LOCATION"),
            description=ical_crypto.field(joined, "DESCRIPTION"),
            start=datetime.fromtimestamp(start_ts, tz=UTC),
            end=datetime.fromtimestamp(end_ts, tz=UTC),
            all_day=int(raw.get("FullDay", 0) or 0) == 1,
            uid=str(raw.get("UID", "")),
        )


def default_range() -> tuple[datetime, datetime]:
    now = datetime.now(tz=UTC)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=30)
