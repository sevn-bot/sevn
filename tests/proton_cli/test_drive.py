"""Tests for drive helpers."""

from __future__ import annotations

from proton_cli.service.drive import blocks, paths
from proton_cli.service.drive.crypto import lookup_hash
from proton_cli.service.drive.service import DriveService


def test_path_helpers() -> None:
    assert paths.normalize_path("") == "/"
    assert paths.dir_of("/Photos/2024") == "/Photos"
    assert paths.base_of("/Photos/2024") == "2024"


def test_lookup_hash() -> None:
    key = b"\x01" * 32
    h1 = lookup_hash("readme.txt", key)
    h2 = lookup_hash("readme.txt", key)
    assert h1 == h2
    assert len(h1) == 64


def test_seipd_roundtrip() -> None:
    sk = blocks.make_session_key()
    plain = b"hello drive block"
    enc, sig = blocks.encrypt_block(plain, sk, None, None)
    assert sig == ""
    dec = blocks.decrypt_block(enc, sk)
    assert dec == plain


def test_session_key_payload() -> None:
    sk = blocks.make_session_key()
    payload = blocks.session_key_payload(sk)
    assert payload[0] == 9
    assert len(payload) == 1 + 32 + 2


def test_drive_service_init() -> None:
    class FakeClient:
        pass

    svc = DriveService(FakeClient())
    assert svc._client is not None
