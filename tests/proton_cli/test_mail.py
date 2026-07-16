"""Tests for mail service helpers."""

from __future__ import annotations

from proton_cli.service.mail.folders import resolve_folder
from proton_cli.service.mail.service import ListOptions, MailService, _dedupe, _recipient_list


def test_resolve_folder_aliases() -> None:
    assert resolve_folder("inbox") == "0"
    assert resolve_folder("sent") == "7"
    assert resolve_folder("custom-label-id") == "custom-label-id"


def test_recipient_list_and_dedupe() -> None:
    assert _recipient_list(["a@x.com", ""]) == [{"Address": "a@x.com", "Name": ""}]
    assert _dedupe(["a@x.com", "a@x.com", "b@x.com"]) == ["a@x.com", "b@x.com"]


def test_list_messages_mock_client() -> None:
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
