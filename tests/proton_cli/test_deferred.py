"""Tests for deferred proton-cli features (PR #45 / W11).

Exports:
    test_ical_signed_and_encrypted_vevent
    test_ical_trigger_and_reminders
    test_attendee_token_deterministic
    test_encrypt_data_packet_roundtrip
    test_status_from_flag
    test_build_mime_message_with_attachment
    test_python_drive_keygen
    test_hv_resolver_env_token
    test_hv_helper_missing
    test_vcard_grouped_signed_roundtrip
    test_calendar_events_create_respond_cli_mocked
    test_contacts_groups_and_pin_key_cli_mocked
    test_contacts_groups_service
    test_mail_send_attach_and_attachments_cli_mocked
    test_mail_attachments_list_service
    test_classify_recipient_uses_pinned_keys
    test_hv_helper_crash_logged
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from pgpy import PGPKey
from pgpy.constants import EllipticCurveOID, PubKeyAlgorithm
from typer.testing import CliRunner

from proton_cli.cli.root import app as root_app
from proton_cli.crypto import ical as ical_crypto
from proton_cli.hv import helper as hv_helper
from proton_cli.hv.resolver import cli_hv_resolver
from proton_cli.proton.errors import ErrHVUnavailable, HumanVerificationError
from proton_cli.service.calendar.service import status_from_flag
from proton_cli.service.contacts.service import ContactCrypto, ContactsService, Group
from proton_cli.service.drive import blocks
from proton_cli.service.drive.keygen import _generate_armored_locked_key_python
from proton_cli.service.mail import mime as mail_mime
from proton_cli.service.mail.service import PKG_CLEAR, PKG_INTERNAL, Attachment, MailService

runner = CliRunner()


def test_ical_signed_and_encrypted_vevent() -> None:
    start = datetime(2026, 7, 16, 10, 0, tzinfo=UTC)
    end = datetime(2026, 7, 16, 11, 0, tzinfo=UTC)
    uid = "uid@test"
    signed = ical_crypto.signed_vevent(uid, start, end, False, 0, "", "org@proton.me")
    encrypted = ical_crypto.encrypted_vevent("Title", "Room", "Notes")
    assert "UID:uid@test" in signed
    assert ical_crypto.field(encrypted, "SUMMARY") == "Title"


def test_ical_trigger_and_reminders() -> None:
    assert ical_crypto.ical_trigger("15m") == "-PT15M"
    reminders = ical_crypto.build_reminders(["15m", "1d"])
    assert len(reminders) == 2


def test_attendee_token_deterministic() -> None:
    token = ical_crypto.attendee_token("uid-1", "Alice@Proton.me")
    assert len(token) == 40


def test_encrypt_data_packet_roundtrip() -> None:
    PGPKey.new(PubKeyAlgorithm.ECDH, EllipticCurveOID.Curve25519)
    session_key = blocks.make_session_key()
    plain = b"SUMMARY:Meet"
    packet = blocks.encrypt_data_packet(plain, session_key)
    decrypted = blocks.decrypt_block(packet, session_key)
    assert decrypted == plain


def test_status_from_flag() -> None:
    from proton_cli.service.calendar.service import PARTSTAT_ACCEPTED

    assert status_from_flag("accept") == PARTSTAT_ACCEPTED
    with pytest.raises(ValueError, match="invalid --status"):
        status_from_flag("maybe")


def test_build_mime_message_with_attachment() -> None:
    body = mail_mime.build_mime_message(
        "hello",
        "text/plain",
        [mail_mime.PreparedAttachment(filename="a.txt", mime_type="text/plain", data=b"data")],
    )
    assert "multipart/mixed" in body
    assert "a.txt" in body


def test_python_drive_keygen() -> None:
    armored = _generate_armored_locked_key_python(b"test-passphrase-32-bytes-long!!!")
    assert "BEGIN PGP PRIVATE KEY BLOCK" in armored
    key, _ = PGPKey.from_blob(armored)
    with key.unlock(b"test-passphrase-32-bytes-long!!!"):
        assert key.is_unlocked


def test_hv_resolver_env_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROTON_HV_TOKEN", "tok-abc")
    token, kind = cli_hv_resolver(HumanVerificationError(token="x", web_url="https://example.com"))
    assert token == "tok-abc"
    assert kind == "captcha"


def test_hv_helper_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PROTON_HV_HELPER", raising=False)
    monkeypatch.setenv("PATH", "")
    with pytest.raises(hv_helper.HVUnavailableError):
        hv_helper.resolve_with_helper("challenge-token")


def test_vcard_grouped_signed_roundtrip() -> None:
    from proton_cli.crypto import vcard as vcard_crypto

    text = vcard_crypto.signed_vcard("Alice", ["a@x.com"], "uid-1")
    assert vcard_crypto.field(text, "FN") == "Alice"
    assert vcard_crypto.fields(text, "EMAIL") == ["a@x.com"]
    assert ical_crypto.email_group(text, "a@x.com") == "item1"


def test_calendar_events_create_respond_cli_mocked() -> None:
    """``calendar events create|respond`` drive service side effects (not --help)."""
    from proton_cli.service.calendar.service import EventResult, RespondResult

    with patch("proton_cli.cli.calendar_cmd._run") as run_app:
        app = MagicMock()
        app.dry_run = False
        app.unlock.return_value = MagicMock()
        app.calendar_svc.resolve_calendar_id.return_value = "cal-1"
        app.calendar_svc.event_create.return_value = EventResult(id="ev-1")
        app.renderer.format.value = "text"
        run_app.return_value = app
        created = runner.invoke(
            root_app,
            [
                "calendar",
                "events",
                "create",
                "--title",
                "Standup",
                "--start",
                "2026-07-21T10:00:00Z",
                "--calendar",
                "cal-1",
            ],
        )
    assert created.exit_code == 0
    app.calendar_svc.event_create.assert_called_once()
    create_args = app.calendar_svc.event_create.call_args.args
    assert create_args[1] == "cal-1"
    assert create_args[2].title == "Standup"

    with patch("proton_cli.cli.calendar_cmd._run") as run_app:
        app = MagicMock()
        app.dry_run = False
        app.unlock.return_value = MagicMock()
        app.calendar_svc.resolve_event.return_value = ("cal-1", "ev-1")
        app.calendar_svc.event_respond.return_value = RespondResult(
            status="ACCEPTED",
            title="Standup",
        )
        app.renderer.format.value = "text"
        run_app.return_value = app
        responded = runner.invoke(
            root_app,
            ["calendar", "events", "respond", "cal-1", "ev-1", "--status", "accept"],
        )
    assert responded.exit_code == 0
    app.calendar_svc.event_respond.assert_called_once()
    respond_args = app.calendar_svc.event_respond.call_args.args
    assert respond_args[1:3] == ("cal-1", "ev-1")


def test_contacts_groups_and_pin_key_cli_mocked() -> None:
    """``contacts groups *`` and ``pin-key`` / ``unpin-key`` invoke service mutators."""
    with patch("proton_cli.cli.contacts_cmd._run") as run_app:
        app = MagicMock()
        app.dry_run = False
        app.unlock.return_value = MagicMock()
        app.contacts_svc.groups_list.return_value = [Group(id="g1", name="Friends")]
        app.contacts_svc.group_create.return_value = "g-new"
        app.contacts_svc.resolve_contact.return_value = "c1"
        app.contacts_svc.get_contact.return_value = MagicMock(email="a@x.com")
        app.renderer.format.value = "text"
        run_app.return_value = app

        assert runner.invoke(root_app, ["contacts", "groups", "list"]).exit_code == 0
        app.contacts_svc.groups_list.assert_called_once()

        assert runner.invoke(root_app, ["contacts", "groups", "create", "Work"]).exit_code == 0
        app.contacts_svc.group_create.assert_called_once()

        assert (
            runner.invoke(
                root_app,
                ["contacts", "groups", "add", "g1", "c1"],
            ).exit_code
            == 0
        )
        app.contacts_svc.group_add.assert_called_once_with("g1", ["c1"])

        assert (
            runner.invoke(
                root_app,
                ["contacts", "groups", "remove", "g1", "c1"],
            ).exit_code
            == 0
        )
        app.contacts_svc.group_remove.assert_called_once_with("g1", ["c1"])

        assert runner.invoke(root_app, ["contacts", "groups", "delete", "g1"]).exit_code == 0
        app.contacts_svc.group_delete.assert_called_once_with("g1")

        with patch("proton_cli.cli.contacts_cmd.Path") as path_cls:
            path_cls.return_value.read_text.return_value = "-----BEGIN PGP PUBLIC KEY BLOCK-----\n"
            pinned = runner.invoke(
                root_app,
                ["contacts", "pin-key", "c1", "--key", "/tmp/key.asc"],
            )
        assert pinned.exit_code == 0
        app.contacts_svc.pin_key.assert_called_once()

        unpinned = runner.invoke(root_app, ["contacts", "unpin-key", "c1"])
        assert unpinned.exit_code == 0
        app.contacts_svc.unpin_key.assert_called_once()


def test_contacts_groups_service() -> None:
    """``groups_list`` / ``group_create`` map API payloads and POST bodies."""
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
                        "Labels": [
                            {"ID": "g1", "Name": "Friends", "Color": "#00f", "Type": 2},
                        ]
                    }
                )
            else:
                out.update({"Label": {"ID": "g-new"}})

    svc = ContactsService(FakeClient())
    rows = svc.groups_list()
    assert rows[0].id == "g1"
    assert rows[0].name == "Friends"
    assert svc.group_create("Work", "#f00") == "g-new"
    create_req = next(c for c in calls if c.method == "POST")
    assert create_req.path == "/core/v4/labels"
    assert create_req.body["Name"] == "Work"
    assert create_req.body["Type"] == 2


def test_mail_send_attach_and_attachments_cli_mocked(tmp_path: Path) -> None:
    """``mail messages send --attach`` and ``attachments list|download`` hit the service."""
    attach = tmp_path / "note.txt"
    attach.write_text("hello", encoding="utf-8")

    with patch("proton_cli.cli.mail_cmd._run") as run_app:
        app = MagicMock()
        app.dry_run = False
        app.unlock.return_value = MagicMock()
        app.mail_svc.send.return_value = "msg-sent"
        app.renderer.format.value = "text"
        run_app.return_value = app
        sent = runner.invoke(
            root_app,
            [
                "mail",
                "messages",
                "send",
                "--to",
                "b@x.com",
                "--subject",
                "Hi",
                "--body",
                "body",
                "--attach",
                str(attach),
            ],
        )
    assert sent.exit_code == 0
    send_opts = app.mail_svc.send.call_args.args[1]
    assert send_opts.attachments == [str(attach)]

    with patch("proton_cli.cli.mail_cmd._run") as run_app:
        app = MagicMock()
        app.unlock.return_value = MagicMock()
        app.mail_svc.attachments_list.return_value = [
            Attachment(id="att-1", name="note.txt", size=5, mime_type="text/plain"),
        ]
        app.mail_svc.attachment_download.return_value = (b"hello", "note.txt")
        app.renderer.format.value = "text"
        run_app.return_value = app
        listed = runner.invoke(root_app, ["mail", "messages", "attachments", "list", "msg-1"])
        assert listed.exit_code == 0
        app.mail_svc.attachments_list.assert_called_once_with("msg-1", include_inline=False)

        out = tmp_path / "out.bin"
        downloaded = runner.invoke(
            root_app,
            [
                "mail",
                "messages",
                "attachments",
                "download",
                "msg-1",
                "att-1",
                "--output",
                str(out),
            ],
        )
        assert downloaded.exit_code == 0
        app.mail_svc.attachment_download.assert_called_once()
        assert out.read_bytes() == b"hello"


def test_mail_attachments_list_service() -> None:
    class FakeClient:
        def decode(self, req: Any, out: dict[str, Any]) -> None:
            out.clear()
            out.update(
                {
                    "Message": {
                        "Attachments": [
                            {
                                "ID": "a1",
                                "Name": "file.bin",
                                "Size": 10,
                                "MIMEType": "application/octet-stream",
                                "Disposition": "attachment",
                            },
                            {
                                "ID": "a2",
                                "Name": "inline.png",
                                "Size": 2,
                                "MIMEType": "image/png",
                                "Disposition": "inline",
                            },
                        ]
                    }
                }
            )

    rows = MailService(FakeClient()).attachments_list("msg-1")
    assert [r.id for r in rows] == ["a1"]
    rows_all = MailService(FakeClient()).attachments_list("msg-1", include_inline=True)
    assert [r.id for r in rows_all] == ["a1", "a2"]


def test_classify_recipient_uses_pinned_keys() -> None:
    """Pinned contact keys win over ``/core/v4/keys/all`` during classification."""
    contacts = MagicMock(spec=ContactsService)
    contacts.pinned_keys_for.return_value = ContactCrypto(
        armored_keys=["-----BEGIN PGP PUBLIC KEY BLOCK-----\npinned\n"],
        encrypt=True,
    )
    calls: list[str] = []

    class FakeClient:
        def decode(self, req: Any, out: dict[str, Any]) -> None:
            calls.append(req.path)
            out.clear()
            out.update(
                {
                    "Address": {
                        "Keys": [{"Flags": 0, "PublicKey": "directory-key"}],
                    }
                }
            )

    svc = MailService(FakeClient(), contacts=contacts)
    scheme, armored = svc._classify_recipient(MagicMock(), "pin@x.com")
    assert scheme == PKG_INTERNAL
    assert "pinned" in armored
    assert calls == []  # directory lookup skipped when pinned key present
    contacts.pinned_keys_for.assert_called_once()

    contacts.pinned_keys_for.return_value = ContactCrypto(armored_keys=["k"], encrypt=False)
    scheme_clear, armored_clear = svc._classify_recipient(MagicMock(), "clear@x.com")
    assert scheme_clear == PKG_CLEAR
    assert armored_clear == ""


def test_classify_recipient_falls_back_when_pinned_keys_unavailable() -> None:
    """When pinned lookup soft-fails (``None``), classification uses the directory."""
    contacts = MagicMock(spec=ContactsService)
    contacts.pinned_keys_for.return_value = None
    calls: list[str] = []

    class FakeClient:
        def decode(self, req: Any, out: dict[str, Any]) -> None:
            calls.append(req.path)
            out.clear()
            out.update(
                {
                    "Address": {
                        "Keys": [{"Flags": 0, "PublicKey": "directory-key"}],
                    }
                }
            )

    svc = MailService(FakeClient(), contacts=contacts)
    scheme, armored = svc._classify_recipient(MagicMock(), "pin@x.com")
    assert scheme == PKG_INTERNAL
    assert armored == "directory-key"
    assert calls == ["/core/v4/keys/all"]
    contacts.pinned_keys_for.assert_called_once()


def test_pinned_keys_for_soft_fails_on_decrypt_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Decrypt/network failures inside ``pinned_keys_for`` return ``None`` (no raise)."""
    from proton_cli.crypto import cards as card_crypto

    contacts = ContactsService.__new__(ContactsService)
    contacts._contact_id_by_email = lambda email: ("c1", True)  # type: ignore[method-assign]
    contacts.get_contact = MagicMock()  # type: ignore[method-assign]
    contacts._raw_contact_cards = MagicMock(return_value=[{"Type": 2}])  # type: ignore[method-assign]
    unlocked = MagicMock()
    unlocked.user_keys = [MagicMock()]
    with (
        caplog.at_level(logging.WARNING),
        patch.object(
            card_crypto, "decrypt_cards", side_effect=ValueError("unrecognized card type")
        ),
    ):
        assert contacts.pinned_keys_for(unlocked, "pin@x.com") is None
    assert any("contacts_pinned_keys_lookup_failed" in r.message for r in caplog.records)


def test_hv_helper_crash_logged(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Unexpected helper crashes log detail; ``HVUnavailableError`` stays quiet."""
    monkeypatch.delenv("PROTON_HV_TOKEN", raising=False)
    with (
        caplog.at_level(logging.WARNING),
        patch.object(hv_helper, "resolve_with_helper", side_effect=RuntimeError("boom")),
        pytest.raises(ErrHVUnavailable),
    ):
        cli_hv_resolver(
            HumanVerificationError(token="x", methods=["captcha"], web_url="https://hv"),
        )
    assert any("boom" in r.message or "helper" in r.message.lower() for r in caplog.records)

    caplog.clear()
    with (
        caplog.at_level(logging.WARNING),
        patch.object(
            hv_helper,
            "resolve_with_helper",
            side_effect=hv_helper.HVUnavailableError("not installed"),
        ),
        pytest.raises(ErrHVUnavailable),
    ):
        cli_hv_resolver(
            HumanVerificationError(token="x", methods=["captcha"], web_url="https://hv"),
        )
    assert not any("not installed" in r.message for r in caplog.records)
