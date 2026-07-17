"""Tests for calendar/contacts helpers."""

from __future__ import annotations

from typer.testing import CliRunner

from proton_cli.cli.root import app as root_app
from proton_cli.crypto import vcard as vcard_crypto
from proton_cli.service.calendar.service import CalendarService, default_range
from proton_cli.service.contacts.service import ContactsService


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
        def decode(self, req, out):
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
