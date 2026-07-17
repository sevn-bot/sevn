"""Tests for pass write helpers and protobuf item codec."""

from __future__ import annotations

from proton_cli.proto import item as item_proto
from proton_cli.service.pass_service.service import ItemPatch, NewItem


def test_encode_decode_login_roundtrip() -> None:
    encoded = item_proto.encode_login_item(
        name="sevn-secret",
        note="ops",
        username="alice",
        email="alice@proton.me",
        password="s3cret!",
        url="https://example.com",
        totp="otpauth://totp/test",
    )
    parsed = item_proto.decode_item_content(encoded)
    assert parsed["name"] == "sevn-secret"
    assert parsed["note"] == "ops"
    assert parsed["username"] == "alice"
    assert parsed["email"] == "alice@proton.me"
    assert parsed["password"] == "s3cret!"
    assert parsed["urls"] == ["https://example.com"]
    assert parsed["totp"] == "otpauth://totp/test"


def test_patch_login_item_updates_password() -> None:
    original = item_proto.encode_login_item(name="k", password="old")
    patched = item_proto.patch_login_item(original, password="new")
    parsed = item_proto.decode_item_content(patched)
    assert parsed["name"] == "k"
    assert parsed["password"] == "new"


def test_patch_login_item_preserves_multiple_urls() -> None:
    original = item_proto.encode_login_item(
        name="k",
        urls=["https://a.example", "https://b.example"],
    )
    patched = item_proto.patch_login_item(original, password="new")
    parsed = item_proto.decode_item_content(patched)
    assert parsed["password"] == "new"
    assert parsed["urls"] == ["https://a.example", "https://b.example"]


def test_new_item_and_patch_dataclasses() -> None:
    ni = NewItem(name="x", password="p")
    assert ni.type == "login"
    patch = ItemPatch(password="q")
    assert patch.password == "q"
