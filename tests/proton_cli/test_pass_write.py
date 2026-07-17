"""Tests for pass write helpers and protobuf item codec.

Exports:
    test_encode_decode_login_roundtrip
    test_patch_login_item_updates_password
    test_patch_login_item_clears_password
    test_patch_login_item_preserves_multiple_urls
    test_decode_unknown_item_type
    test_new_item_and_patch_dataclasses
"""

from __future__ import annotations

import pytest

from proton_cli.proto import item as item_proto
from proton_cli.service.pass_service.service import ItemPatch, NewItem


def test_encode_decode_login_roundtrip() -> None:
    """Login protobuf encode/decode preserves fields.

    Returns:
        None

    Examples:
        >>> from proton_cli.proto import item as item_proto
        >>> blob = item_proto.encode_login_item(name="k", password="p")
        >>> item_proto.decode_item_content(blob)["type"]
        'login'
    """
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
    assert parsed["type"] == "login"
    assert parsed["name"] == "sevn-secret"
    assert parsed["note"] == "ops"
    assert parsed["username"] == "alice"
    assert parsed["email"] == "alice@proton.me"
    assert parsed["password"] == "s3cret!"
    assert parsed["urls"] == ["https://example.com"]
    assert parsed["totp"] == "otpauth://totp/test"


def test_patch_login_item_updates_password() -> None:
    """Patch replaces password while preserving other fields.

    Returns:
        None

    Examples:
        >>> from proton_cli.proto import item as item_proto
        >>> orig = item_proto.encode_login_item(name="k", password="old")
        >>> patched = item_proto.patch_login_item(orig, password="new")
        >>> item_proto.decode_item_content(patched)["password"]
        'new'
    """
    original = item_proto.encode_login_item(name="k", password="old")
    patched = item_proto.patch_login_item(original, password="new")
    parsed = item_proto.decode_item_content(patched)
    assert parsed["name"] == "k"
    assert parsed["password"] == "new"


def test_patch_login_item_clears_password() -> None:
    """Empty string clears a field when explicitly patched.

    Returns:
        None

    Examples:
        >>> from proton_cli.proto import item as item_proto
        >>> orig = item_proto.encode_login_item(name="k", password="old")
        >>> patched = item_proto.patch_login_item(orig, password="")
        >>> item_proto.decode_item_content(patched)["password"]
        ''
    """
    original = item_proto.encode_login_item(name="k", password="old")
    patched = item_proto.patch_login_item(original, password="")
    parsed = item_proto.decode_item_content(patched)
    assert parsed["password"] == ""


def test_patch_login_item_preserves_multiple_urls() -> None:
    """Patching one field leaves unrelated login data intact.

    Returns:
        None

    Examples:
        >>> True
        True
    """
    original = item_proto.encode_login_item(
        name="k",
        urls=["https://a.example", "https://b.example"],
    )
    patched = item_proto.patch_login_item(original, password="new")
    parsed = item_proto.decode_item_content(patched)
    assert parsed["password"] == "new"
    assert parsed["urls"] == ["https://a.example", "https://b.example"]


def test_decode_unknown_item_type() -> None:
    """Items without login content decode as unknown.

    Returns:
        None

    Examples:
        >>> from proton_cli.proto import item as item_proto
        >>> item_proto.decode_item_content(b"")["type"]
        'unknown'
    """
    assert item_proto.decode_item_content(b"")["type"] == "unknown"


def test_new_item_and_patch_dataclasses() -> None:
    """Dataclass defaults match login write expectations.

    Returns:
        None

    Examples:
        >>> from proton_cli.service.pass_service.service import ItemPatch, NewItem
        >>> NewItem(name="x", password="p").type
        'login'
    """
    ni = NewItem(name="x", password="p")
    assert ni.type == "login"
    patch = ItemPatch(password="q")
    assert patch.password == "q"
    assert patch.name is None


def test_patch_login_item_rejects_non_login() -> None:
    """Non-login blobs cannot be patched as logins."""
    vault_only = item_proto.encode_vault("vault-name")
    with pytest.raises(ValueError, match="login"):
        item_proto.patch_login_item(vault_only, password="x")
