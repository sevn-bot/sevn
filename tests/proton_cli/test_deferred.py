"""Tests for deferred proton-cli features."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pgpy import PGPKey
from pgpy.constants import EllipticCurveOID, HashAlgorithm, PubKeyAlgorithm, SymmetricKeyAlgorithm

from proton_cli.crypto import ical as ical_crypto
from proton_cli.hv import helper as hv_helper
from proton_cli.hv.resolver import cli_hv_resolver
from proton_cli.proton.errors import ErrHVUnavailable, HumanVerificationError
from proton_cli.service.calendar.service import status_from_flag
from proton_cli.service.drive import blocks
from proton_cli.service.drive.keygen import _generate_armored_locked_key_python
from proton_cli.service.mail import mime as mail_mime


def test_ical_signed_and_encrypted_vevent() -> None:
    start = datetime(2026, 7, 16, 10, 0, tzinfo=timezone.utc)
    end = datetime(2026, 7, 16, 11, 0, tzinfo=timezone.utc)
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
    key = PGPKey.new(PubKeyAlgorithm.ECDH, EllipticCurveOID.Curve25519)
    session_key = blocks.make_session_key()
    plain = b"SUMMARY:Meet"
    packet = blocks.encrypt_data_packet(plain, session_key)
    decrypted = blocks.decrypt_block(packet, session_key)
    assert decrypted == plain


def test_status_from_flag() -> None:
    from proton_cli.service.calendar.service import PARTSTAT_ACCEPTED

    assert status_from_flag("accept") == PARTSTAT_ACCEPTED
    with pytest.raises(ValueError):
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
