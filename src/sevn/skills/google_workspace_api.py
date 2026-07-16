"""Google Workspace API operations for bundled skill scripts.

Module: sevn.skills.google_workspace_api
Depends: base64, datetime, email.mime.text, mimetypes, sevn.skills.google_workspace

Exports:
    calendar_create — create a calendar event.
    calendar_delete — delete a calendar event.
    calendar_list — list upcoming calendar events.
    contacts_list — list Google contacts via People API.
    docs_append — append text to a Google Doc.
    docs_create — create a Google Doc.
    docs_get — fetch one Google Doc and extract body text.
    drive_get — get Drive file metadata.
    drive_create_folder — create a Drive folder.
    drive_delete — trash or permanently delete a Drive file.
    drive_download — download or export a Drive file.
    drive_search — search Drive files.
    drive_share — share a Drive file.
    drive_upload — upload a local file to Drive.
    gmail_get — fetch one Gmail message.
    gmail_labels — list Gmail labels.
    gmail_modify — add/remove Gmail labels.
    gmail_reply — reply to a Gmail thread.
    gmail_search — search Gmail messages.
    gmail_send — send a Gmail message.
    sheets_append — append values to a Google Sheet.
    sheets_create — create a Google Sheet.
    sheets_get — fetch a Sheet range.
    sheets_update — update a Sheet range.
"""

from __future__ import annotations

import base64
import mimetypes
import os
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from pathlib import Path
from typing import Final, Iterable

from sevn.skills import google_workspace

_GMAIL_METADATA_HEADERS: Final[list[str]] = ["From", "To", "Subject", "Date", "Message-ID"]


def _headers_dict(message: dict[str, object]) -> dict[str, str]:
    """Return lower-cased Gmail headers from a message resource."""

    payload = message.get("payload", {})
    headers = payload.get("headers", []) if isinstance(payload, dict) else []
    output: dict[str, str] = {}
    for row in headers:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name", "")).strip().lower()
        if not name:
            continue
        output[name] = str(row.get("value", ""))
    return output


def _decode_b64url(data: str) -> str:
    """Decode a Gmail urlsafe base64 payload fragment."""

    padding = "=" * ((4 - len(data) % 4) % 4)
    return base64.urlsafe_b64decode(f"{data}{padding}").decode("utf-8", errors="replace")


def _extract_message_body(message: dict[str, object]) -> str:
    """Extract the most useful body text from a Gmail message payload."""

    payload = message.get("payload", {})
    if not isinstance(payload, dict):
        return ""
    body = payload.get("body", {})
    if isinstance(body, dict):
        data = str(body.get("data", "")).strip()
        if data:
            return _decode_b64url(data)
    parts = payload.get("parts", [])
    if not isinstance(parts, list):
        return ""
    plain_text = ""
    html_text = ""
    stack: list[dict[str, object]] = [part for part in parts if isinstance(part, dict)]
    while stack:
        part = stack.pop(0)
        mime_type = str(part.get("mimeType", "")).strip().lower()
        part_body = part.get("body", {})
        data = str(part_body.get("data", "")).strip() if isinstance(part_body, dict) else ""
        if data and mime_type == "text/plain" and not plain_text:
            plain_text = _decode_b64url(data)
        elif data and mime_type == "text/html" and not html_text:
            html_text = _decode_b64url(data)
        nested = part.get("parts", [])
        if isinstance(nested, list):
            stack.extend(item for item in nested if isinstance(item, dict))
    return plain_text or html_text


def _gmail_summary_row(message: dict[str, object]) -> dict[str, object]:
    """Normalise a Gmail message resource to the Hermes summary shape."""

    headers = _headers_dict(message)
    return {
        "id": str(message.get("id", "")),
        "threadId": str(message.get("threadId", "")),
        "from": headers.get("from", ""),
        "to": headers.get("to", ""),
        "subject": headers.get("subject", ""),
        "date": headers.get("date", ""),
        "snippet": str(message.get("snippet", "")),
        "labels": [
            str(label)
            for label in message.get("labelIds", [])
            if isinstance(label, str) and label.strip()
        ],
    }


def _gmail_required_scopes() -> list[str]:
    """Return Gmail scopes used by read/write operations."""

    return list(google_workspace.SERVICE_SCOPE_SETS["email"])


def _calendar_scopes() -> list[str]:
    """Return Calendar scopes used by calendar operations."""

    return list(google_workspace.SERVICE_SCOPE_SETS["calendar"])


def _drive_scopes() -> list[str]:
    """Return Drive scopes used by drive operations."""

    return list(google_workspace.SERVICE_SCOPE_SETS["drive"])


def _contacts_scopes() -> list[str]:
    """Return People API scopes used by contact operations."""

    return list(google_workspace.SERVICE_SCOPE_SETS["contacts"])


def _sheets_scopes() -> list[str]:
    """Return Sheets scopes used by spreadsheet operations."""

    return list(google_workspace.SERVICE_SCOPE_SETS["sheets"])


def _docs_scopes() -> list[str]:
    """Return Docs scopes used by document operations."""

    return list(google_workspace.SERVICE_SCOPE_SETS["docs"])


def _workspace_path(workspace: str | Path) -> Path:
    """Normalize a workspace argument to an absolute path."""

    return Path(workspace).expanduser().resolve()


def _dry_run_requested() -> bool:
    """Return True when Google Workspace dry-run mode is enabled."""

    return google_workspace.dry_run_requested(env=os.environ)


def _dry_run(
    workspace: str | Path,
    *,
    service: str,
    operation: str,
    parameters: dict[str, object],
    scopes: Iterable[str],
) -> dict[str, object]:
    """Return a dry-run plan envelope when dry-run mode is enabled."""

    resolved = google_workspace.paths(_workspace_path(workspace))
    return {
        "mode": "dry_run",
        "service": service,
        "operation": operation,
        "parameters": parameters,
        "scopes": list(scopes),
        "token_path": str(resolved.token_path),
        "client_secret_path": str(resolved.client_secret_path),
    }


def _datetime_with_timezone(value: str | None) -> str | None:
    """Return ISO datetime with timezone info when missing."""

    if value is None:
        return None
    text = value.strip()
    if not text or "T" not in text or text.endswith("Z"):
        return text
    tail = text[10:]
    if "+" in tail or "-" in tail:
        return text
    return f"{text}Z"


def _extract_doc_text(document: dict[str, object]) -> str:
    """Extract plain text content from a Google Docs document resource."""

    text_parts: list[str] = []
    body = document.get("body", {})
    content = body.get("content", []) if isinstance(body, dict) else []
    for element in content:
        if not isinstance(element, dict):
            continue
        paragraph = element.get("paragraph", {})
        elements = paragraph.get("elements", []) if isinstance(paragraph, dict) else []
        for paragraph_element in elements:
            if not isinstance(paragraph_element, dict):
                continue
            text_run = paragraph_element.get("textRun", {})
            if not isinstance(text_run, dict):
                continue
            content_text = text_run.get("content")
            if isinstance(content_text, str) and content_text:
                text_parts.append(content_text)
    return "".join(text_parts)


def _docs_insert_text(workspace: str | Path, document_id: str, text: str, index: int) -> None:
    """Insert text into a Google Doc using a single batchUpdate request."""

    service = google_workspace.build_service(_workspace_path(workspace), "docs", "v1")
    service.documents().batchUpdate(
        documentId=document_id,
        body={
            "requests": [
                {
                    "insertText": {
                        "location": {"index": index},
                        "text": text,
                    },
                },
            ],
        },
    ).execute()


def gmail_search(workspace: str, query: str, max_results: int = 10) -> list[dict[str, object]] | dict[str, object]:
    """Search Gmail messages and return Hermes-style summary rows."""

    params = {"query": query, "max_results": max_results}
    if _dry_run_requested():
        return _dry_run(
            workspace,
            service="gmail",
            operation="search",
            parameters=params,
            scopes=_gmail_required_scopes(),
        )
    service = google_workspace.build_service(_workspace_path(workspace), "gmail", "v1")
    results = service.users().messages().list(
        userId="me",
        q=query,
        maxResults=max(max_results, 0),
    ).execute()
    messages = results.get("messages", []) if isinstance(results, dict) else []
    output: list[dict[str, object]] = []
    for message_meta in messages:
        if not isinstance(message_meta, dict) or "id" not in message_meta:
            continue
        message = service.users().messages().get(
            userId="me",
            id=message_meta["id"],
            format="metadata",
            metadataHeaders=["From", "To", "Subject", "Date"],
        ).execute()
        output.append(_gmail_summary_row(message))
    return output


def gmail_get(workspace: str, message_id: str) -> dict[str, object]:
    """Fetch one Gmail message with body text."""

    params = {"message_id": message_id}
    if _dry_run_requested():
        return _dry_run(
            workspace,
            service="gmail",
            operation="get",
            parameters=params,
            scopes=_gmail_required_scopes(),
        )
    service = google_workspace.build_service(_workspace_path(workspace), "gmail", "v1")
    message = service.users().messages().get(
        userId="me",
        id=message_id,
        format="full",
    ).execute()
    result = _gmail_summary_row(message)
    result["body"] = _extract_message_body(message)
    return result


def gmail_send(
    workspace: str,
    to: str,
    subject: str,
    body: str,
    html: bool = False,
    from_header: str | None = None,
    cc: str | None = None,
) -> dict[str, object]:
    """Send a Gmail message."""

    params = {
        "to": to,
        "subject": subject,
        "body_chars": len(body),
        "html": html,
        "from_header": from_header,
        "cc": cc,
    }
    if _dry_run_requested():
        return _dry_run(
            workspace,
            service="gmail",
            operation="send",
            parameters=params,
            scopes=_gmail_required_scopes(),
        )
    mime = MIMEText(body, "html" if html else "plain")
    mime["To"] = to
    mime["Subject"] = subject
    if cc:
        mime["Cc"] = cc
    if from_header:
        mime["From"] = from_header
    raw = base64.urlsafe_b64encode(mime.as_bytes()).decode("utf-8")
    service = google_workspace.build_service(_workspace_path(workspace), "gmail", "v1")
    result = service.users().messages().send(
        userId="me",
        body={"raw": raw},
    ).execute()
    return {
        "status": "sent",
        "id": str(result.get("id", "")),
        "threadId": str(result.get("threadId", "")),
    }


def gmail_reply(
    workspace: str,
    message_id: str,
    body: str,
    from_header: str | None = None,
) -> dict[str, object]:
    """Reply to an existing Gmail message."""

    params = {
        "message_id": message_id,
        "body_chars": len(body),
        "from_header": from_header,
    }
    if _dry_run_requested():
        return _dry_run(
            workspace,
            service="gmail",
            operation="reply",
            parameters=params,
            scopes=_gmail_required_scopes(),
        )
    service = google_workspace.build_service(_workspace_path(workspace), "gmail", "v1")
    original = service.users().messages().get(
        userId="me",
        id=message_id,
        format="metadata",
        metadataHeaders=_GMAIL_METADATA_HEADERS,
    ).execute()
    headers = _headers_dict(original)
    subject = headers.get("subject", "")
    reply_subject = subject if subject.startswith("Re:") else f"Re: {subject}".strip()
    mime = MIMEText(body)
    mime["To"] = headers.get("from", "")
    mime["Subject"] = reply_subject
    if from_header:
        mime["From"] = from_header
    if headers.get("message-id"):
        mime["In-Reply-To"] = headers["message-id"]
        mime["References"] = headers["message-id"]
    raw = base64.urlsafe_b64encode(mime.as_bytes()).decode("utf-8")
    result = service.users().messages().send(
        userId="me",
        body={"raw": raw, "threadId": original.get("threadId", "")},
    ).execute()
    return {
        "status": "sent",
        "id": str(result.get("id", "")),
        "threadId": str(result.get("threadId", "")),
    }


def gmail_labels(workspace: str) -> list[dict[str, object]] | dict[str, object]:
    """List Gmail labels."""

    if _dry_run_requested():
        return _dry_run(
            workspace,
            service="gmail",
            operation="labels",
            parameters={},
            scopes=_gmail_required_scopes(),
        )
    service = google_workspace.build_service(_workspace_path(workspace), "gmail", "v1")
    results = service.users().labels().list(userId="me").execute()
    labels = results.get("labels", []) if isinstance(results, dict) else []
    return [
        {
            "id": str(label.get("id", "")),
            "name": str(label.get("name", "")),
            "type": str(label.get("type", "")),
        }
        for label in labels
        if isinstance(label, dict)
    ]


def gmail_modify(
    workspace: str,
    message_id: str,
    add_labels: list[str] | None = None,
    remove_labels: list[str] | None = None,
) -> dict[str, object]:
    """Add and/or remove Gmail labels from a message."""

    params = {
        "message_id": message_id,
        "add_labels": list(add_labels or []),
        "remove_labels": list(remove_labels or []),
    }
    if _dry_run_requested():
        return _dry_run(
            workspace,
            service="gmail",
            operation="modify",
            parameters=params,
            scopes=_gmail_required_scopes(),
        )
    body_payload: dict[str, object] = {}
    if add_labels:
        body_payload["addLabelIds"] = list(add_labels)
    if remove_labels:
        body_payload["removeLabelIds"] = list(remove_labels)
    service = google_workspace.build_service(_workspace_path(workspace), "gmail", "v1")
    result = service.users().messages().modify(
        userId="me",
        id=message_id,
        body=body_payload,
    ).execute()
    return {
        "id": str(result.get("id", "")),
        "labels": [
            str(label)
            for label in result.get("labelIds", [])
            if isinstance(label, str) and label.strip()
        ],
    }


def calendar_list(
    workspace: str,
    start: str | None = None,
    end: str | None = None,
) -> list[dict[str, object]] | dict[str, object]:
    """List primary-calendar events within the requested window."""

    now = datetime.now(timezone.utc)
    time_min = _datetime_with_timezone(start or now.isoformat()) or now.isoformat()
    time_max = _datetime_with_timezone(end or (now + timedelta(days=7)).isoformat()) or (
        now + timedelta(days=7)
    ).isoformat()
    params = {"start": time_min, "end": time_max}
    if _dry_run_requested():
        return _dry_run(
            workspace,
            service="calendar",
            operation="list",
            parameters=params,
            scopes=_calendar_scopes(),
        )
    service = google_workspace.build_service(_workspace_path(workspace), "calendar", "v3")
    results = service.events().list(
        calendarId="primary",
        timeMin=time_min,
        timeMax=time_max,
        maxResults=25,
        singleEvents=True,
        orderBy="startTime",
    ).execute()
    items = results.get("items", []) if isinstance(results, dict) else []
    return [
        {
            "id": str(item.get("id", "")),
            "summary": str(item.get("summary", "(no title)")),
            "start": str(
                item.get("start", {}).get("dateTime", item.get("start", {}).get("date", "")),
            ),
            "end": str(item.get("end", {}).get("dateTime", item.get("end", {}).get("date", ""))),
            "location": str(item.get("location", "")),
            "description": str(item.get("description", "")),
            "status": str(item.get("status", "")),
            "htmlLink": str(item.get("htmlLink", "")),
        }
        for item in items
        if isinstance(item, dict)
    ]


def calendar_create(
    workspace: str,
    summary: str,
    start: str,
    end: str,
    location: str | None = None,
    attendees: list[str] | None = None,
) -> dict[str, object]:
    """Create a primary-calendar event."""

    params = {
        "summary": summary,
        "start": start,
        "end": end,
        "location": location,
        "attendees": list(attendees or []),
    }
    if _dry_run_requested():
        return _dry_run(
            workspace,
            service="calendar",
            operation="create",
            parameters=params,
            scopes=_calendar_scopes(),
        )
    event: dict[str, object] = {
        "summary": summary,
        "start": {"dateTime": start},
        "end": {"dateTime": end},
    }
    if location:
        event["location"] = location
    if attendees:
        event["attendees"] = [{"email": attendee} for attendee in attendees if attendee.strip()]
    service = google_workspace.build_service(_workspace_path(workspace), "calendar", "v3")
    result = service.events().insert(calendarId="primary", body=event).execute()
    return {
        "status": "created",
        "id": str(result.get("id", "")),
        "summary": str(result.get("summary", "")),
        "htmlLink": str(result.get("htmlLink", "")),
    }


def calendar_delete(workspace: str, event_id: str) -> dict[str, object]:
    """Delete a primary-calendar event."""

    params = {"event_id": event_id}
    if _dry_run_requested():
        return _dry_run(
            workspace,
            service="calendar",
            operation="delete",
            parameters=params,
            scopes=_calendar_scopes(),
        )
    service = google_workspace.build_service(_workspace_path(workspace), "calendar", "v3")
    service.events().delete(calendarId="primary", eventId=event_id).execute()
    return {"status": "deleted", "eventId": event_id}


def drive_search(
    workspace: str,
    query: str,
    max_results: int = 10,
    raw_query: bool = False,
) -> list[dict[str, object]] | dict[str, object]:
    """Search Drive files."""

    drive_query = query if raw_query else f"fullText contains '{query}'"
    params = {
        "query": query,
        "drive_query": drive_query,
        "max_results": max_results,
        "raw_query": raw_query,
    }
    if _dry_run_requested():
        return _dry_run(
            workspace,
            service="drive",
            operation="search",
            parameters=params,
            scopes=_drive_scopes(),
        )
    service = google_workspace.build_service(_workspace_path(workspace), "drive", "v3")
    results = service.files().list(
        q=drive_query,
        pageSize=max(max_results, 0),
        fields="files(id, name, mimeType, modifiedTime, webViewLink)",
    ).execute()
    files = results.get("files", []) if isinstance(results, dict) else []
    return [
        {
            "id": str(file_row.get("id", "")),
            "name": str(file_row.get("name", "")),
            "mimeType": str(file_row.get("mimeType", "")),
            "modifiedTime": str(file_row.get("modifiedTime", "")),
            "webViewLink": str(file_row.get("webViewLink", "")),
        }
        for file_row in files
        if isinstance(file_row, dict)
    ]


def drive_get(workspace: str, file_id: str) -> dict[str, object]:
    """Get one Drive file metadata row."""

    params = {"file_id": file_id}
    if _dry_run_requested():
        return _dry_run(
            workspace,
            service="drive",
            operation="get",
            parameters=params,
            scopes=_drive_scopes(),
        )
    service = google_workspace.build_service(_workspace_path(workspace), "drive", "v3")
    result = service.files().get(
        fileId=file_id,
        fields="id, name, mimeType, modifiedTime, size, webViewLink, parents, owners(emailAddress)",
    ).execute()
    owners = result.get("owners", []) if isinstance(result, dict) else []
    return {
        "id": str(result.get("id", "")),
        "name": str(result.get("name", "")),
        "mimeType": str(result.get("mimeType", "")),
        "modifiedTime": str(result.get("modifiedTime", "")),
        "size": str(result.get("size", "")),
        "webViewLink": str(result.get("webViewLink", "")),
        "parents": [
            str(parent)
            for parent in result.get("parents", [])
            if isinstance(parent, str) and parent.strip()
        ],
        "owners": [
            str(owner.get("emailAddress", ""))
            for owner in owners
            if isinstance(owner, dict) and str(owner.get("emailAddress", "")).strip()
        ],
    }


def drive_upload(
    workspace: str | Path,
    path: str | Path,
    *,
    name: str | None = None,
    parent: str | None = None,
    mime_type: str | None = None,
) -> dict[str, object]:
    """Upload a local file to Google Drive."""

    local_path = Path(path).expanduser()
    params = {
        "path": str(local_path),
        "name": name,
        "parent": parent,
        "mime_type": mime_type,
    }
    if _dry_run_requested():
        return _dry_run(
            workspace,
            service="drive",
            operation="upload",
            parameters=params,
            scopes=_drive_scopes(),
        )
    if not local_path.exists():
        raise ValueError(f"file not found: {local_path}")
    from googleapiclient.http import MediaFileUpload

    detected_mime = mime_type or mimetypes.guess_type(str(local_path))[0] or "application/octet-stream"
    metadata: dict[str, object] = {"name": name or local_path.name}
    if parent:
        metadata["parents"] = [parent]
    service = google_workspace.build_service(_workspace_path(workspace), "drive", "v3")
    media = MediaFileUpload(str(local_path), mimetype=detected_mime, resumable=True)
    result = service.files().create(
        body=metadata,
        media_body=media,
        fields="id, name, mimeType, webViewLink",
    ).execute()
    return {
        "status": "uploaded",
        "id": str(result.get("id", "")),
        "name": str(result.get("name", "")),
        "mimeType": str(result.get("mimeType", "")),
        "webViewLink": str(result.get("webViewLink", "")),
    }


def drive_download(
    workspace: str | Path,
    file_id: str,
    *,
    output: str | Path | None = None,
    export_mime: str | None = None,
) -> dict[str, object]:
    """Download or export a Drive file to a local path."""

    params = {
        "file_id": file_id,
        "output": str(output) if output is not None else None,
        "export_mime": export_mime,
    }
    if _dry_run_requested():
        return _dry_run(
            workspace,
            service="drive",
            operation="download",
            parameters=params,
            scopes=_drive_scopes(),
        )
    from googleapiclient.http import MediaIoBaseDownload

    service = google_workspace.build_service(_workspace_path(workspace), "drive", "v3")
    metadata = service.files().get(fileId=file_id, fields="id, name, mimeType").execute()
    mime_type_value = str(metadata.get("mimeType", ""))
    name = str(metadata.get("name", file_id))
    native_export_map = {
        "application/vnd.google-apps.document": ("application/pdf", ".pdf"),
        "application/vnd.google-apps.spreadsheet": ("text/csv", ".csv"),
        "application/vnd.google-apps.presentation": ("application/pdf", ".pdf"),
        "application/vnd.google-apps.drawing": ("image/png", ".png"),
    }
    out_path = (
        Path(output).expanduser()
        if output is not None
        else (Path.cwd() / name)
    )
    if mime_type_value in native_export_map:
        download_mime, default_suffix = native_export_map[mime_type_value]
        if export_mime:
            download_mime = export_mime
        if output is None and not out_path.suffix:
            out_path = out_path.with_suffix(default_suffix)
        request = service.files().export_media(fileId=file_id, mimeType=download_mime)
    else:
        request = service.files().get_media(fileId=file_id)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("wb") as handle:
        downloader = MediaIoBaseDownload(handle, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
    return {
        "status": "downloaded",
        "id": file_id,
        "name": name,
        "path": str(out_path),
        "mimeType": mime_type_value,
    }


def drive_create_folder(
    workspace: str | Path,
    name: str,
    *,
    parent: str | None = None,
) -> dict[str, object]:
    """Create a Google Drive folder."""

    params = {"name": name, "parent": parent}
    if _dry_run_requested():
        return _dry_run(
            workspace,
            service="drive",
            operation="create-folder",
            parameters=params,
            scopes=_drive_scopes(),
        )
    body: dict[str, object] = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    if parent:
        body["parents"] = [parent]
    service = google_workspace.build_service(_workspace_path(workspace), "drive", "v3")
    result = service.files().create(body=body, fields="id, name, webViewLink").execute()
    return {
        "status": "created",
        "id": str(result.get("id", "")),
        "name": str(result.get("name", "")),
        "webViewLink": str(result.get("webViewLink", "")),
    }


def drive_share(
    workspace: str | Path,
    file_id: str,
    *,
    role: str = "reader",
    permission_type: str = "user",
    email: str | None = None,
    domain: str | None = None,
    notify: bool = False,
) -> dict[str, object]:
    """Create a Drive permission for a file."""

    permission: dict[str, object] = {
        "type": permission_type,
        "role": role,
    }
    if permission_type in {"user", "group"}:
        if not email:
            raise ValueError("--email is required for type=user or type=group")
        permission["emailAddress"] = email
    elif permission_type == "domain":
        if not domain:
            raise ValueError("--domain is required for type=domain")
        permission["domain"] = domain
    params = {
        "file_id": file_id,
        "role": role,
        "type": permission_type,
        "email": email,
        "domain": domain,
        "notify": notify,
    }
    if _dry_run_requested():
        return _dry_run(
            workspace,
            service="drive",
            operation="share",
            parameters=params,
            scopes=_drive_scopes(),
        )
    service = google_workspace.build_service(_workspace_path(workspace), "drive", "v3")
    result = service.permissions().create(
        fileId=file_id,
        body=permission,
        sendNotificationEmail=notify,
        fields="id",
    ).execute()
    return {
        "status": "shared",
        "permissionId": str(result.get("id", "")),
        "fileId": file_id,
        "role": role,
        "type": permission_type,
    }


def drive_delete(workspace: str | Path, file_id: str, *, permanent: bool = False) -> dict[str, object]:
    """Trash or permanently delete a Google Drive file."""

    params = {"file_id": file_id, "permanent": permanent}
    if _dry_run_requested():
        return _dry_run(
            workspace,
            service="drive",
            operation="delete",
            parameters=params,
            scopes=_drive_scopes(),
        )
    service = google_workspace.build_service(_workspace_path(workspace), "drive", "v3")
    if permanent:
        service.files().delete(fileId=file_id).execute()
        return {"status": "deleted", "fileId": file_id, "permanent": True}
    service.files().update(fileId=file_id, body={"trashed": True}).execute()
    return {"status": "trashed", "fileId": file_id, "permanent": False}


def contacts_list(workspace: str, max_results: int = 20) -> list[dict[str, object]] | dict[str, object]:
    """List Google contacts via the People API."""

    params = {"max_results": max_results}
    if _dry_run_requested():
        return _dry_run(
            workspace,
            service="contacts",
            operation="list",
            parameters=params,
            scopes=_contacts_scopes(),
        )
    service = google_workspace.build_service(_workspace_path(workspace), "people", "v1")
    results = service.people().connections().list(
        resourceName="people/me",
        pageSize=max(max_results, 0),
        personFields="names,emailAddresses,phoneNumbers",
    ).execute()
    connections = results.get("connections", []) if isinstance(results, dict) else []
    output: list[dict[str, object]] = []
    for person in connections:
        if not isinstance(person, dict):
            continue
        names = person.get("names", [])
        emails = person.get("emailAddresses", [])
        phones = person.get("phoneNumbers", [])
        display_name = ""
        if isinstance(names, list) and names and isinstance(names[0], dict):
            display_name = str(names[0].get("displayName", ""))
        output.append(
            {
                "name": display_name,
                "emails": [
                    str(email.get("value", ""))
                    for email in emails
                    if isinstance(email, dict) and str(email.get("value", "")).strip()
                ],
                "phones": [
                    str(phone.get("value", ""))
                    for phone in phones
                    if isinstance(phone, dict) and str(phone.get("value", "")).strip()
                ],
            },
        )
    return output


def sheets_get(
    workspace: str | Path,
    spreadsheet_id: str,
    range_name: str,
) -> list[list[object]] | dict[str, object]:
    """Fetch values for a Google Sheets range."""

    params = {"spreadsheet_id": spreadsheet_id, "range": range_name}
    if _dry_run_requested():
        return _dry_run(
            workspace,
            service="sheets",
            operation="get",
            parameters=params,
            scopes=_sheets_scopes(),
        )
    service = google_workspace.build_service(_workspace_path(workspace), "sheets", "v4")
    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=range_name,
    ).execute()
    values = result.get("values", []) if isinstance(result, dict) else []
    return [row for row in values if isinstance(row, list)]


def sheets_update(
    workspace: str | Path,
    spreadsheet_id: str,
    range_name: str,
    values: list[list[object]],
) -> dict[str, object]:
    """Update a Google Sheets range with user-entered values."""

    params = {
        "spreadsheet_id": spreadsheet_id,
        "range": range_name,
        "values": values,
    }
    if _dry_run_requested():
        return _dry_run(
            workspace,
            service="sheets",
            operation="update",
            parameters=params,
            scopes=_sheets_scopes(),
        )
    service = google_workspace.build_service(_workspace_path(workspace), "sheets", "v4")
    result = service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=range_name,
        valueInputOption="USER_ENTERED",
        body={"values": values},
    ).execute()
    return {
        "updatedCells": int(result.get("updatedCells", 0)),
        "updatedRange": str(result.get("updatedRange", "")),
    }


def sheets_append(
    workspace: str | Path,
    spreadsheet_id: str,
    range_name: str,
    values: list[list[object]],
) -> dict[str, object]:
    """Append rows to a Google Sheets range."""

    params = {
        "spreadsheet_id": spreadsheet_id,
        "range": range_name,
        "values": values,
    }
    if _dry_run_requested():
        return _dry_run(
            workspace,
            service="sheets",
            operation="append",
            parameters=params,
            scopes=_sheets_scopes(),
        )
    service = google_workspace.build_service(_workspace_path(workspace), "sheets", "v4")
    result = service.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range=range_name,
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": values},
    ).execute()
    updates = result.get("updates", {}) if isinstance(result, dict) else {}
    return {"updatedCells": int(updates.get("updatedCells", 0))}


def sheets_create(
    workspace: str | Path,
    title: str,
    *,
    sheet_name: str | None = None,
) -> dict[str, object]:
    """Create a new Google Sheets spreadsheet."""

    params = {"title": title, "sheet_name": sheet_name}
    if _dry_run_requested():
        return _dry_run(
            workspace,
            service="sheets",
            operation="create",
            parameters=params,
            scopes=_sheets_scopes(),
        )
    body: dict[str, object] = {"properties": {"title": title}}
    if sheet_name:
        body["sheets"] = [{"properties": {"title": sheet_name}}]
    service = google_workspace.build_service(_workspace_path(workspace), "sheets", "v4")
    result = service.spreadsheets().create(
        body=body,
        fields="spreadsheetId,properties,spreadsheetUrl",
    ).execute()
    properties = result.get("properties", {}) if isinstance(result, dict) else {}
    return {
        "status": "created",
        "spreadsheetId": str(result.get("spreadsheetId", "")),
        "title": str(properties.get("title", "")) if isinstance(properties, dict) else "",
        "spreadsheetUrl": str(result.get("spreadsheetUrl", "")),
    }


def docs_get(workspace: str | Path, document_id: str) -> dict[str, object]:
    """Fetch a Google Doc and return extracted plain text."""

    params = {"document_id": document_id}
    if _dry_run_requested():
        return _dry_run(
            workspace,
            service="docs",
            operation="get",
            parameters=params,
            scopes=_docs_scopes(),
        )
    service = google_workspace.build_service(_workspace_path(workspace), "docs", "v1")
    result = service.documents().get(documentId=document_id).execute()
    return {
        "title": str(result.get("title", "")),
        "documentId": str(result.get("documentId", "")),
        "body": _extract_doc_text(result),
    }


def docs_create(
    workspace: str | Path,
    title: str,
    *,
    body: str | None = None,
) -> dict[str, object]:
    """Create a new Google Doc, optionally with initial body text."""

    params = {"title": title, "body": body}
    if _dry_run_requested():
        return _dry_run(
            workspace,
            service="docs",
            operation="create",
            parameters=params,
            scopes=_docs_scopes(),
        )
    service = google_workspace.build_service(_workspace_path(workspace), "docs", "v1")
    result = service.documents().create(body={"title": title}).execute()
    document_id = str(result.get("documentId", ""))
    if body and document_id:
        _docs_insert_text(workspace, document_id, body, 1)
    return {
        "status": "created",
        "documentId": document_id,
        "title": str(result.get("title", "")),
        "url": f"https://docs.google.com/document/d/{document_id}/edit" if document_id else "",
    }


def docs_append(workspace: str | Path, document_id: str, text: str) -> dict[str, object]:
    """Append text to the end of a Google Doc."""

    params = {"document_id": document_id, "text": text}
    if _dry_run_requested():
        return _dry_run(
            workspace,
            service="docs",
            operation="append",
            parameters=params,
            scopes=_docs_scopes(),
        )
    service = google_workspace.build_service(_workspace_path(workspace), "docs", "v1")
    document = service.documents().get(documentId=document_id).execute()
    body = document.get("body", {})
    content = body.get("content", []) if isinstance(body, dict) else []
    end_index = 1
    for element in content:
        if not isinstance(element, dict):
            continue
        raw_end_index = element.get("endIndex")
        if isinstance(raw_end_index, int) and raw_end_index > end_index:
            end_index = raw_end_index
    insert_index = max(end_index - 1, 1)
    appended_text = text if text.endswith("\n") else f"{text}\n"
    _docs_insert_text(workspace, document_id, appended_text, insert_index)
    return {
        "status": "appended",
        "documentId": document_id,
        "inserted_at": insert_index,
        "characters": len(appended_text),
    }


__all__ = [
    "calendar_create",
    "calendar_delete",
    "calendar_list",
    "contacts_list",
    "docs_append",
    "docs_create",
    "docs_get",
    "drive_create_folder",
    "drive_delete",
    "drive_download",
    "drive_get",
    "drive_search",
    "drive_share",
    "drive_upload",
    "gmail_get",
    "gmail_labels",
    "gmail_modify",
    "gmail_reply",
    "gmail_search",
    "gmail_send",
    "sheets_append",
    "sheets_create",
    "sheets_get",
    "sheets_update",
]
