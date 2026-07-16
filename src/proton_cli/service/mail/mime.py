"""MIME helpers for Proton Mail send."""

from __future__ import annotations

import base64
import mimetypes
import secrets
from dataclasses import dataclass
from email import policy
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path


@dataclass
class PreparedAttachment:
    filename: str
    mime_type: str
    data: bytes
    content_id: str = ""


@dataclass
class InlineAttachment:
    filename: str
    mime_type: str
    data: bytes


def prepare_attachments(
    paths: list[str],
    inline: list[InlineAttachment] | None = None,
) -> list[PreparedAttachment]:
    out: list[PreparedAttachment] = []
    for path in paths:
        data = Path(path).read_bytes()
        mime_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
        out.append(PreparedAttachment(filename=Path(path).name, mime_type=mime_type, data=data))
    for item in inline or []:
        mime_type = item.mime_type or "application/octet-stream"
        out.append(
            PreparedAttachment(
                filename=item.filename,
                mime_type=mime_type,
                data=item.data,
            )
        )
    return out


def prepare_inline_images(
    body: str, paths: list[str], sender_email: str
) -> tuple[str, list[PreparedAttachment]]:
    if not paths:
        return body, []
    out: list[PreparedAttachment] = []
    images: list[str] = []
    domain = sender_email.split("@")[-1] if "@" in sender_email else "proton.me"
    for path in paths:
        data = Path(path).read_bytes()
        mime_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
        cid = f"{secrets.token_hex(8)}@{domain}"
        images.append(f'<img src="cid:{cid}" alt="{Path(path).name}">')
        out.append(
            PreparedAttachment(
                filename=Path(path).name,
                mime_type=mime_type,
                data=data,
                content_id=cid,
            )
        )
    return body + "".join(images), out


def build_mime_message(body: str, mime_type: str, attachments: list[PreparedAttachment]) -> str:
    if not attachments:
        return body
    if mime_type == "":
        mime_type = "text/plain"
    root = MIMEMultipart("mixed", policy=policy.SMTP)
    body_part = MIMEText(body, _subtype_from_mime(mime_type), "utf-8", policy=policy.SMTP)
    body_part.replace_header("Content-Transfer-Encoding", "base64")
    body_part.set_payload(base64.b64encode(body.encode()).decode(), charset="utf-8")
    root.attach(body_part)
    for attachment in attachments:
        part = MIMEText(
            _wrap_base64(attachment.data).decode(),
            "octet-stream",
            "utf-8",
            policy=policy.SMTP,
        )
        part.replace_header("Content-Type", f'{attachment.mime_type}; name="{attachment.filename}"')
        part.replace_header("Content-Transfer-Encoding", "base64")
        if attachment.content_id:
            part.add_header("Content-Disposition", f'inline; filename="{attachment.filename}"')
            part.add_header("Content-ID", f"<{attachment.content_id}>")
        else:
            part.add_header("Content-Disposition", f'attachment; filename="{attachment.filename}"')
        root.attach(part)
    payload = root.as_bytes(policy=policy.SMTP)
    lines = payload.decode().split("\r\n\r\n", 1)
    if len(lines) == 2:
        return lines[0] + "\r\n\r\n" + lines[1] + "\r\n"
    return payload.decode() + "\r\n"


def _subtype_from_mime(mime_type: str) -> str:
    if "/" in mime_type:
        return mime_type.split("/", 1)[1].split(";", 1)[0]
    return "plain"


def _wrap_base64(data: bytes) -> bytes:
    encoded = base64.b64encode(data).decode()
    lines: list[str] = []
    while len(encoded) > 76:
        lines.append(encoded[:76])
        encoded = encoded[76:]
    lines.append(encoded)
    return "\r\n".join(lines).encode()
