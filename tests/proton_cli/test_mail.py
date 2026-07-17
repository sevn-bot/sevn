"""Tests for mail service helpers.

Exports:
    test_mail_command_registered
    test_resolve_folder_aliases
    test_recipient_list_and_dedupe
    test_list_messages_mock_client
"""

from __future__ import annotations

from typer.testing import CliRunner

from proton_cli.cli.root import app as root_app
from proton_cli.service.mail.folders import resolve_folder
from proton_cli.service.mail.service import ListOptions, MailService, _dedupe, _recipient_list


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
