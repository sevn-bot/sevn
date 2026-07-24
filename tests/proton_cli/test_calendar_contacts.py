"""Tests for calendar/contacts helpers, services, and card decrypt.

Exports:
    test_calendar_and_contacts_commands_registered
    test_vcard_signed_roundtrip
    test_default_range
    test_calendar_list_mock
    test_contacts_service_init
    test_contacts_list_decrypts_fields
    test_contacts_list_logs_dropped_rows
    test_contacts_get_create_delete
    test_contacts_create_empty_response_raises
    test_calendar_events_list_get_delete
    test_resolve_event_logs_partial_failures
    test_decrypt_cards_encrypted_and_signed_types
    test_decrypt_cards_unknown_type_surfaced
"""

from __future__ import annotations

import base64
import logging
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from pgpy import PGPUID, PGPKey, PGPMessage
from pgpy.constants import (
    CompressionAlgorithm,
    HashAlgorithm,
    KeyFlags,
    PubKeyAlgorithm,
    SymmetricKeyAlgorithm,
)
from typer.testing import CliRunner

from proton_cli.cli.root import app as root_app
from proton_cli.crypto import cards as card_crypto
from proton_cli.crypto import vcard as vcard_crypto
from proton_cli.errors import NotFound
from proton_cli.service.calendar.service import Calendar, CalendarService, Event, default_range
from proton_cli.service.contacts.service import ContactsService, NewContact
from proton_cli.service.drive import blocks


def test_calendar_and_contacts_commands_registered() -> None:
    runner = CliRunner()
    cal = runner.invoke(root_app, ["calendar", "--help"])
    con = runner.invoke(root_app, ["contacts", "--help"])
    assert cal.exit_code == 0
    assert con.exit_code == 0
    assert "events" in cal.output
    assert "list" in con.output


def test_vcard_signed_roundtrip() -> None:
    text = vcard_crypto.signed_vcard("Alice", ["a@x.com"], "uid-1")
    assert vcard_crypto.field(text, "FN") == "Alice"
    assert vcard_crypto.fields(text, "EMAIL") == ["a@x.com"]


def test_default_range() -> None:
    start, end = default_range()
    assert end > start


def test_calendar_list_mock() -> None:
    class FakeClient:
        def decode(self, req: Any, out: dict[str, Any]) -> None:
            out.clear()
            out.update(
                {
                    "Calendars": [
                        {
                            "ID": "cal-1",
                            "Members": [{"Name": "Work", "Color": "#f00", "Description": ""}],
                        }
                    ]
                }
            )

    rows = CalendarService(FakeClient()).calendars_list()
    assert rows[0].id == "cal-1"
    assert rows[0].name == "Work"


def test_contacts_service_init() -> None:
    assert ContactsService(object())._client is not None


def _rsa_key() -> PGPKey:
    key = PGPKey.new(PubKeyAlgorithm.RSAEncryptOrSign, 2048)
    uid = PGPUID.new("Test", email="t@example.com")
    key.add_uid(
        uid,
        usage={KeyFlags.EncryptCommunications, KeyFlags.EncryptStorage, KeyFlags.Sign},
        hashes=[HashAlgorithm.SHA256],
        ciphers=[SymmetricKeyAlgorithm.AES256],
        compression=[CompressionAlgorithm.ZLIB],
    )
    return key


def test_contacts_list_decrypts_fields() -> None:
    """``list_contacts`` decrypts signed cards into Contact fields."""
    key = _rsa_key()
    signed = vcard_crypto.signed_vcard("Alice", ["a@x.com"], "uid-alice")

    class FakeClient:
        def decode(self, req: Any, out: dict[str, Any]) -> None:
            out.clear()
            out.update(
                {
                    "Contacts": [
                        {
                            "ID": "c1",
                            "Cards": [
                                {
                                    "Type": card_crypto.CARD_SIGNED,
                                    "Data": signed,
                                    "Signature": "",
                                }
                            ],
                        }
                    ]
                }
            )

    unlocked = MagicMock()
    unlocked.user_keys = [key]
    rows = ContactsService(FakeClient()).list_contacts(unlocked)
    assert rows[0].id == "c1"
    assert rows[0].name == "Alice"
    assert rows[0].emails == ["a@x.com"]


def test_contacts_list_logs_dropped_rows(caplog: pytest.LogCaptureFixture) -> None:
    """Decrypt failures for a contact row log at warning and skip the row."""
    key = _rsa_key()

    class FakeClient:
        def decode(self, req: Any, out: dict[str, Any]) -> None:
            out.clear()
            out.update(
                {
                    "Contacts": [
                        {"ID": "bad-1", "Cards": [{"Type": 1, "Data": "not-pgp"}]},
                        {
                            "ID": "ok-1",
                            "Cards": [
                                {
                                    "Type": card_crypto.CARD_SIGNED,
                                    "Data": vcard_crypto.signed_vcard("Ok", ["ok@x.com"], "uid-ok"),
                                    "Signature": "",
                                }
                            ],
                        },
                    ]
                }
            )

    unlocked = MagicMock()
    unlocked.user_keys = [key]
    with caplog.at_level(logging.WARNING):
        rows = ContactsService(FakeClient()).list_contacts(unlocked)
    assert [r.id for r in rows] == ["ok-1"]
    assert any("decrypt" in r.message.lower() and "bad-1" in r.message for r in caplog.records)


def test_contacts_get_create_delete() -> None:
    """``get_contact`` / ``create_contact`` / ``delete_contacts`` assert API shapes."""
    key = _rsa_key()
    signed = vcard_crypto.signed_vcard("Bob", ["b@x.com"], "uid-bob")
    calls: list[Any] = []

    class FakeClient:
        def decode(self, req: Any, out: dict[str, Any] | None = None) -> None:
            calls.append(req)
            if out is None:
                return
            out.clear()
            if req.method == "GET":
                out.update(
                    {
                        "Contact": {
                            "ID": "c-get",
                            "Cards": [
                                {
                                    "Type": card_crypto.CARD_SIGNED,
                                    "Data": signed,
                                    "Signature": "",
                                }
                            ],
                        }
                    }
                )
            elif req.method == "POST":
                out.update(
                    {
                        "Responses": [
                            {"Response": {"Contact": {"ID": "c-new"}}},
                        ]
                    }
                )

    unlocked = MagicMock()
    unlocked.user_keys = [key]
    svc = ContactsService(FakeClient())

    got = svc.get_contact(unlocked, "c-get")
    assert got.name == "Bob"
    assert got.emails == ["b@x.com"]

    cid = svc.create_contact(unlocked, NewContact(name="Bob", emails=["b@x.com"]))
    assert cid == "c-new"
    create_req = next(c for c in calls if c.method == "POST")
    assert create_req.path == "/contacts/v4/contacts"
    assert "Contacts" in create_req.body
    assert create_req.body["Contacts"][0]["Cards"]

    svc.delete_contacts(["c-new"])
    delete_req = next(c for c in calls if c.path.endswith("/delete"))
    assert delete_req.method == "PUT"
    assert delete_req.body == {"IDs": ["c-new"]}


def test_contacts_create_empty_response_raises() -> None:
    """Empty ``Responses`` must raise — CLI must not report false success (D7)."""
    key = _rsa_key()

    class FakeClient:
        def decode(self, req: Any, out: dict[str, Any]) -> None:
            out.clear()
            out.update({"Responses": []})

    unlocked = MagicMock()
    unlocked.user_keys = [key]
    with pytest.raises(ValueError, match="empty Responses"):
        ContactsService(FakeClient()).create_contact(
            unlocked,
            NewContact(name="Bob", emails=["b@x.com"]),
        )


def test_calendar_events_list_get_delete() -> None:
    """``events_list`` / ``event_get`` / ``event_delete`` drive service side effects."""
    calls: list[Any] = []
    start = datetime(2026, 7, 1, tzinfo=UTC)
    end = datetime(2026, 7, 31, tzinfo=UTC)
    keys = MagicMock()
    keys.member_id = "mem-1"
    event = Event(id="e1", calendar_id="cal-1", title="Standup")

    class FakeClient:
        def decode(self, req: Any, out: dict[str, Any] | None = None) -> None:
            calls.append(req)
            if out is None:
                return
            out.clear()
            if req.method == "GET" and req.path.endswith("/events"):
                out.update({"Events": [{"ID": "e1"}]})
            elif req.method == "GET":
                out.update({"Event": {"ID": "e1"}})

    svc = CalendarService(FakeClient())
    unlocked = MagicMock()
    with (
        patch.object(svc, "_unlock_calendar", return_value=keys),
        patch.object(svc, "_event_from_raw", return_value=event),
    ):
        rows = svc.events_list(unlocked, "cal-1", start, end)
        assert rows[0].id == "e1"
        assert rows[0].title == "Standup"

        got = svc.event_get(unlocked, "cal-1", "e1")
        assert got.id == "e1"

        svc.event_delete(unlocked, "cal-1", "e1")

    delete_req = next(c for c in calls if c.method == "PUT")
    assert delete_req.path == "/calendar/v1/cal-1/events/sync"
    assert delete_req.body == {"MemberID": "mem-1", "Events": [{"ID": "e1"}]}


def test_resolve_event_logs_partial_failures(caplog: pytest.LogCaptureFixture) -> None:
    """Per-calendar unlock/list errors in ``resolve_event`` log at warning."""
    svc = CalendarService(MagicMock())
    unlocked = MagicMock()
    with (
        caplog.at_level(logging.WARNING),
        patch.object(
            svc,
            "calendars_list",
            return_value=[Calendar(id="cal-bad", name="Bad"), Calendar(id="cal-ok", name="Ok")],
        ),
        patch.object(
            svc,
            "events_list",
            side_effect=[
                RuntimeError("unlock failed"),
                [Event(id="e-ok", calendar_id="cal-ok", title="FindMe")],
            ],
        ),
    ):
        cal_id, ev_id = svc.resolve_event(unlocked, ["FindMe"])
    assert cal_id == "cal-ok"
    assert ev_id == "e-ok"
    assert any("resolve_event" in r.message and "cal-bad" in r.message for r in caplog.records)


def test_resolve_event_all_fail_raises_not_found(caplog: pytest.LogCaptureFixture) -> None:
    svc = CalendarService(MagicMock())
    with (
        caplog.at_level(logging.WARNING),
        patch.object(svc, "calendars_list", return_value=[Calendar(id="cal-1", name="A")]),
        patch.object(svc, "events_list", side_effect=RuntimeError("boom")),
        pytest.raises(NotFound),
    ):
        svc.resolve_event(MagicMock(), ["Nope"])
    assert any("resolve_event" in r.message for r in caplog.records)


def test_decrypt_cards_encrypted_and_signed_types() -> None:
    """``decrypt_cards`` covers CARD_ENCRYPTED / CARD_ENCRYPTED_SIGNED + session-key packet."""
    key = _rsa_key()
    pub = key.pubkey

    msg = PGPMessage.new("plain-encrypted")
    enc = pub.encrypt(msg)
    out_enc = card_crypto.decrypt_cards(
        [{"Type": card_crypto.CARD_ENCRYPTED, "Data": str(enc)}],
        key,
        key,
    )
    assert out_enc == ["plain-encrypted"]

    signed_card = card_crypto.encrypt_and_sign_card("plain-signed", pub, key)
    out_signed = card_crypto.decrypt_cards([signed_card], key, key)
    assert out_signed == ["plain-signed"]

    sk = blocks.make_session_key()
    data_packet = blocks.encrypt_data_packet(b"SUMMARY:Meet\r\n", sk)
    with (
        patch(
            "proton_cli.crypto.cards.blocks.decrypt_session_key_packet",
            return_value=sk,
        ) as decrypt_sk,
        patch(
            "proton_cli.crypto.cards.blocks._packet_body",
            wraps=blocks._packet_body,
        ) as packet_body,
    ):
        out_pkt = card_crypto.decrypt_cards(
            [
                {
                    "Type": card_crypto.CARD_ENCRYPTED_SIGNED,
                    "Data": base64.b64encode(data_packet).decode(),
                }
            ],
            key,
            key,
            key_packet=b"\x00fake-key-packet",
        )
    assert out_pkt == ["SUMMARY:Meet\r\n"]
    decrypt_sk.assert_called_once()
    packet_body.assert_called()


def test_decrypt_cards_unknown_type_surfaced() -> None:
    key = _rsa_key()
    with pytest.raises(ValueError, match="unrecognized card type"):
        card_crypto.decrypt_cards([{"Type": 999, "Data": "raw"}], key, key)
