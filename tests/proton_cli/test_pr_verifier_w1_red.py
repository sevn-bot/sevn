"""PR #38-#45 RED behavioral coverage for proton-cli (green after W4-W11).

Extends the thin structural suites with mocked Client / CliRunner paths and
silent-failure surfacing assertions.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from proton_cli.cli.root import app as root_app

runner = CliRunner()


# --- W4 / PR #38 -----------------------------------------------------------


def test_pass_vaults_list_mocked_client() -> None:
    """``pass vaults list`` drives PassService and returns vault share ids."""
    from proton_cli.service.pass_service.service import PassService

    class FakeClient:
        def decode(self, req: Any, out: dict[str, Any] | None = None) -> None:
            if out is None:
                return
            out.clear()
            if req.path == "/pass/v1/share":
                out.update(
                    {
                        "Shares": [
                            {
                                "ShareID": "share-1",
                                "VaultID": "vault-1",
                                "TargetType": 1,
                                "Owner": True,
                                "Shared": False,
                                "TargetMembers": 1,
                                "AddressID": "addr-1",
                                "Content": "",
                                "ContentKeyRotation": 0,
                            }
                        ]
                    }
                )

    svc = PassService(FakeClient())
    rows = svc.vaults_list(MagicMock())
    assert len(rows) == 1
    assert rows[0].share_id == "share-1"
    assert rows[0].vault_id == "vault-1"


def test_pass_items_list_mocked_client() -> None:
    """``items_list`` decrypts share keys then fetches items per vault."""
    from proton_cli.service.pass_service.service import Item, PassService, Vault

    svc = PassService(MagicMock())
    unlocked = MagicMock()
    vault = Vault(share_id="share-1", vault_id="vault-1", name="Personal")
    item = Item(share_id="share-1", item_id="item-1", name="login-1", type="login")
    with (
        patch.object(svc, "vaults_list", return_value=[vault]),
        patch.object(svc, "_decrypt_share_keys", return_value={1: b"share-key"}) as decrypt,
        patch.object(svc, "_fetch_items", return_value=[item]) as fetch,
    ):
        rows = svc.items_list(unlocked)
    assert rows[0].name == "login-1"
    decrypt.assert_called_once_with("share-1", unlocked)
    fetch.assert_called_once_with("share-1", {1: b"share-key"})


def test_pass_items_get_cli_invokes_service() -> None:
    """``pass items get`` resolves + loads an item via PassService."""
    with patch("proton_cli.cli.pass_cmd._run") as run_app:
        app = MagicMock()
        app.pass_svc.resolve_item.return_value = ("share-1", "item-1")
        app.pass_svc.item_get.return_value = MagicMock(
            name="login-1",
            item_id="item-1",
            type="login",
        )
        run_app.return_value = app
        result = runner.invoke(
            root_app,
            ["--output", "json", "pass", "items", "get", "login-1"],
        )
    assert result.exit_code == 0
    app.pass_svc.resolve_item.assert_called_once()
    app.pass_svc.item_get.assert_called_once_with(
        app.unlock.return_value,
        "share-1",
        "item-1",
    )


def test_pass_share_key_decrypt_failure_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    """Share-key decrypt failure is logged; empty key map is not a silent skip."""
    import base64

    from proton_cli.service.pass_service.service import PassService

    class FakeClient:
        def decode(self, req: Any, out: dict[str, Any] | None = None) -> None:
            if out is None:
                return
            out.clear()
            out.update(
                {
                    "ShareKeys": {
                        "Keys": [
                            {
                                "Key": base64.b64encode(b"ciphertext").decode(),
                                "KeyRotation": 1,
                            }
                        ]
                    }
                }
            )

    svc = PassService(FakeClient())
    unlocked = MagicMock()
    unlocked.user_keys = []
    unlocked.addr_keys = {}
    with (
        caplog.at_level(logging.WARNING),
        patch(
            "proton_cli.service.pass_service.service.decrypt_pgp_message",
            side_effect=RuntimeError("bad key"),
        ),
    ):
        keys = svc._decrypt_share_keys("share-1", unlocked)
    assert keys == {}
    logged = any(
        ("decrypt" in r.message.lower() or "share" in r.message.lower())
        and "bad key" in r.message.lower()
        for r in caplog.records
    )
    assert logged


# --- W5 / PR #39 -----------------------------------------------------------


def test_pass_item_create_posts_to_api() -> None:
    """``item_create`` POSTs an encrypted login item and returns ItemID."""
    from proton_cli.service.pass_service.service import NewItem, PassService

    calls: list[Any] = []

    class FakeClient:
        def decode(self, req: Any, out: dict[str, Any] | None = None) -> None:
            calls.append(req)
            if out is not None:
                out.clear()
                out.update({"Item": {"ItemID": "new-1"}})

    svc = PassService(FakeClient())
    unlocked = MagicMock()
    with patch.object(svc, "_decrypt_share_keys", return_value={1: b"\x00" * 32}):
        item_id = svc.item_create(unlocked, "share-1", NewItem(name="x", password="p"))
    assert item_id == "new-1"
    assert len(calls) == 1
    assert calls[0].method == "POST"
    assert calls[0].path == "/pass/v1/share/share-1/item"
    assert "Content" in (calls[0].body or {})
    assert "ItemKey" in (calls[0].body or {})


def test_pass_vault_create_and_delete_side_effects() -> None:
    """``vault_create`` POSTs /pass/v1/vault; ``vault_delete`` DELETEs the share."""
    from proton_cli.service.pass_service.service import PassService

    calls: list[Any] = []

    class FakeClient:
        def decode(self, req: Any, out: dict[str, Any] | None = None) -> None:
            calls.append(req)
            if out is not None and req.method == "POST":
                out.clear()
                out.update({"Share": {"ShareID": "vault-share-1"}})

    svc = PassService(FakeClient())
    unlocked = MagicMock()
    unlocked.primary_addr.return_value = ([MagicMock()], "addr-1", "a@proton.me")
    with patch(
        "proton_cli.service.pass_service.service._encrypt_binary",
        return_value=b"enc-key",
    ):
        share_id = svc.vault_create(unlocked, "Personal")
    assert share_id == "vault-share-1"
    assert calls[0].method == "POST"
    assert calls[0].path == "/pass/v1/vault"

    calls.clear()
    svc.vault_delete("vault-share-1")
    assert calls[0].method == "DELETE"
    assert calls[0].path == "/pass/v1/vault/vault-share-1"


def test_pass_upsert_login_password_creates_when_missing() -> None:
    """``upsert_login_password`` creates a login when no matching item exists."""
    from proton_cli.service.pass_service.service import PassService

    svc = PassService(MagicMock())
    unlocked = MagicMock()
    with (
        patch.object(svc, "find_login_by_name", return_value=None),
        patch.object(svc, "resolve_vault", return_value="share-1"),
        patch.object(svc, "item_create", return_value="created-1") as create,
    ):
        item_id = svc.upsert_login_password(unlocked, name="sevn", password="p")
    assert item_id == "created-1"
    create.assert_called_once()


def test_pass_secrets_get_emits_credential() -> None:
    """``pass secrets get`` resolves a login and emits the password via stdout helper."""
    emitted: list[str] = []
    with (
        patch("proton_cli.cli.pass_cmd._run") as run_app,
        patch(
            "proton_cli.cli.pass_cmd._emit_credential_stdout",
            side_effect=lambda value: emitted.append(value),
        ),
    ):
        app = MagicMock()
        app.pass_svc.find_login_by_name.return_value = MagicMock(
            name="sevn",
            username="u",
            password="secret",
        )
        run_app.return_value = app
        result = runner.invoke(root_app, ["pass", "secrets", "get", "sevn"])
    assert result.exit_code == 0
    assert emitted == ["secret"]
    app.pass_svc.find_login_by_name.assert_called_once()


def test_pass_items_create_and_vaults_create_cli() -> None:
    """``pass items create`` / ``pass vaults create`` drive PassService write methods."""
    with patch("proton_cli.cli.pass_cmd._run") as run_app:
        app = MagicMock()
        app.dry_run = False
        app.pass_svc.resolve_vault.return_value = "share-1"
        app.pass_svc.item_create.return_value = "item-1"
        app.pass_svc.vault_create.return_value = "share-new"
        run_app.return_value = app
        created = runner.invoke(
            root_app,
            ["pass", "items", "create", "--name", "n", "--password", "p"],
        )
        vaulted = runner.invoke(root_app, ["pass", "vaults", "create", "--name", "Team"])
    assert created.exit_code == 0
    assert vaulted.exit_code == 0
    app.pass_svc.item_create.assert_called_once()
    app.pass_svc.vault_create.assert_called_once()


def test_address_key_unlock_failure_is_visible(caplog: pytest.LogCaptureFixture) -> None:
    """Address-key unlock failures log at warning instead of silent empty lists."""
    from proton_cli.account.keys import Key, _unlock_keys

    bad = Key(id="addr-key-1", private_key="not-a-valid-pgp-blob", active=1)
    with caplog.at_level(logging.WARNING):
        unlocked = _unlock_keys([bad], b"passphrase", None)
    assert unlocked == []
    logged = any(
        "unlock" in r.message.lower() and "addr-key-1" in r.message for r in caplog.records
    )
    assert logged


def test_pass_item_decrypt_failure_logged_not_anonymized(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """``_fetch_items`` logs item decrypt failures; placeholder type=unknown is not silent."""
    import base64

    from proton_cli.service.pass_service.service import PassService

    class FakeClient:
        def decode(self, req: Any, out: dict[str, Any] | None = None) -> None:
            if out is None:
                return
            out.clear()
            out.update(
                {
                    "Items": {
                        "RevisionsData": [
                            {
                                "ItemID": "item-bad",
                                "State": 1,
                                "ContentKeyRotation": 1,
                                "ItemKey": base64.b64encode(b"short").decode(),
                                "Content": base64.b64encode(b"x").decode(),
                                "Revision": 1,
                            }
                        ],
                        "LastToken": "",
                    }
                }
            )

    svc = PassService(FakeClient())
    with caplog.at_level(logging.WARNING):
        items = svc._fetch_items("share-1", {1: b"\x00" * 32})
    assert len(items) == 1
    assert items[0].type == "unknown"
    logged = any(
        "item decrypt" in r.message.lower() and "item-bad" in r.message for r in caplog.records
    )
    assert logged


# --- W7 / PR #41 -----------------------------------------------------------


def test_mail_messages_search_mocked() -> None:
    with patch("proton_cli.cli.mail_cmd._run") as run_app:
        app = MagicMock()
        app.mail_svc.search_messages.return_value = ([], 0)
        app.renderer.format.value = "text"
        run_app.return_value = app
        result = runner.invoke(root_app, ["mail", "messages", "search", "--keyword", "hello"])
    assert result.exit_code == 0
    app.mail_svc.search_messages.assert_called_once()
    opts = app.mail_svc.search_messages.call_args.args[0]
    assert opts.keyword == "hello"


def test_mail_messages_read_mocked() -> None:
    with patch("proton_cli.cli.mail_cmd._run") as run_app:
        app = MagicMock()
        app.mail_svc.list_messages.return_value = ([], 0)
        app.mail_svc.resolve_message.return_value = "msg-1"
        app.mail_svc.read_message.return_value = MagicMock(subject="Hi", body="body")
        app.renderer.format.value = "json"
        run_app.return_value = app
        result = runner.invoke(root_app, ["mail", "messages", "read", "msg-1"])
    assert result.exit_code == 0
    app.mail_svc.read_message.assert_called_once()


@pytest.mark.parametrize(
    "argv",
    [
        ["mail", "messages", "trash", "msg-1"],
        ["mail", "messages", "delete", "msg-1"],
        ["mail", "messages", "move", "msg-1", "--folder", "archive"],
        ["mail", "labels", "list"],
    ],
)
def test_mail_mutate_and_labels_cli(argv: list[str]) -> None:
    with patch("proton_cli.cli.mail_cmd._run") as run_app:
        app = MagicMock()
        app.mail_svc.labels_list.return_value = ([], [])
        app.renderer.format.value = "text"
        run_app.return_value = app
        result = runner.invoke(root_app, argv)
    assert result.exit_code == 0


def test_resolve_secret_value_from_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    from proton_cli.cli import pass_cmd

    monkeypatch.setattr(pass_cmd.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(pass_cmd.sys.stdin, "read", lambda: "from-stdin\n")
    value = pass_cmd._resolve_secret_value("-", prompt="Password")
    assert value == "from-stdin"


def test_login_srp_retries_once_on_hv() -> None:
    from proton_cli.proton import auth
    from proton_cli.proton.errors import HumanVerificationError

    calls = {"n": 0}

    def _once(*_a: Any, **_k: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            raise HumanVerificationError(token="t", web_url="https://hv")
        return {"UID": "u", "AccessToken": "a", "RefreshToken": "r"}

    client = MagicMock()
    client.get_hv_resolver.return_value = lambda _exc: ("tok", "captcha")
    with patch.object(auth, "_login_srp_once", side_effect=_once):
        result = auth._login_srp(client, "user", "pass", "", "")
    assert calls["n"] == 2
    assert result["UID"] == "u"
    client.get_hv_resolver.assert_called()


def test_cli_hv_resolver_uses_env_token(monkeypatch: pytest.MonkeyPatch) -> None:
    from proton_cli.hv.resolver import cli_hv_resolver
    from proton_cli.proton.errors import HumanVerificationError

    monkeypatch.setenv("PROTON_HV_TOKEN", "env-tok")
    monkeypatch.setenv("PROTON_HV_TYPE", "captcha")
    token, kind = cli_hv_resolver(HumanVerificationError(token="t", web_url="https://hv"))
    assert token == "env-tok"
    assert kind == "captcha"


def test_cli_hv_resolver_raises_when_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    from proton_cli.hv.resolver import cli_hv_resolver
    from proton_cli.proton.errors import ErrHVUnavailable, HumanVerificationError

    def _boom(_token: str) -> str:
        raise Exception("no helper")

    monkeypatch.delenv("PROTON_HV_TOKEN", raising=False)
    monkeypatch.setattr("proton_cli.hv.helper.resolve_with_helper", _boom)
    with pytest.raises(ErrHVUnavailable):
        cli_hv_resolver(
            HumanVerificationError(token="t", methods=["captcha"], web_url="https://hv")
        )


# --- W8 / PR #42 -----------------------------------------------------------


def test_drive_list_children_mocked() -> None:
    """``list_children`` decrypts names via mocked crypto (behavioral, not ``--help``)."""
    from proton_cli.service.drive.crypto import Link
    from proton_cli.service.drive.service import DriveService

    svc = DriveService(MagicMock())
    resolved = MagicMock(is_folder=True, share_id="s", link_id="r", node_key=MagicMock())
    with (
        patch.object(svc, "resolve_path", return_value=resolved),
        patch.object(
            svc,
            "_list_raw_children",
            return_value=[Link(link_id="c1", name="enc", type=2, size=1)],
        ),
        patch("proton_cli.service.drive.crypto.decrypt_name", return_value="readme.txt"),
    ):
        rows = svc.list_children(MagicMock(), "/")
    assert rows[0].name == "readme.txt"
    assert rows[0].link_id == "c1"


def test_drive_resolve_path_decrypt_failure_distinct_from_not_found(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Decrypt/key mismatch on a path segment is logged before ``NotFound``."""
    from proton_cli.errors import NotFound
    from proton_cli.service.drive.crypto import Link
    from proton_cli.service.drive.service import DriveService

    svc = DriveService(MagicMock())
    dc = MagicMock()
    dc.share_id = "share-1"
    dc.root_link_id = "root-1"
    dc.share_key = MagicMock()
    dc.addr_key = MagicMock()
    with (
        caplog.at_level(logging.WARNING),
        patch.object(svc, "_get_link", return_value=Link(link_id="root-1", type=1)),
        patch("proton_cli.service.drive.crypto.unlock_node", return_value=MagicMock()),
        patch.object(
            svc,
            "_list_raw_children",
            return_value=[Link(link_id="child-1", name="enc", type=2)],
        ),
        patch(
            "proton_cli.service.drive.crypto.decrypt_name",
            side_effect=RuntimeError("key mismatch"),
        ),
        pytest.raises(NotFound),
    ):
        svc.resolve_path(dc, "/x")
    assert any(
        "decrypt" in r.message.lower() and "key mismatch" in r.message.lower()
        for r in caplog.records
    )


def test_drive_unlock_share_uses_typed_address_fields() -> None:
    """Upload/create payload carries a non-empty ``SignatureAddress`` from typed address."""
    from proton_cli.account.keys import Address
    from proton_cli.service.drive import crypto as drive_crypto
    from proton_cli.service.drive.crypto import Link
    from proton_cli.service.drive.service import DriveService

    addr = Address(id="addr-1", email="a@proton.me")
    assert addr.id == "addr-1"
    assert addr.email == "a@proton.me"
    assert hasattr(drive_crypto, "unlock_share")

    calls: list[Any] = []

    class FakeClient:
        def decode(self, req: Any, out: dict[str, Any] | None = None) -> None:
            calls.append(req)

    svc = DriveService(FakeClient())
    dc = MagicMock()
    dc.addr_email = addr.email
    dc.addr_key = MagicMock()
    parent = MagicMock(share_id="share-1", link_id="p1", node_key=MagicMock(), is_folder=True)
    with (
        patch.object(svc, "resolve_path", return_value=parent),
        patch.object(svc, "_get_link", return_value=Link(link_id="p1", type=1)),
        patch("proton_cli.service.drive.crypto.hash_key_of", return_value=b"\x00" * 32),
        patch("proton_cli.service.drive.crypto.lookup_hash", return_value="digest"),
        patch("proton_cli.service.drive.crypto.encrypt_name", return_value="enc"),
        patch(
            "proton_cli.service.drive.crypto.gen_node_keys",
            return_value=("arm", "pass", "sig", MagicMock(), "phrase"),
        ),
        patch("proton_cli.service.drive.crypto.gen_node_hash_key", return_value="hk"),
    ):
        svc.create_folder(dc, "/Photos")
    assert calls[0].body["SignatureAddress"] == "a@proton.me"


# --- W9 / PR #43 -----------------------------------------------------------


def _w9_rsa_key() -> Any:
    from pgpy import PGPUID, PGPKey
    from pgpy.constants import (
        CompressionAlgorithm,
        HashAlgorithm,
        KeyFlags,
        PubKeyAlgorithm,
        SymmetricKeyAlgorithm,
    )

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
    from proton_cli.crypto import cards as card_crypto
    from proton_cli.crypto import vcard as vcard_crypto
    from proton_cli.service.contacts.service import ContactsService

    key = _w9_rsa_key()
    signed = vcard_crypto.signed_vcard("Alice", ["a@x.com"], "uid-1")

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
    assert rows[0].name == "Alice"
    assert rows[0].emails == ["a@x.com"]


def test_calendar_events_list_get_delete() -> None:
    from datetime import UTC, datetime

    from proton_cli.service.calendar.service import CalendarService, Event

    calls: list[Any] = []
    keys = MagicMock(member_id="m1")
    event = Event(id="e1", calendar_id="cal-1", title="Standup")

    class FakeClient:
        def decode(self, req: Any, out: dict[str, Any] | None = None) -> None:
            calls.append(req)
            if out is None:
                return
            out.clear()
            if req.method == "GET" and str(req.path).endswith("/events"):
                out.update({"Events": [{"ID": "e1"}]})
            elif req.method == "GET":
                out.update({"Event": {"ID": "e1"}})

    svc = CalendarService(FakeClient())
    unlocked = MagicMock()
    start = datetime(2026, 7, 1, tzinfo=UTC)
    end = datetime(2026, 7, 31, tzinfo=UTC)
    with (
        patch.object(svc, "_unlock_calendar", return_value=keys),
        patch.object(svc, "_event_from_raw", return_value=event),
    ):
        assert svc.events_list(unlocked, "cal-1", start, end)[0].id == "e1"
        assert svc.event_get(unlocked, "cal-1", "e1").id == "e1"
        svc.event_delete(unlocked, "cal-1", "e1")
    delete_req = next(c for c in calls if c.method == "PUT")
    assert delete_req.body == {"MemberID": "m1", "Events": [{"ID": "e1"}]}


def test_contacts_create_empty_response_not_success() -> None:
    from proton_cli.service.contacts.service import ContactsService, NewContact

    class FakeClient:
        def decode(self, req: Any, out: dict[str, Any]) -> None:
            out.clear()
            out.update({"Responses": []})

    unlocked = MagicMock()
    unlocked.user_keys = [_w9_rsa_key()]
    svc = ContactsService(FakeClient())
    nc = NewContact(name="Bob", emails=["b@x.com"])
    with pytest.raises((ValueError, RuntimeError), match="empty Responses"):
        svc.create_contact(unlocked, nc)


def test_decrypt_cards_encrypted_and_signed_types() -> None:
    import base64

    from pgpy import PGPMessage

    from proton_cli.crypto import cards as cards_mod
    from proton_cli.service.drive import blocks

    assert hasattr(cards_mod, "decrypt_cards")
    assert cards_mod.CARD_ENCRYPTED == 1
    assert cards_mod.CARD_ENCRYPTED_SIGNED == 3

    key = _w9_rsa_key()
    pub = key.pubkey
    msg = PGPMessage.new("plain-encrypted")
    enc = pub.encrypt(msg)
    assert cards_mod.decrypt_cards(
        [{"Type": cards_mod.CARD_ENCRYPTED, "Data": str(enc)}],
        key,
        key,
    ) == ["plain-encrypted"]

    signed_card = cards_mod.encrypt_and_sign_card("plain-signed", pub, key)
    assert cards_mod.decrypt_cards([signed_card], key, key) == ["plain-signed"]

    sk = blocks.make_session_key()
    data_packet = blocks.encrypt_data_packet(b"SUMMARY:Meet\r\n", sk)
    with (
        patch(
            "proton_cli.crypto.cards.blocks.decrypt_session_key_packet",
            return_value=sk,
        ),
        patch(
            "proton_cli.crypto.cards.blocks._packet_body",
            wraps=blocks._packet_body,
        ) as packet_body,
    ):
        out = cards_mod.decrypt_cards(
            [
                {
                    "Type": cards_mod.CARD_ENCRYPTED_SIGNED,
                    "Data": base64.b64encode(data_packet).decode(),
                }
            ],
            key,
            key,
            key_packet=b"\x00fake",
        )
    assert out == ["SUMMARY:Meet\r\n"]
    packet_body.assert_called()


def test_decrypt_cards_unknown_type_surfaced() -> None:
    from proton_cli.crypto import cards as cards_mod

    key = _w9_rsa_key()
    with pytest.raises(ValueError, match="unrecognized card type"):
        cards_mod.decrypt_cards([{"Type": 999, "Data": "raw"}], key, key)


def test_contacts_list_logs_dropped_rows(caplog: pytest.LogCaptureFixture) -> None:
    from proton_cli.crypto import cards as card_crypto
    from proton_cli.crypto import vcard as vcard_crypto
    from proton_cli.service.contacts.service import ContactsService

    key = _w9_rsa_key()

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
    assert any("bad-1" in r.message and "decrypt" in r.message.lower() for r in caplog.records)


# --- W10 / PR #44 ----------------------------------------------------------


def test_status_command_runs_not_missing_command() -> None:
    result = runner.invoke(root_app, ["--output", "json", "status"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout or result.output or "{}")
    assert "version" in payload or "profile" in payload or "ok" in payload or payload


def test_api_get_runs_not_missing_command() -> None:
    with patch("proton_cli.cli.api_cmd._run") as run_app:
        app = MagicMock()
        app.api.do.return_value = MagicMock(body=b'{"Code":1000}')
        app.renderer.json_body = MagicMock()
        run_app.return_value = app
        result = runner.invoke(root_app, ["api", "GET", "/core/v4/users"])
    assert result.exit_code != 2
    assert "Missing command" not in (result.output or "")
    app.api.do.assert_called_once()


def test_status_session_exists_legacy_session_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    legacy = tmp_path / "proton-cli" / "session.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("{}", encoding="utf-8")
    from proton_cli.account import session as session_store

    path = session_store.session_path("default")
    assert path == legacy
    assert path.is_file()
    result = runner.invoke(root_app, ["--output", "json", "status"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout or result.output or "{}")
    assert payload.get("session_exists") is True
    assert str(legacy) in str(payload.get("session_file", ""))


def test_settings_set_rejects_missing_value() -> None:
    result = runner.invoke(root_app, ["settings", "set", "page-size"])
    assert result.exit_code != 0
    assert "value" in (result.output or "").lower() or "missing" in (result.output or "").lower()


# --- W11 / PR #45 ----------------------------------------------------------


@pytest.mark.xfail(reason="green after W11: calendar events create/respond", strict=False)
def test_calendar_events_create_and_respond() -> None:
    result_create = runner.invoke(
        root_app,
        ["calendar", "events", "create", "--help"],
    )
    assert result_create.exit_code == 0
    # Behavioral (not --help) after W11:
    raise AssertionError("events create/respond need mocked side-effect tests (W11)")


@pytest.mark.xfail(reason="green after W11: contacts groups and pin-key", strict=False)
def test_contacts_groups_and_pin_key_cli() -> None:
    raise AssertionError("contacts groups/pin-key behavioral coverage missing (W11)")


@pytest.mark.xfail(reason="green after W11: mail attach + attachments", strict=False)
def test_mail_send_attach_and_attachments() -> None:
    raise AssertionError("mail send --attach + attachments list/download uncovered (W11)")


@pytest.mark.xfail(reason="green after W11: pinned_keys_for consumed", strict=False)
def test_pinned_keys_for_used_in_recipient_classification() -> None:
    from proton_cli.service.contacts import service as contacts_svc
    from proton_cli.service.mail import service as mail_svc

    assert hasattr(contacts_svc.ContactsService, "pinned_keys_for")
    # Mail classification must consult pinned keys, not only /core/v4/keys/all.
    source = Path(mail_svc.__file__).read_text(encoding="utf-8")
    assert "pinned_keys_for" in source


@pytest.mark.xfail(reason="green after W11: HV helper crash distinguishable", strict=False)
def test_hv_helper_crash_distinct_from_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from proton_cli.hv import helper as hv_helper
    from proton_cli.hv import resolver as hv_resolver
    from proton_cli.proton.errors import ErrHVUnavailable, HumanVerificationError

    monkeypatch.delenv("PROTON_HV_TOKEN", raising=False)
    with (
        caplog.at_level(logging.WARNING),
        patch.object(hv_helper, "resolve_with_helper", side_effect=RuntimeError("boom")),
        pytest.raises(ErrHVUnavailable),
    ):
        hv_resolver.cli_hv_resolver(
            HumanVerificationError(token="x", methods=["captcha"], web_url="https://hv"),
        )
    assert any("boom" in r.message or "helper" in r.message.lower() for r in caplog.records)
