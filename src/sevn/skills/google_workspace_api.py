"""Google Workspace API operations for bundled skill scripts.

Module: sevn.skills.google_workspace_api
Depends: base64, datetime, email.mime.text, sevn.skills.google_workspace

Exports:
    calendar_create — create a calendar event.
    calendar_delete — delete a calendar event.
    calendar_list — list upcoming calendar events.
    contacts_list — list Google contacts via People API.
    drive_get — get Drive file metadata.
    drive_search — search Drive files.
    gmail_get — fetch one Gmail message.
    gmail_labels — list Gmail labels.
    gmail_modify — add/remove Gmail labels.
    gmail_reply — reply to a Gmail thread.
    gmail_search — search Gmail messages.
    gmail_send — send a Gmail message.
"""

from __future__ import annotations

import base64
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


__all__ = [
    "calendar_create",
    "calendar_delete",
    "calendar_list",
    "contacts_list",
    "drive_get",
    "drive_search",
    "gmail_get",
    "gmail_labels",
    "gmail_modify",
    "gmail_reply",
    "gmail_search",
    "gmail_send",
]
