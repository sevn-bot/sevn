"""Proton Calendar operations."""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from pgpy import PGPKey, PGPMessage

from proton_cli.account.keys import persist_unlock, use_unlocked_key
from proton_cli.crypto import cards as card_crypto
from proton_cli.crypto import ical as ical_crypto
from proton_cli.errors import NotFound
from proton_cli.proton.client import Client, Request
from proton_cli.ref import pick
from proton_cli.service.drive import blocks

if TYPE_CHECKING:
    from proton_cli.account.keys import Unlocked

_logger = logging.getLogger(__name__)

PARTSTAT_NEEDS_ACTION = 0
PARTSTAT_TENTATIVE = 1
PARTSTAT_DECLINED = 2
PARTSTAT_ACCEPTED = 3


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
class EventInput:
    title: str
    location: str = ""
    description: str = ""
    start: datetime | None = None
    end: datetime | None = None
    all_day: bool = False
    rrule: str = ""
    reminders: list[str] | None = None
    attendees: list[str] | None = None


@dataclass
class Invite:
    ics: str
    recipients: list[str]
    subject: str


@dataclass
class EventResult:
    id: str = ""
    invite: Invite | None = None


@dataclass
class Reply:
    ics: str
    recipients: list[str]
    subject: str
    body: str


@dataclass
class RespondResult:
    title: str = ""
    status: str = ""
    reply: Reply | None = None
    notify_error: str = ""


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

    def event_create(
        self, unlocked: Unlocked, calendar_id: str, event_in: EventInput
    ) -> EventResult:
        keys = self._unlock_calendar(unlocked, calendar_id)
        notifs = ical_crypto.build_reminders(event_in.reminders or [])
        organizer = keys.email if event_in.attendees else ""
        uid = ical_crypto.event_uid()
        signed = ical_crypto.signed_vevent(
            uid,
            event_in.start or datetime.now(UTC),
            event_in.end or datetime.now(UTC),
            event_in.all_day,
            0,
            event_in.rrule,
            organizer,
        )
        encrypted = ical_crypto.encrypted_vevent(
            event_in.title,
            event_in.location,
            event_in.description,
        )
        signed_card, enc_card, key_packet, session_key = card_crypto.encrypt_and_sign_card_split(
            signed,
            encrypted,
            keys.cal_key,
            keys.addr_key,
        )
        event: dict[str, object] = {
            "Permissions": 63,
            "IsOrganizer": 1,
            "SharedKeyPacket": key_packet,
            "SharedEventContent": [signed_card, enc_card],
            "Notifications": notifs,
            "Color": None,
        }
        invite: Invite | None = None
        if event_in.attendees:
            atts, clear, added, external = self._build_attendees(
                uid, event_in.attendees, session_key
            )
            att_card = card_crypto.encrypt_part_with_session_key(
                ical_crypto.attendees_vevent(uid, atts),
                session_key,
                keys.addr_key,
            )
            event["AttendeesEventContent"] = [att_card]
            event["Attendees"] = clear
            if added:
                event["AddedProtonAttendees"] = added
            if external:
                invite = Invite(
                    ics=ical_crypto.invite_ics(
                        uid,
                        event_in.title,
                        event_in.location,
                        event_in.description,
                        event_in.start or datetime.now(UTC),
                        event_in.end or datetime.now(UTC),
                        event_in.all_day,
                        organizer,
                        atts,
                    ),
                    recipients=external,
                    subject=f"Invitation: {event_in.title}",
                )
        payload: dict = {}
        self._client.decode(
            Request(
                method="PUT",
                path=f"/calendar/v1/{calendar_id}/events/sync",
                body={"MemberID": keys.member_id, "Events": [{"Overwrite": 0, "Event": event}]},
            ),
            payload,
        )
        result = EventResult(invite=invite)
        responses = payload.get("Responses") or []
        if responses:
            result.id = str((responses[0].get("Response") or {}).get("Event", {}).get("ID", ""))
        return result

    def event_respond(
        self,
        unlocked: Unlocked,
        calendar_id: str,
        event_id: str,
        status: int,
    ) -> RespondResult:
        payload: dict = {}
        self._client.decode(
            Request(method="GET", path=f"/calendar/v1/{calendar_id}/events/{event_id}"),
            payload,
        )
        raw = payload.get("Event") or {}
        if int(raw.get("IsOrganizer", 0) or 0) == 1:
            raise ValueError("you are the organizer of this event; RSVP is for attendees")
        uid = str(raw.get("UID", ""))
        attendees_info = raw.get("AttendeesInfo") or {}
        attendees = attendees_info.get("Attendees") or []
        attendee_id, self_email, found = self._find_self_attendee(uid, unlocked, attendees)
        if not found and int(attendees_info.get("MoreAttendees", 0) or 0) == 1:
            attendee_id, self_email, found = self._find_self_attendee_paged(
                calendar_id,
                event_id,
                uid,
                unlocked,
            )
        if not found:
            raise NotFound("attendee record for you on this event")
        self._client.decode(
            Request(
                method="PUT",
                path=f"/calendar/v1/{calendar_id}/events/{event_id}/attendees/{attendee_id}",
                body={"Status": status, "UpdateTime": int(datetime.now(UTC).timestamp())},
            ),
        )
        result = RespondResult(status=_status_word(status))
        try:
            keys = self._unlock_calendar(unlocked, calendar_id)
            packet = str(raw.get("SharedKeyPacket", ""))
            dec_key = keys.cal_key
            if not packet and raw.get("AddressKeyPacket"):
                packet = str(raw.get("AddressKeyPacket", ""))
                addr_keys = unlocked.addr_keys.get(str(raw.get("AddressID", "")))
                if addr_keys:
                    dec_key = addr_keys[0]
            title, location, _, _, organizer = self._decrypt_event_cards(
                raw.get("SharedEvents") or raw.get("SharedEventContent") or [],
                packet,
                dec_key,
                keys.addr_key,
            )
            result.title = title
            if organizer and organizer.lower() != self_email.lower():
                start = datetime.fromtimestamp(int(raw.get("StartTime", 0) or 0), tz=UTC)
                end = datetime.fromtimestamp(int(raw.get("EndTime", 0) or 0), tz=UTC)
                result.reply = Reply(
                    ics=ical_crypto.reply_ics(
                        uid,
                        title,
                        location,
                        organizer,
                        self_email,
                        _partstat_ics(status),
                        start,
                        end,
                        int(raw.get("FullDay", 0) or 0) == 1,
                        int(raw.get("IsProtonProtonInvite", 0) or 0) == 1,
                    ),
                    recipients=[organizer],
                    subject=_reply_subject(start, int(raw.get("FullDay", 0) or 0) == 1),
                    body=_reply_body(self_email, status, title),
                )
        except Exception as exc:
            # RSVP status update already succeeded; surface notify build failures to the CLI.
            result.notify_error = str(exc)
        return result

    def resolve_event(self, unlocked: Unlocked, args: list[str]) -> tuple[str, str]:
        if len(args) == 2:
            return args[0], args[1]
        needle = args[0]
        start, end = default_range()
        matches: list[tuple[str, str, str]] = []
        for cal in self.calendars_list():
            try:
                events = self.events_list(unlocked, cal.id, start, end)
            except Exception as exc:
                _logger.warning(
                    "calendar resolve_event list failed calendar_id=%s: %s",
                    cal.id,
                    exc,
                )
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
            with use_unlocked_key(addr_key):
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
                cal_key = persist_unlock(locked, cal_pass)
                break
            except Exception:
                continue
        if cal_key is None:
            raise ValueError("failed to unlock calendar keys")
        return _CalKeys(cal_key=cal_key, addr_key=addr_key, member_id=member_id, email=email)

    def _build_attendees(
        self,
        uid: str,
        emails: list[str],
        session_key: blocks.SessionKey,
    ) -> tuple[
        list[ical_crypto.Attendee], list[dict[str, object]], list[dict[str, object]], list[str]
    ]:
        seen: set[str] = set()
        atts: list[ical_crypto.Attendee] = []
        clear: list[dict[str, object]] = []
        added: list[dict[str, object]] = []
        external: list[str] = []
        for raw in emails:
            email = raw.strip()
            if not email:
                continue
            canon = ical_crypto.canonical_email(email)
            if canon in seen:
                continue
            seen.add(canon)
            token = ical_crypto.attendee_token(uid, email)
            atts.append(ical_crypto.Attendee(email=email, token=token))
            clear.append({"Token": token, "Status": 0})
            key_payload: dict = {}
            self._client.decode(
                Request(
                    method="GET",
                    path="/core/v4/keys/all",
                    query={"Email": email, "InternalOnly": "0"},
                ),
                key_payload,
            )
            address = key_payload.get("Address") or {}
            keys = address.get("Keys") or []
            if keys:
                rec_key, _ = PGPKey.from_blob(str(keys[0].get("PublicKey", "")))
                kp = blocks.encrypt_session_key_packet(rec_key, session_key)
                added.append({"Email": email, "AddressKeyPacket": base64.b64encode(kp).decode()})
            else:
                external.append(email)
        return atts, clear, added, external

    def _find_self_attendee(
        self,
        uid: str,
        unlocked: Unlocked,
        attendees: list[dict],
    ) -> tuple[str, str, bool]:
        token_to_email = {
            ical_crypto.attendee_token(uid, addr.email): addr.email for addr in unlocked.addresses
        }
        for attendee in attendees:
            token = str(attendee.get("Token", ""))
            if token in token_to_email:
                return str(attendee.get("ID", "")), token_to_email[token], True
        return "", "", False

    def _find_self_attendee_paged(
        self,
        calendar_id: str,
        event_id: str,
        uid: str,
        unlocked: Unlocked,
    ) -> tuple[str, str, bool]:
        page = 1
        while True:
            payload: dict = {}
            self._client.decode(
                Request(
                    method="GET",
                    path=f"/calendar/v1/{calendar_id}/events/{event_id}/attendees",
                    query={"Page": str(page)},
                ),
                payload,
            )
            attendee_id, email, found = self._find_self_attendee(
                uid,
                unlocked,
                payload.get("Attendees") or [],
            )
            if found:
                return attendee_id, email, True
            if int(payload.get("MoreAttendees", 0) or 0) != 1:
                return "", "", False
            page += 1

    def _decrypt_event_cards(
        self,
        cards: list[dict],
        key_packet_b64: str,
        decryption_key: PGPKey,
        verification_key: PGPKey,
    ) -> tuple[str, str, str, str, str]:
        key_packet = base64.b64decode(key_packet_b64) if key_packet_b64 else None
        decrypted = card_crypto.decrypt_cards(cards, decryption_key, verification_key, key_packet)
        joined = "\n".join(decrypted)
        return (
            ical_crypto.field(joined, "SUMMARY"),
            ical_crypto.field(joined, "LOCATION"),
            ical_crypto.field(joined, "DESCRIPTION"),
            ical_crypto.field(joined, "RRULE"),
            ical_crypto.field(joined, "ORGANIZER").split("mailto:")[-1],
        )

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


def status_from_flag(value: str) -> int:
    match value.strip().lower():
        case "accept":
            return PARTSTAT_ACCEPTED
        case "tentative":
            return PARTSTAT_TENTATIVE
        case "decline":
            return PARTSTAT_DECLINED
    raise ValueError(f"invalid --status {value!r} (use: accept, tentative, decline)")


def _partstat_ics(status: int) -> str:
    if status == PARTSTAT_ACCEPTED:
        return "ACCEPTED"
    if status == PARTSTAT_TENTATIVE:
        return "TENTATIVE"
    if status == PARTSTAT_DECLINED:
        return "DECLINED"
    return "NEEDS-ACTION"


def _status_word(status: int) -> str:
    if status == PARTSTAT_ACCEPTED:
        return "accepted"
    if status == PARTSTAT_TENTATIVE:
        return "tentatively accepted"
    if status == PARTSTAT_DECLINED:
        return "declined"
    return "did not answer"


def _reply_body(self_email: str, status: int, title: str) -> str:
    return f"{self_email} {_status_word(status)} your invitation to {title}"


def _reply_subject(start: datetime, all_day: bool) -> str:
    if all_day:
        return f"Re: Invitation for an event on {start.strftime('%Y-%m-%d')}"
    return f"Re: Invitation for an event starting on {start.strftime('%Y-%m-%d %H:%M')}"
