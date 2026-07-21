"""Tests for mail service helpers and CLI commands.

Exports:
    test_mail_command_registered
    test_resolve_folder_aliases
    test_recipient_list_and_dedupe
    test_list_messages_mock_client
    test_mail_search_cli_mocked
    test_mail_read_cli_mocked
    test_mail_send_cli_mocked
    test_mail_trash_delete_move_cli_mocked
    test_mail_labels_list_cli_mocked
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from proton_cli.cli.root import app as root_app
from proton_cli.service.mail.folders import resolve_folder
from proton_cli.service.mail.service import ListOptions, MailService, _dedupe, _recipient_list

runner = CliRunner()


def test_mail_command_registered() -> None:
    """``mail`` is registered on the root CLI.

    Returns:
        None

    Examples:
        >>> from typer.testing import CliRunner
        >>> from proton_cli.cli.root import app as root_app
        >>> result = CliRunner().invoke(root_app, ["mail", "--help"])
        >>> result.exit_code == 0 and "messages" in result.output
        True
    """
    result = CliRunner().invoke(root_app, ["mail", "--help"])
    assert result.exit_code == 0
    assert "messages" in result.output


def test_resolve_folder_aliases() -> None:
    """Built-in folder aliases map to Proton label ids.

    Returns:
        None

    Examples:
        >>> from proton_cli.service.mail.folders import resolve_folder
        >>> resolve_folder("inbox")
        '0'
    """
    assert resolve_folder("inbox") == "0"
    assert resolve_folder("sent") == "7"
    assert resolve_folder("custom-label-id") == "custom-label-id"


def test_recipient_list_and_dedupe() -> None:
    """Recipient helpers skip blanks and dedupe addresses.

    Returns:
        None

    Examples:
        >>> from proton_cli.service.mail.service import _dedupe
        >>> _dedupe(["a@x.com", "a@x.com"])
        ['a@x.com']
    """
    assert _recipient_list(["a@x.com", ""]) == [{"Address": "a@x.com", "Name": ""}]
    assert _dedupe(["a@x.com", "a@x.com", "b@x.com"]) == ["a@x.com", "b@x.com"]


def test_list_messages_mock_client() -> None:
    """``list_messages`` maps API payloads into summaries.

    Returns:
        None

    Examples:
        >>> True
        True
    """

    class FakeClient:
        def decode(self, req, out):
            assert req.path == "/mail/v4/messages"
            out.clear()
            out.update(
                {
                    "Total": 1,
                    "Messages": [
                        {
                            "ID": "msg-1",
                            "Subject": "Hello",
                            "Sender": {"Address": "a@proton.me", "Name": "A"},
                            "Time": 1710000000,
                            "Unread": 1,
                            "NumAttachments": 0,
                        }
                    ],
                }
            )

    svc = MailService(FakeClient())
    rows, total = svc.list_messages(ListOptions())
    assert total == 1
    assert rows[0].id == "msg-1"
    assert rows[0].subject == "Hello"


def test_mail_search_cli_mocked() -> None:
    """``mail messages search`` drives ``search_messages`` with keyword options."""
    with patch("proton_cli.cli.mail_cmd._run") as run_app:
        app = MagicMock()
        app.mail_svc.search_messages.return_value = ([], 0)
        app.renderer.format.value = "text"
        run_app.return_value = app
        result = runner.invoke(
            root_app,
            ["mail", "messages", "search", "--keyword", "invoice", "--from", "a@x.com"],
        )
    assert result.exit_code == 0
    opts = app.mail_svc.search_messages.call_args.args[0]
    assert opts.keyword == "invoice"
    assert opts.sender == "a@x.com"


def test_mail_read_cli_mocked() -> None:
    """``mail messages read`` resolves then decrypts via ``read_message``."""
    with patch("proton_cli.cli.mail_cmd._run") as run_app:
        app = MagicMock()
        app.mail_svc.list_messages.return_value = ([], 0)
        app.mail_svc.resolve_message.return_value = "msg-1"
        app.mail_svc.read_message.return_value = MagicMock(subject="Hi", body="body")
        app.renderer.format.value = "json"
        run_app.return_value = app
        result = runner.invoke(root_app, ["mail", "messages", "read", "msg-1"])
    assert result.exit_code == 0
    app.mail_svc.resolve_message.assert_called_once()
    app.mail_svc.read_message.assert_called_once()


def test_mail_send_cli_mocked() -> None:
    """``mail messages send`` calls ``send`` with recipients and subject."""
    with patch("proton_cli.cli.mail_cmd._run") as run_app:
        app = MagicMock()
        app.dry_run = False
        app.mail_svc.send.return_value = "sent-1"
        app.renderer.format.value = "text"
        run_app.return_value = app
        result = runner.invoke(
            root_app,
            [
                "mail",
                "messages",
                "send",
                "--to",
                "b@x.com",
                "--subject",
                "Hello",
                "--body",
                "hi",
            ],
        )
    assert result.exit_code == 0
    app.mail_svc.send.assert_called_once()
    send_opts = app.mail_svc.send.call_args.args[1]
    assert send_opts.to == ["b@x.com"]
    assert send_opts.subject == "Hello"
    assert send_opts.body == "hi"


def test_mail_trash_delete_move_cli_mocked() -> None:
    """Trash / delete / move invoke the matching MailService mutators."""
    with patch("proton_cli.cli.mail_cmd._run") as run_app:
        app = MagicMock()
        app.dry_run = False
        app.renderer.format.value = "text"
        run_app.return_value = app
        assert runner.invoke(root_app, ["mail", "messages", "trash", "msg-1"]).exit_code == 0
        app.mail_svc.trash.assert_called_once_with(["msg-1"])
        assert runner.invoke(root_app, ["mail", "messages", "delete", "msg-1"]).exit_code == 0
        app.mail_svc.delete.assert_called_once_with(["msg-1"])
        assert (
            runner.invoke(
                root_app,
                ["mail", "messages", "move", "msg-1", "--folder", "archive"],
            ).exit_code
            == 0
        )
        app.mail_svc.move.assert_called_once_with(["msg-1"], "archive")


def test_mail_labels_list_cli_mocked() -> None:
    """``mail labels list`` renders labels and folders from the service."""
    label = MagicMock(id="l1", name="Work", type=1)
    folder = MagicMock(id="f1", name="Archive", type=3)
    with patch("proton_cli.cli.mail_cmd._run") as run_app:
        app = MagicMock()
        app.mail_svc.labels_list.return_value = ([label], [folder])
        app.renderer.format.value = "text"
        run_app.return_value = app
        result = runner.invoke(root_app, ["mail", "labels", "list"])
    assert result.exit_code == 0
    app.mail_svc.labels_list.assert_called_once()
