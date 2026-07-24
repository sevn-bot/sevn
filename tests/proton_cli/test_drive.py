"""Tests for drive helpers, service flows, and CLI commands.

Exports:
    test_drive_command_registered
    test_path_helpers
    test_lookup_hash
    test_seipd_roundtrip
    test_session_key_payload
    test_drive_service_init
    test_list_children_decrypts_names
    test_list_children_logs_decrypt_failure
    test_resolve_path_decrypt_failure_logged_before_not_found
    test_trash_list_logs_link_fetch_failure
    test_create_folder_signature_address_non_empty
    test_drive_items_list_cli_mocked
    test_drive_items_upload_download_cli_mocked
    test_drive_items_trash_delete_cli_mocked
    test_drive_folders_create_cli_mocked
    test_drive_trash_list_restore_empty_cli_mocked
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from proton_cli.cli.root import app as root_app
from proton_cli.errors import NotFound
from proton_cli.service.drive import blocks, paths
from proton_cli.service.drive.crypto import Link, lookup_hash
from proton_cli.service.drive.service import Child, DriveService, TrashEntry

runner = CliRunner()


def test_drive_command_registered() -> None:
    result = CliRunner().invoke(root_app, ["drive", "--help"])
    assert result.exit_code == 0
    assert "items" in result.output


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


def _folder_dc() -> MagicMock:
    dc = MagicMock()
    dc.share_id = "share-1"
    dc.root_link_id = "root-1"
    dc.volume_id = "vol-1"
    dc.addr_email = "a@proton.me"
    dc.addr_key = MagicMock()
    dc.share_key = MagicMock()
    return dc


def test_list_children_decrypts_names() -> None:
    """``list_children`` decrypts child names via ``crypto.decrypt_name``."""
    svc = DriveService(MagicMock())
    resolved = MagicMock(is_folder=True, share_id="share-1", link_id="root-1", node_key=MagicMock())
    child = Link(link_id="c1", name="enc-name", type=2, size=10)
    with (
        patch.object(svc, "resolve_path", return_value=resolved),
        patch.object(svc, "_list_raw_children", return_value=[child]),
        patch(
            "proton_cli.service.drive.crypto.decrypt_name",
            return_value="readme.txt",
        ) as decrypt,
    ):
        rows = svc.list_children(_folder_dc(), "/")
    assert len(rows) == 1
    assert rows[0].name == "readme.txt"
    assert rows[0].link_id == "c1"
    decrypt.assert_called_once()


def test_list_children_logs_decrypt_failure(caplog: pytest.LogCaptureFixture) -> None:
    """Name decrypt failure is logged and substituted with a marker."""
    svc = DriveService(MagicMock())
    resolved = MagicMock(is_folder=True, share_id="share-1", link_id="root-1", node_key=MagicMock())
    child = Link(link_id="bad-1", name="enc-bad", type=2, size=0)
    with (
        caplog.at_level(logging.WARNING),
        patch.object(svc, "resolve_path", return_value=resolved),
        patch.object(svc, "_list_raw_children", return_value=[child]),
        patch(
            "proton_cli.service.drive.crypto.decrypt_name",
            side_effect=RuntimeError("bad key"),
        ),
    ):
        rows = svc.list_children(_folder_dc(), "/")
    assert rows[0].name == "(decrypt failed)"
    assert any(
        "decrypt" in r.message.lower() and "bad-1" in r.message and "bad key" in r.message.lower()
        for r in caplog.records
    )


def test_resolve_path_decrypt_failure_logged_before_not_found(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Decrypt failure on a path segment is logged before ``NotFound``."""
    svc = DriveService(MagicMock())
    dc = _folder_dc()
    root = Link(link_id="root-1", type=1, name="")
    bad = Link(link_id="child-1", name="enc-x", type=2)
    with (
        caplog.at_level(logging.WARNING),
        patch.object(svc, "_get_link", return_value=root),
        patch(
            "proton_cli.service.drive.crypto.unlock_node",
            return_value=MagicMock(),
        ),
        patch.object(svc, "_list_raw_children", return_value=[bad]),
        patch(
            "proton_cli.service.drive.crypto.decrypt_name",
            side_effect=RuntimeError("key mismatch"),
        ),
        pytest.raises(NotFound),
    ):
        svc.resolve_path(dc, "/missing")
    assert any(
        "decrypt" in r.message.lower()
        and "key mismatch" in r.message.lower()
        and "child-1" in r.message
        for r in caplog.records
    )


def test_trash_list_logs_link_fetch_failure(caplog: pytest.LogCaptureFixture) -> None:
    """``trash_list`` logs when ``_get_link`` fails and still returns a bare entry."""

    class FakeClient:
        def decode(self, req: Any, out: dict[str, Any] | None = None) -> None:
            if out is not None:
                out.clear()
                out.update({"Trash": [{"ShareID": "share-1", "LinkIDs": ["gone-1"]}]})

    svc = DriveService(FakeClient())
    with (
        caplog.at_level(logging.WARNING),
        patch.object(svc, "_get_link", side_effect=RuntimeError("link gone")),
    ):
        rows = svc.trash_list(_folder_dc())
    assert len(rows) == 1
    assert rows[0].link_id == "gone-1"
    assert rows[0].type == 0
    assert any(
        "trash" in r.message.lower() and "gone-1" in r.message and "link gone" in r.message.lower()
        for r in caplog.records
    )


def test_create_folder_signature_address_non_empty() -> None:
    """``create_folder`` POST body carries a non-empty ``SignatureAddress``."""
    calls: list[Any] = []

    class FakeClient:
        def decode(self, req: Any, out: dict[str, Any] | None = None) -> None:
            calls.append(req)

    svc = DriveService(FakeClient())
    dc = _folder_dc()
    parent = MagicMock(
        share_id="share-1",
        link_id="parent-1",
        node_key=MagicMock(),
        is_folder=True,
    )
    with (
        patch.object(svc, "resolve_path", return_value=parent),
        patch.object(svc, "_get_link", return_value=Link(link_id="parent-1", type=1)),
        patch("proton_cli.service.drive.crypto.hash_key_of", return_value=b"\x00" * 32),
        patch("proton_cli.service.drive.crypto.lookup_hash", return_value="digest"),
        patch("proton_cli.service.drive.crypto.encrypt_name", return_value="enc-name"),
        patch(
            "proton_cli.service.drive.crypto.gen_node_keys",
            return_value=("arm", "pass", "sig", MagicMock(), "phrase"),
        ),
        patch("proton_cli.service.drive.crypto.gen_node_hash_key", return_value="hk"),
    ):
        svc.create_folder(dc, "/Photos")
    assert len(calls) == 1
    assert calls[0].method == "POST"
    assert calls[0].body["SignatureAddress"] == "a@proton.me"


def test_drive_items_list_cli_mocked() -> None:
    with (
        patch("proton_cli.cli.drive_cmd._run") as run_app,
        patch("proton_cli.cli.drive_cmd._drive_ctx", return_value=MagicMock()),
    ):
        app = MagicMock()
        app.drive_svc.list_children.return_value = [
            Child(link_id="c1", name="readme.txt", type=2, size=4),
        ]
        app.renderer.format.value = "text"
        run_app.return_value = app
        result = runner.invoke(root_app, ["drive", "items", "list", "/"])
    assert result.exit_code == 0
    app.drive_svc.list_children.assert_called_once()


def test_drive_items_upload_download_cli_mocked() -> None:
    with (
        patch("proton_cli.cli.drive_cmd._run") as run_app,
        patch("proton_cli.cli.drive_cmd._drive_ctx", return_value=MagicMock()),
    ):
        app = MagicMock()
        app.dry_run = False
        app.renderer.format.value = "text"
        run_app.return_value = app

        def _download(_dc: Any, _path: str, writer: Any) -> None:
            writer.write(b"payload")

        app.drive_svc.download.side_effect = _download
        up = runner.invoke(
            root_app,
            ["drive", "items", "upload", "-", "/"],
            input=b"hello",
        )
        assert up.exit_code == 0
        app.drive_svc.upload.assert_called_once()
        down = runner.invoke(
            root_app,
            ["drive", "items", "download", "/readme.txt", "--output", "-"],
        )
    assert down.exit_code == 0
    app.drive_svc.download.assert_called_once()


def test_drive_items_trash_delete_cli_mocked() -> None:
    with (
        patch("proton_cli.cli.drive_cmd._run") as run_app,
        patch("proton_cli.cli.drive_cmd._drive_ctx", return_value=MagicMock()),
    ):
        app = MagicMock()
        app.dry_run = False
        run_app.return_value = app
        trash = runner.invoke(root_app, ["drive", "items", "trash", "/x"])
        delete = runner.invoke(root_app, ["drive", "items", "delete", "/x"])
    assert trash.exit_code == 0
    assert delete.exit_code == 0
    assert app.drive_svc.delete.call_count == 2


def test_drive_folders_create_cli_mocked() -> None:
    with (
        patch("proton_cli.cli.drive_cmd._run") as run_app,
        patch("proton_cli.cli.drive_cmd._drive_ctx", return_value=MagicMock()),
    ):
        app = MagicMock()
        app.dry_run = False
        run_app.return_value = app
        result = runner.invoke(root_app, ["drive", "folders", "create", "/Photos"])
    assert result.exit_code == 0
    app.drive_svc.create_folder.assert_called_once()


def test_drive_trash_list_restore_empty_cli_mocked() -> None:
    with (
        patch("proton_cli.cli.drive_cmd._run") as run_app,
        patch("proton_cli.cli.drive_cmd._drive_ctx", return_value=MagicMock()),
    ):
        app = MagicMock()
        app.dry_run = False
        app.renderer.format.value = "text"
        app.drive_svc.trash_list.return_value = [
            TrashEntry(share_id="s1", link_id="l1", type=2, size=1),
        ]
        run_app.return_value = app
        listed = runner.invoke(root_app, ["drive", "trash", "list"])
        restored = runner.invoke(root_app, ["drive", "trash", "restore", "l1"])
        emptied = runner.invoke(root_app, ["drive", "trash", "empty"])
    assert listed.exit_code == 0
    assert restored.exit_code == 0
    assert emptied.exit_code == 0
    app.drive_svc.trash_list.assert_called_once()
    app.drive_svc.trash_restore.assert_called_once()
    app.drive_svc.trash_empty.assert_called_once()
