"""Proton Mail operations."""

from __future__ import annotations

import base64
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pgpy import PGPKey, PGPMessage

from proton_cli.account.keys import use_unlocked_key
from proton_cli.proton.client import Client, Request
from proton_cli.ref import pick
from proton_cli.service.drive import blocks
from proton_cli.service.mail import crypto as mail_crypto
from proton_cli.service.mail import mime as mail_mime
from proton_cli.service.mail.folders import LABEL_STARRED, LABEL_TRASH, resolve_folder

if TYPE_CHECKING:
    from proton_cli.account.keys import Unlocked

PKG_INTERNAL = 1
PKG_CLEAR = 4


@dataclass
class MessageSummary:
    id: str
    subject: str
    from_address: str = ""
    from_name: str = ""
    time: int = 0
    unread: int = 0
    num_attachments: int = 0


@dataclass
class MessageFull:
    id: str
    subject: str
    body: str = ""
    mime_type: str = ""
    from_address: str = ""
    from_name: str = ""
    time: int = 0
    to_list: list[dict[str, object]] = field(default_factory=list)
    signature: str = "unverified"


@dataclass
class Label:
    id: str
    name: str
    color: str = ""
    type: int = 0
    path: str = ""


@dataclass
class ListOptions:
    folder: str = "inbox"
    page: int = 0
    page_size: int = 25
    unread: bool = False


@dataclass
class SearchOptions:
    keyword: str = ""
    sender: str = ""
    recipient: str = ""
    subject: str = ""
    folder: str = "all"
    after: str = ""
    before: str = ""
    limit: int = 25
    unread: bool = False


@dataclass
class InlineAttachment:
    filename: str
    mime_type: str
    data: bytes


@dataclass
class Attachment:
    id: str
    name: str = ""
    size: int = 0
    mime_type: str = ""
    disposition: str = ""


@dataclass
class UploadedAttachment:
    id: str
    session_key: blocks.SessionKey


@dataclass
class SendOptions:
    to: list[str]
    subject: str
    body: str
    cc: list[str] = field(default_factory=list)
    bcc: list[str] = field(default_factory=list)
    html: bool = False
    attachments: list[str] = field(default_factory=list)
    inline_attach: list[str] = field(default_factory=list)
    inline_attachments: list[InlineAttachment] = field(default_factory=list)


class MailService:
    def __init__(self, client: Client) -> None:
        self._client = client

    def list_messages(self, opts: ListOptions) -> tuple[list[MessageSummary], int]:
        query = {
            "LabelID": resolve_folder(opts.folder),
            "Page": str(opts.page),
            "PageSize": str(max(opts.page_size, 1)),
            "Sort": "Time",
            "Desc": "1",
        }
        if opts.unread:
            query["Unread"] = "1"
        payload: dict = {}
        self._client.decode(Request(method="GET", path="/mail/v4/messages", query=query), payload)
        total = int(payload.get("Total", 0) or 0)
        out: list[MessageSummary] = []
        for raw in payload.get("Messages") or []:
            sender = raw.get("Sender") or {}
            out.append(
                MessageSummary(
                    id=str(raw.get("ID", "")),
                    subject=str(raw.get("Subject", "")),
                    from_address=str(sender.get("Address", "")),
                    from_name=str(sender.get("Name", "")),
                    time=int(raw.get("Time", 0) or 0),
                    unread=int(raw.get("Unread", 0) or 0),
                    num_attachments=int(raw.get("NumAttachments", 0) or 0),
                )
            )
        return out, total

    def search_messages(self, opts: SearchOptions) -> tuple[list[MessageSummary], int]:
        query = {
            "LabelID": resolve_folder(opts.folder or "all"),
            "Sort": "Time",
            "Desc": "1",
            "PageSize": str(max(opts.limit, 1)),
        }
        if opts.unread:
            query["Unread"] = "1"
        if opts.keyword:
            query["Keyword"] = opts.keyword
        if opts.sender:
            query["From"] = opts.sender
        if opts.recipient:
            query["To"] = opts.recipient
        if opts.subject:
            query["Subject"] = opts.subject
        if opts.after:
            query["Begin"] = str(_parse_date(opts.after))
        if opts.before:
            query["End"] = str(_parse_date(opts.before))
        payload: dict = {}
        self._client.decode(Request(method="GET", path="/mail/v4/messages", query=query), payload)
        total = int(payload.get("Total", 0) or 0)
        out: list[MessageSummary] = []
        for raw in payload.get("Messages") or []:
            sender = raw.get("Sender") or {}
            out.append(
                MessageSummary(
                    id=str(raw.get("ID", "")),
                    subject=str(raw.get("Subject", "")),
                    from_address=str(sender.get("Address", "")),
                    from_name=str(sender.get("Name", "")),
                    time=int(raw.get("Time", 0) or 0),
                    unread=int(raw.get("Unread", 0) or 0),
                    num_attachments=int(raw.get("NumAttachments", 0) or 0),
                )
            )
        return out, total

    def read_message(self, unlocked: Unlocked, message_id: str) -> MessageFull:
        payload: dict = {}
        self._client.decode(
            Request(method="GET", path=f"/mail/v4/messages/{message_id}"),
            payload,
        )
        raw = payload.get("Message") or {}
        address_id = str(raw.get("AddressID", ""))
        addr_keys = unlocked.addr_keys.get(address_id)
        if not addr_keys:
            _keys, _aid, _email = unlocked.primary_addr()
            addr_keys = _keys
        body, sig = mail_crypto.decrypt_body(str(raw.get("Body", "")), addr_keys or [])
        sender = raw.get("Sender") or {}
        return MessageFull(
            id=str(raw.get("ID", "")),
            subject=str(raw.get("Subject", "")),
            body=body,
            mime_type=str(raw.get("MIMEType", "")),
            from_address=str(sender.get("Address", "")),
            from_name=str(sender.get("Name", "")),
            time=int(raw.get("Time", 0) or 0),
            to_list=list(raw.get("ToList") or []),
            signature=sig,
        )

    def resolve_message(self, message_ref: str, messages: list[MessageSummary]) -> str:
        for msg in messages:
            if msg.id == message_ref:
                return msg.id
        needle = message_ref.lower()
        matches = [
            m for m in messages if needle in m.subject.lower() or needle in m.from_address.lower()
        ]
        chosen = pick(
            "message",
            message_ref,
            matches,
            lambda m: m.id,
            lambda m: f"{m.from_address}  {m.subject}",
        )
        return chosen.id

    def labels_list(self) -> tuple[list[Label], list[Label]]:
        labels_payload: dict = {}
        folders_payload: dict = {}
        self._client.decode(
            Request(method="GET", path="/core/v4/labels", query={"Type": "1"}),
            labels_payload,
        )
        self._client.decode(
            Request(method="GET", path="/core/v4/labels", query={"Type": "3"}),
            folders_payload,
        )

        def _map_items(payload: dict) -> list[Label]:
            return [
                Label(
                    id=str(item.get("ID", "")),
                    name=str(item.get("Name", "")),
                    color=str(item.get("Color", "")),
                    type=int(item.get("Type", 0) or 0),
                    path=str(item.get("Path", "")),
                )
                for item in payload.get("Labels") or []
            ]

        return _map_items(labels_payload), _map_items(folders_payload)

    def trash(self, ids: list[str]) -> None:
        self._client.decode(
            Request(
                method="PUT",
                path="/mail/v4/messages/label",
                body={"LabelID": LABEL_TRASH, "IDs": ids},
            )
        )

    def delete(self, ids: list[str]) -> None:
        self._client.decode(
            Request(method="PUT", path="/mail/v4/messages/delete", body={"IDs": ids}),
        )

    def move(self, ids: list[str], folder: str) -> None:
        self._client.decode(
            Request(
                method="PUT",
                path="/mail/v4/messages/label",
                body={"LabelID": resolve_folder(folder), "IDs": ids},
            )
        )

    def mark_read(self, ids: list[str]) -> None:
        self._client.decode(
            Request(method="PUT", path="/mail/v4/messages/read", body={"IDs": ids}),
        )

    def mark_unread(self, ids: list[str]) -> None:
        self._client.decode(
            Request(method="PUT", path="/mail/v4/messages/unread", body={"IDs": ids}),
        )

    def star(self, ids: list[str]) -> None:
        self._client.decode(
            Request(
                method="PUT",
                path="/mail/v4/messages/label",
                body={"LabelID": LABEL_STARRED, "IDs": ids},
            )
        )

    def unstar(self, ids: list[str]) -> None:
        self._client.decode(
            Request(
                method="PUT",
                path="/mail/v4/messages/unlabel",
                body={"LabelID": LABEL_STARRED, "IDs": ids},
            )
        )

    def send(self, unlocked: Unlocked, opts: SendOptions) -> str:
        """Send a message to internal and cleartext recipients (with optional attachments)."""
        if not opts.to:
            raise ValueError("at least one --to recipient is required")
        addr_keys, _addr_id, sender_email = unlocked.primary_addr()
        mime_type = "text/html" if opts.html else "text/plain"
        body = opts.body
        if opts.inline_attach:
            if not opts.html:
                raise ValueError("--attach-inline requires --html")
            body, inline_prepared = mail_mime.prepare_inline_images(
                body,
                opts.inline_attach,
                sender_email,
            )
        else:
            inline_prepared = []
        prepared = mail_mime.prepare_attachments(opts.attachments, opts.inline_attachments)
        prepared.extend(inline_prepared)
        if prepared:
            body = mail_mime.build_mime_message(body, mime_type, prepared)
            mime_type = "multipart/mixed"

        message = PGPMessage.new(body)
        with use_unlocked_key(addr_keys[0]):
            enc = addr_keys[0].encrypt(message)
        armored = str(enc)

        draft_payload: dict = {}
        self._client.decode(
            Request(
                method="POST",
                path="/mail/v4/messages",
                body={
                    "Message": {
                        "ToList": _recipient_list(opts.to),
                        "CCList": _recipient_list(opts.cc),
                        "BCCList": _recipient_list(opts.bcc),
                        "Subject": opts.subject,
                        "Sender": {"Address": sender_email, "Name": ""},
                        "Body": armored,
                        "MIMEType": mime_type,
                    }
                },
            ),
            draft_payload,
        )
        message_id = str((draft_payload.get("Message") or {}).get("ID", ""))
        if not message_id:
            raise ValueError("draft creation did not return a message id")

        uploaded: list[UploadedAttachment] = []
        for attachment in prepared:
            uploaded.append(
                self._upload_attachment_data(
                    addr_keys[0],
                    message_id,
                    attachment.filename,
                    attachment.mime_type,
                    attachment.content_id,
                    attachment.data,
                )
            )

        plans = []
        for email in _dedupe(opts.to + opts.cc + opts.bcc):
            scheme, armored_key = self._classify_recipient(email)
            plans.append((email, scheme, armored_key))

        packages = self._build_body_packages(body, mime_type, plans, addr_keys, uploaded)
        try:
            self._client.decode(
                Request(
                    method="POST",
                    path=f"/mail/v4/messages/{message_id}",
                    body={"ExpirationTime": None, "AutoSaveContacts": 0, "Packages": packages},
                )
            )
        except Exception:
            self.delete([message_id])
            raise
        return message_id

    def attachments_list(self, message_id: str, include_inline: bool = False) -> list[Attachment]:
        payload: dict = {}
        self._client.decode(
            Request(method="GET", path=f"/mail/v4/messages/{message_id}"),
            payload,
        )
        out: list[Attachment] = []
        for raw in (payload.get("Message") or {}).get("Attachments") or []:
            disposition = str(raw.get("Disposition", ""))
            if not include_inline and disposition == "inline":
                continue
            out.append(
                Attachment(
                    id=str(raw.get("ID", "")),
                    name=str(raw.get("Name", "")),
                    size=int(raw.get("Size", 0) or 0),
                    mime_type=str(raw.get("MIMEType", "")),
                    disposition=disposition,
                )
            )
        return out

    def attachment_download(
        self, unlocked: Unlocked, message_id: str, attachment_id: str
    ) -> tuple[bytes, str]:
        payload: dict = {}
        self._client.decode(
            Request(method="GET", path=f"/mail/v4/messages/{message_id}"),
            payload,
        )
        raw_message = payload.get("Message") or {}
        address_id = str(raw_message.get("AddressID", ""))
        addr_keys = unlocked.addr_keys.get(address_id)
        if not addr_keys:
            addr_keys, _, _ = unlocked.primary_addr()
        key_packets = ""
        name = ""
        for raw in raw_message.get("Attachments") or []:
            if str(raw.get("ID", "")) == attachment_id:
                key_packets = str(raw.get("KeyPackets", ""))
                name = str(raw.get("Name", ""))
                break
        if not key_packets:
            from proton_cli.errors import NotFound

            raise NotFound("attachment", attachment_id)
        response = self._client.do(
            Request(method="GET", path=f"/mail/v4/attachments/{attachment_id}")
        )
        key_packet = base64.b64decode(key_packets)
        sk = blocks.decrypt_session_key_packet(key_packet, addr_keys[0])
        return blocks.decrypt_block(response.body, sk), name

    def _upload_attachment_data(
        self,
        addr_key: PGPKey,
        message_id: str,
        filename: str,
        mime_type: str,
        content_id: str,
        data: bytes,
    ) -> UploadedAttachment:
        sk = blocks.make_session_key()
        data_packet = blocks.encrypt_data_packet(data, sk)
        key_packet = blocks.encrypt_session_key_packet(addr_key, sk)
        with use_unlocked_key(addr_key):
            sig = addr_key.sign(PGPMessage.new(data))
        sig_bytes = bytes(sig)
        body, content_type = _build_attachment_form(
            {
                "Filename": filename,
                "MessageID": message_id,
                "ContentID": content_id,
                "MIMEType": mime_type,
            },
            {
                "KeyPackets": key_packet,
                "DataPacket": data_packet,
                "Signature": sig_bytes,
            },
        )
        payload: dict = {}
        self._client.decode(
            Request(
                method="POST",
                path="/mail/v4/attachments",
                body=body,
                content_type=content_type,
            ),
            payload,
        )
        att_id = str((payload.get("Attachment") or {}).get("ID", ""))
        return UploadedAttachment(id=att_id, session_key=sk)

    def _classify_recipient(self, email: str) -> tuple[int, str]:
        payload: dict = {}
        self._client.decode(
            Request(
                method="GET",
                path="/core/v4/keys/all",
                query={"Email": email, "InternalOnly": "0"},
            ),
            payload,
        )
        address = payload.get("Address") or {}
        for key in address.get("Keys") or []:
            if int(key.get("Flags", 0) or 0) & 4 == 0:
                return PKG_INTERNAL, str(key.get("PublicKey", ""))
        return PKG_CLEAR, ""

    def _build_body_packages(
        self,
        body: str,
        mime_type: str,
        plans: list[tuple[str, int, str]],
        addr_keys: list,
        attachments: list[UploadedAttachment] | None = None,
    ) -> list[dict[str, object]]:
        session_key = blocks.make_session_key()
        enc_body = blocks.encrypt_plaintext(body, session_key)
        body_b64 = base64.b64encode(enc_body).decode()

        internal_addrs: dict[str, object] = {}
        clear_addrs: dict[str, object] = {}
        for email, scheme, armored_key in plans:
            if scheme == PKG_INTERNAL and armored_key:
                rec_key, _ = PGPKey.from_blob(armored_key)
                rec_kp = blocks.encrypt_session_key_packet(rec_key, session_key)
                addr_entry: dict[str, object] = {
                    "Type": PKG_INTERNAL,
                    "BodyKeyPacket": base64.b64encode(rec_kp).decode(),
                    "Signature": 0,
                }
                att_packets = _attachment_key_packets(rec_key, attachments or [])
                if att_packets:
                    addr_entry["AttachmentKeyPackets"] = att_packets
                internal_addrs[email] = addr_entry
            else:
                clear_addrs[email] = {"Type": PKG_CLEAR, "Signature": 0}

        packages: list[dict[str, object]] = []
        if internal_addrs:
            sender_kp = blocks.encrypt_session_key_packet(addr_keys[0], session_key)
            packages.append(
                {
                    "Addresses": internal_addrs,
                    "MIMEType": mime_type,
                    "Type": PKG_INTERNAL,
                    "Body": body_b64,
                    "BodyKeyPacket": base64.b64encode(sender_kp).decode(),
                }
            )
        if clear_addrs:
            packages.append(
                {
                    "Addresses": clear_addrs,
                    "MIMEType": mime_type,
                    "Type": PKG_CLEAR,
                    "Body": body_b64,
                }
            )
        return packages


def _recipient_list(emails: list[str]) -> list[dict[str, str]]:
    return [{"Address": e, "Name": ""} for e in emails if e]


def _dedupe(emails: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for email in emails:
        if email and email not in seen:
            seen.add(email)
            out.append(email)
    return out


def _parse_date(value: str) -> int:
    return int(datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC).timestamp())


def _attachment_key_packets(
    recipient_key: PGPKey,
    attachments: list[UploadedAttachment],
) -> dict[str, str]:
    if not attachments:
        return {}
    out: dict[str, str] = {}
    for attachment in attachments:
        kp = blocks.encrypt_session_key_packet(recipient_key, attachment.session_key)
        out[attachment.id] = base64.b64encode(kp).decode()
    return out


def _build_attachment_form(
    fields: dict[str, str],
    files: dict[str, bytes],
) -> tuple[bytes, str]:
    boundary = "proton-cli-attach-" + secrets.token_hex(8)
    lines: list[bytes] = []
    for key, value in fields.items():
        lines.append(f"--{boundary}\r\n".encode())
        lines.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode())
        lines.append(f"{value}\r\n".encode())
    for name, data in files.items():
        lines.append(f"--{boundary}\r\n".encode())
        lines.append(
            f'Content-Disposition: form-data; name="{name}"; filename="{name}"\r\n'.encode()
        )
        lines.append(b"Content-Type: application/octet-stream\r\n\r\n")
        lines.append(data)
        lines.append(b"\r\n")
    lines.append(f"--{boundary}--\r\n".encode())
    body = b"".join(lines)
    return body, f"multipart/form-data; boundary={boundary}"
