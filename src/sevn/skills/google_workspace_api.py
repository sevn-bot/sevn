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
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from email.mime.text import MIMEText
from pathlib import Path
from typing import Final

from sevn.skills import google_workspace

_GMAIL_METADATA_HEADERS: Final[list[str]] = ["From", "To", "Subject", "Date", "Message-ID"]


def _headers_dict(message: dict[str, object]) -> dict[str, str]:
    """Return lower-cased Gmail headers from a message resource.

    Args:
        message (dict[str, object]): Parameter.

    Returns:
        dict[str, str]: Result.

    Examples:
        >>> _headers_dict  # doctest: +SKIP
    """

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
    """Decode a Gmail urlsafe base64 payload fragment.

    Args:
        data (str): Parameter.

    Returns:
        str: Result.

    Examples:
        >>> _decode_b64url  # doctest: +SKIP
    """

    padding = "=" * ((4 - len(data) % 4) % 4)
    return base64.urlsafe_b64decode(f"{data}{padding}").decode("utf-8", errors="replace")


def _extract_message_body(message: dict[str, object]) -> str:
    """Extract the most useful body text from a Gmail message payload.

    Args:
        message (dict[str, object]): Parameter.

    Returns:
        str: Result.

    Examples:
        >>> _extract_message_body  # doctest: +SKIP
    """

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
    """Normalise a Gmail message resource to the Hermes summary shape.

    Args:
        message (dict[str, object]): Parameter.

    Returns:
        dict[str, object]: Result.

    Examples:
        >>> _gmail_summary_row  # doctest: +SKIP
    """

    headers = _headers_dict(message)
    labels_raw = message.get("labelIds")
    labels_src = labels_raw if isinstance(labels_raw, list) else []
    return {
        "id": str(message.get("id", "")),
        "threadId": str(message.get("threadId", "")),
        "from": headers.get("from", ""),
        "to": headers.get("to", ""),
        "subject": headers.get("subject", ""),
        "date": headers.get("date", ""),
        "snippet": str(message.get("snippet", "")),
        "labels": [str(label) for label in labels_src if isinstance(label, str) and label.strip()],
    }


def _gmail_required_scopes() -> list[str]:
    """Return Gmail scopes used by read/write operations.

    Returns:
        list[str]: Result.

    Examples:
        >>> _gmail_required_scopes  # doctest: +SKIP
    """

    return list(google_workspace.SERVICE_SCOPE_SETS["email"])


def _calendar_scopes() -> list[str]:
    """Return Calendar scopes used by calendar operations.

    Returns:
        list[str]: Result.

    Examples:
        >>> _calendar_scopes  # doctest: +SKIP
    """

    return list(google_workspace.SERVICE_SCOPE_SETS["calendar"])


def _drive_scopes() -> list[str]:
    """Return Drive scopes used by drive operations.

    Returns:
        list[str]: Result.

    Examples:
        >>> _drive_scopes  # doctest: +SKIP
    """

    return list(google_workspace.SERVICE_SCOPE_SETS["drive"])


def _contacts_scopes() -> list[str]:
    """Return People API scopes used by contact operations.

    Returns:
        list[str]: Result.

    Examples:
        >>> _contacts_scopes  # doctest: +SKIP
    """

    return list(google_workspace.SERVICE_SCOPE_SETS["contacts"])


def _sheets_scopes() -> list[str]:
    """Return Sheets scopes used by spreadsheet operations.

    Returns:
        list[str]: Result.

    Examples:
        >>> _sheets_scopes  # doctest: +SKIP
    """

    return list(google_workspace.SERVICE_SCOPE_SETS["sheets"])


def _docs_scopes() -> list[str]:
    """Return Docs scopes used by document operations.

    Returns:
        list[str]: Result.

    Examples:
        >>> _docs_scopes  # doctest: +SKIP
    """

    return list(google_workspace.SERVICE_SCOPE_SETS["docs"])


def _workspace_path(workspace: str | Path) -> Path:
    """Normalize a workspace argument to an absolute path.

    Args:
        workspace (str | Path): Parameter.

    Returns:
        Path: Result.

    Examples:
        >>> _workspace_path  # doctest: +SKIP
    """

    return Path(workspace).expanduser().resolve()


def _dry_run_requested() -> bool:
    """Return True when Google Workspace dry-run mode is enabled.

    Returns:
        bool: Result.

    Examples:
        >>> _dry_run_requested  # doctest: +SKIP
    """

    return google_workspace.dry_run_requested(env=os.environ)


def _dry_run(
    workspace: str | Path,
    *,
    service: str,
    operation: str,
    parameters: Mapping[str, object],
    scopes: Iterable[str],
) -> dict[str, object]:
    """Return a dry-run plan envelope when dry-run mode is enabled.

    Args:
        workspace (str | Path): Parameter.
        service (str): Parameter.
        operation (str): Parameter.
        parameters (dict[str, object]): Parameter.
        scopes (Iterable[str]): Parameter.

    Returns:
        dict[str, object]: Result.

    Examples:
        >>> _dry_run  # doctest: +SKIP
    """

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


def _gws_if_preferred(
    workspace: str | Path,
    parts: list[str],
    *,
    params: Mapping[str, object] | None = None,
    body: object | None = None,
) -> dict[str, object] | None:
    """Return ``run_gws`` payload when §3.3 prefers gws; otherwise ``None``.

    Args:
        workspace (str | Path): Workspace root.
        parts (list[str]): gws argv segments after the binary.
        params (Mapping[str, object] | None): Optional flag map for ``run_gws``.
        body (object | None): Optional stdin JSON body for ``run_gws``.

    Returns:
        dict[str, object] | None: Parsed gws output, or ``None`` to use Python.

    Examples:
        >>> _gws_if_preferred  # doctest: +SKIP
    """

    ws = _workspace_path(workspace)
    if not google_workspace.use_gws_backend(ws):
        return None
    return google_workspace.run_gws(ws, parts, params=params, body=body)


def _gws_as_list(payload: dict[str, object], *keys: str) -> list[dict[str, object]]:
    """Extract a list of dict rows from a gws JSON payload.

    Args:
        payload (dict[str, object]): Parsed gws output.
        keys (str): Preferred top-level keys (e.g. ``messages``, ``files``).

    Returns:
        list[dict[str, object]]: Row list (possibly empty).

    Examples:
        >>> _gws_as_list  # doctest: +SKIP
    """

    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
    data = payload.get("data")
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    return []


def _datetime_with_timezone(value: str | None) -> str | None:
    """Return ISO datetime with timezone info when missing.

    Args:
        value (str | None): Parameter.

    Returns:
        str | None: Result.

    Examples:
        >>> _datetime_with_timezone  # doctest: +SKIP
    """

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
    """Extract plain text content from a Google Docs document resource.

    Args:
        document (dict[str, object]): Parameter.

    Returns:
        str: Result.

    Examples:
        >>> _extract_doc_text  # doctest: +SKIP
    """

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
    """Insert text into a Google Doc using a single batchUpdate request.

    Args:
        workspace (str | Path): Parameter.
        document_id (str): Parameter.
        text (str): Parameter.
        index (int): Parameter.

    Examples:
        >>> _docs_insert_text  # doctest: +SKIP
    """

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


def gmail_search(
    workspace: str, query: str, max_results: int = 10
) -> list[dict[str, object]] | dict[str, object]:
    """Search Gmail messages and return Hermes-style summary rows.

    Args:
        workspace (str): Parameter.
        query (str): Parameter.
        max_results (int): Parameter.

    Returns:
        list[dict[str, object]] | dict[str, object]: Result.

    Examples:
        >>> gmail_search  # doctest: +SKIP
    """

    params = {"query": query, "max_results": max_results}
    if _dry_run_requested():
        return _dry_run(
            workspace,
            service="gmail",
            operation="search",
            parameters=params,
            scopes=_gmail_required_scopes(),
        )
    gws_payload = _gws_if_preferred(
        workspace,
        ["gmail", "users", "messages", "list"],
        params={"userId": "me", "q": query, "maxResults": max(max_results, 0)},
    )
    if gws_payload is not None:
        # gws may return summary rows or id stubs; both satisfy the list contract.
        return _gws_as_list(gws_payload, "messages")
    service = google_workspace.build_service(_workspace_path(workspace), "gmail", "v1")
    results = (
        service.users()
        .messages()
        .list(
            userId="me",
            q=query,
            maxResults=max(max_results, 0),
        )
        .execute()
    )
    messages = results.get("messages", []) if isinstance(results, dict) else []
    output: list[dict[str, object]] = []
    for message_meta in messages:
        if not isinstance(message_meta, dict) or "id" not in message_meta:
            continue
        message = (
            service.users()
            .messages()
            .get(
                userId="me",
                id=message_meta["id"],
                format="metadata",
                metadataHeaders=["From", "To", "Subject", "Date"],
            )
            .execute()
        )
        output.append(_gmail_summary_row(message))
    return output


def gmail_get(workspace: str, message_id: str) -> dict[str, object]:
    """Fetch one Gmail message with body text.

    Args:
        workspace (str): Parameter.
        message_id (str): Parameter.

    Returns:
        dict[str, object]: Result.

    Examples:
        >>> gmail_get  # doctest: +SKIP
    """

    params = {"message_id": message_id}
    if _dry_run_requested():
        return _dry_run(
            workspace,
            service="gmail",
            operation="get",
            parameters=params,
            scopes=_gmail_required_scopes(),
        )
    gws_payload = _gws_if_preferred(
        workspace,
        ["gmail", "users", "messages", "get"],
        params={"userId": "me", "id": message_id, "format": "full"},
    )
    if gws_payload is not None:
        return gws_payload
    service = google_workspace.build_service(_workspace_path(workspace), "gmail", "v1")
    message = (
        service.users()
        .messages()
        .get(
            userId="me",
            id=message_id,
            format="full",
        )
        .execute()
    )
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
    """Send a Gmail message.

    Args:
        workspace (str): Parameter.
        to (str): Parameter.
        subject (str): Parameter.
        body (str): Parameter.
        html (bool): Parameter.
        from_header (str | None): Parameter.
        cc (str | None): Parameter.

    Returns:
        dict[str, object]: Result.

    Examples:
        >>> gmail_send  # doctest: +SKIP
    """

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
    gws_payload = _gws_if_preferred(
        workspace,
        ["gmail", "users", "messages", "send"],
        params={"userId": "me"},
        body={"raw": raw},
    )
    if gws_payload is not None:
        return {
            "status": "sent",
            "id": str(gws_payload.get("id", "")),
            "threadId": str(gws_payload.get("threadId", "")),
        }
    service = google_workspace.build_service(_workspace_path(workspace), "gmail", "v1")
    result = (
        service.users()
        .messages()
        .send(
            userId="me",
            body={"raw": raw},
        )
        .execute()
    )
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
    """Reply to an existing Gmail message.

    Args:
        workspace (str): Parameter.
        message_id (str): Parameter.
        body (str): Parameter.
        from_header (str | None): Parameter.

    Returns:
        dict[str, object]: Result.

    Examples:
        >>> gmail_reply  # doctest: +SKIP
    """

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
    original = (
        service.users()
        .messages()
        .get(
            userId="me",
            id=message_id,
            format="metadata",
            metadataHeaders=_GMAIL_METADATA_HEADERS,
        )
        .execute()
    )
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
    send_body: dict[str, object] = {"raw": raw, "threadId": original.get("threadId", "")}
    gws_payload = _gws_if_preferred(
        workspace,
        ["gmail", "users", "messages", "send"],
        params={"userId": "me"},
        body=send_body,
    )
    if gws_payload is not None:
        return {
            "status": "sent",
            "id": str(gws_payload.get("id", "")),
            "threadId": str(gws_payload.get("threadId", "")),
        }
    result = (
        service.users()
        .messages()
        .send(
            userId="me",
            body=send_body,
        )
        .execute()
    )
    return {
        "status": "sent",
        "id": str(result.get("id", "")),
        "threadId": str(result.get("threadId", "")),
    }


def gmail_labels(workspace: str) -> list[dict[str, object]] | dict[str, object]:
    """List Gmail labels.

    Args:
        workspace (str): Parameter.

    Returns:
        list[dict[str, object]] | dict[str, object]: Result.

    Examples:
        >>> gmail_labels  # doctest: +SKIP
    """

    if _dry_run_requested():
        return _dry_run(
            workspace,
            service="gmail",
            operation="labels",
            parameters={},
            scopes=_gmail_required_scopes(),
        )
    gws_payload = _gws_if_preferred(
        workspace,
        ["gmail", "users", "labels", "list"],
        params={"userId": "me"},
    )
    if gws_payload is not None:
        return _gws_as_list(gws_payload, "labels")
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
    """Add and/or remove Gmail labels from a message.

    Args:
        workspace (str): Parameter.
        message_id (str): Parameter.
        add_labels (list[str] | None): Parameter.
        remove_labels (list[str] | None): Parameter.

    Returns:
        dict[str, object]: Result.

    Examples:
        >>> gmail_modify  # doctest: +SKIP
    """

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
    gws_payload = _gws_if_preferred(
        workspace,
        ["gmail", "users", "messages", "modify"],
        params={"userId": "me", "id": message_id},
        body=body_payload,
    )
    if gws_payload is not None:
        raw_labels = gws_payload.get("labelIds", [])
        label_ids = raw_labels if isinstance(raw_labels, list) else []
        return {
            "id": str(gws_payload.get("id", "")),
            "labels": [
                str(label) for label in label_ids if isinstance(label, str) and label.strip()
            ],
        }
    service = google_workspace.build_service(_workspace_path(workspace), "gmail", "v1")
    result = (
        service.users()
        .messages()
        .modify(
            userId="me",
            id=message_id,
            body=body_payload,
        )
        .execute()
    )
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
    """List primary-calendar events within the requested window.

    Args:
        workspace (str): Parameter.
        start (str | None): Parameter.
        end (str | None): Parameter.

    Returns:
        list[dict[str, object]] | dict[str, object]: Result.

    Examples:
        >>> calendar_list  # doctest: +SKIP
    """

    now = datetime.now(UTC)
    time_min = _datetime_with_timezone(start or now.isoformat()) or now.isoformat()
    time_max = (
        _datetime_with_timezone(end or (now + timedelta(days=7)).isoformat())
        or (now + timedelta(days=7)).isoformat()
    )
    params = {"start": time_min, "end": time_max}
    if _dry_run_requested():
        return _dry_run(
            workspace,
            service="calendar",
            operation="list",
            parameters=params,
            scopes=_calendar_scopes(),
        )
    gws_payload = _gws_if_preferred(
        workspace,
        ["calendar", "events", "list"],
        params={
            "calendarId": "primary",
            "timeMin": time_min,
            "timeMax": time_max,
            "maxResults": 25,
            "singleEvents": True,
            "orderBy": "startTime",
        },
    )
    if gws_payload is not None:
        return _gws_as_list(gws_payload, "items", "events")
    service = google_workspace.build_service(_workspace_path(workspace), "calendar", "v3")
    results = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=time_min,
            timeMax=time_max,
            maxResults=25,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )
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
    """Create a primary-calendar event.

    Args:
        workspace (str): Parameter.
        summary (str): Parameter.
        start (str): Parameter.
        end (str): Parameter.
        location (str | None): Parameter.
        attendees (list[str] | None): Parameter.

    Returns:
        dict[str, object]: Result.

    Examples:
        >>> calendar_create  # doctest: +SKIP
    """

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
    gws_payload = _gws_if_preferred(
        workspace,
        ["calendar", "events", "insert"],
        params={"calendarId": "primary"},
        body=event,
    )
    if gws_payload is not None:
        return {
            "status": "created",
            "id": str(gws_payload.get("id", "")),
            "summary": str(gws_payload.get("summary", "")),
            "htmlLink": str(gws_payload.get("htmlLink", "")),
        }
    service = google_workspace.build_service(_workspace_path(workspace), "calendar", "v3")
    result = service.events().insert(calendarId="primary", body=event).execute()
    return {
        "status": "created",
        "id": str(result.get("id", "")),
        "summary": str(result.get("summary", "")),
        "htmlLink": str(result.get("htmlLink", "")),
    }


def calendar_delete(workspace: str, event_id: str) -> dict[str, object]:
    """Delete a primary-calendar event.

    Args:
        workspace (str): Parameter.
        event_id (str): Parameter.

    Returns:
        dict[str, object]: Result.

    Examples:
        >>> calendar_delete  # doctest: +SKIP
    """

    params = {"event_id": event_id}
    if _dry_run_requested():
        return _dry_run(
            workspace,
            service="calendar",
            operation="delete",
            parameters=params,
            scopes=_calendar_scopes(),
        )
    gws_payload = _gws_if_preferred(
        workspace,
        ["calendar", "events", "delete"],
        params={"calendarId": "primary", "eventId": event_id},
    )
    if gws_payload is not None:
        return gws_payload
    service = google_workspace.build_service(_workspace_path(workspace), "calendar", "v3")
    service.events().delete(calendarId="primary", eventId=event_id).execute()
    return {"status": "deleted", "eventId": event_id}


def drive_search(
    workspace: str,
    query: str,
    max_results: int = 10,
    raw_query: bool = False,
) -> list[dict[str, object]] | dict[str, object]:
    """Search Drive files.

    Args:
        workspace (str): Parameter.
        query (str): Parameter.
        max_results (int): Parameter.
        raw_query (bool): Parameter.

    Returns:
        list[dict[str, object]] | dict[str, object]: Result.

    Examples:
        >>> drive_search  # doctest: +SKIP
    """

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
    gws_payload = _gws_if_preferred(
        workspace,
        ["drive", "files", "list"],
        params={
            "q": drive_query,
            "pageSize": max(max_results, 0),
            "fields": "files(id, name, mimeType, modifiedTime, webViewLink)",
        },
    )
    if gws_payload is not None:
        return _gws_as_list(gws_payload, "files")
    service = google_workspace.build_service(_workspace_path(workspace), "drive", "v3")
    results = (
        service.files()
        .list(
            q=drive_query,
            pageSize=max(max_results, 0),
            fields="files(id, name, mimeType, modifiedTime, webViewLink)",
        )
        .execute()
    )
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
    """Get one Drive file metadata row.

    Args:
        workspace (str): Parameter.
        file_id (str): Parameter.

    Returns:
        dict[str, object]: Result.

    Examples:
        >>> drive_get  # doctest: +SKIP
    """

    params = {"file_id": file_id}
    if _dry_run_requested():
        return _dry_run(
            workspace,
            service="drive",
            operation="get",
            parameters=params,
            scopes=_drive_scopes(),
        )
    drive_fields = (
        "id, name, mimeType, modifiedTime, size, webViewLink, parents, owners(emailAddress)"
    )
    gws_payload = _gws_if_preferred(
        workspace,
        ["drive", "files", "get"],
        params={"fileId": file_id, "fields": drive_fields},
    )
    if gws_payload is not None:
        result = gws_payload
    else:
        service = google_workspace.build_service(_workspace_path(workspace), "drive", "v3")
        result = (
            service.files()
            .get(
                fileId=file_id,
                fields=drive_fields,
            )
            .execute()
        )
    if not isinstance(result, dict):
        result = {}
    owners = result.get("owners", [])
    owners_list = owners if isinstance(owners, list) else []
    parents = result.get("parents", [])
    parents_list = parents if isinstance(parents, list) else []
    return {
        "id": str(result.get("id", "")),
        "name": str(result.get("name", "")),
        "mimeType": str(result.get("mimeType", "")),
        "modifiedTime": str(result.get("modifiedTime", "")),
        "size": str(result.get("size", "")),
        "webViewLink": str(result.get("webViewLink", "")),
        "parents": [
            str(parent) for parent in parents_list if isinstance(parent, str) and parent.strip()
        ],
        "owners": [
            str(owner.get("emailAddress", ""))
            for owner in owners_list
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
    """Upload a local file to Google Drive.

    Args:
        workspace (str | Path): Parameter.
        path (str | Path): Parameter.
        name (str | None): Parameter.
        parent (str | None): Parameter.
        mime_type (str | None): Parameter.

    Returns:
        dict[str, object]: Result.

    Examples:
        >>> drive_upload  # doctest: +SKIP
    """

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

    detected_mime = (
        mime_type or mimetypes.guess_type(str(local_path))[0] or "application/octet-stream"
    )
    metadata: dict[str, object] = {"name": name or local_path.name}
    if parent:
        metadata["parents"] = [parent]
    # Media upload is not expressible as a JSON gws body; keep Python client path.
    service = google_workspace.build_service(_workspace_path(workspace), "drive", "v3")
    media = MediaFileUpload(str(local_path), mimetype=detected_mime, resumable=True)
    result = (
        service.files()
        .create(
            body=metadata,
            media_body=media,
            fields="id, name, mimeType, webViewLink",
        )
        .execute()
    )
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
    """Download or export a Drive file to a local path.

    Args:
        workspace (str | Path): Parameter.
        file_id (str): Parameter.
        output (str | Path | None): Parameter.
        export_mime (str | None): Parameter.

    Returns:
        dict[str, object]: Result.

    Examples:
        >>> drive_download  # doctest: +SKIP
    """

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

    # Download/export requires media streaming; keep Python client path.
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
    out_path = Path(output).expanduser() if output is not None else (Path.cwd() / name)
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
    """Create a Google Drive folder.

    Args:
        workspace (str | Path): Parameter.
        name (str): Parameter.
        parent (str | None): Parameter.

    Returns:
        dict[str, object]: Result.

    Examples:
        >>> drive_create_folder  # doctest: +SKIP
    """

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
    gws_payload = _gws_if_preferred(
        workspace,
        ["drive", "files", "create"],
        body=body,
    )
    if gws_payload is not None:
        return {
            "status": "created",
            "id": str(gws_payload.get("id", "")),
            "name": str(gws_payload.get("name", "")),
            "webViewLink": str(gws_payload.get("webViewLink", "")),
        }
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
    """Create a Drive permission for a file.

    Args:
        workspace (str | Path): Parameter.
        file_id (str): Parameter.
        role (str): Parameter.
        permission_type (str): Parameter.
        email (str | None): Parameter.
        domain (str | None): Parameter.
        notify (bool): Parameter.

    Returns:
        dict[str, object]: Result.

    Examples:
        >>> drive_share  # doctest: +SKIP
    """

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
    gws_payload = _gws_if_preferred(
        workspace,
        ["drive", "permissions", "create"],
        params={"fileId": file_id, "sendNotificationEmail": notify},
        body=permission,
    )
    if gws_payload is not None:
        return {
            "status": "shared",
            "permissionId": str(gws_payload.get("id", "")),
            "fileId": file_id,
            "role": role,
            "type": permission_type,
        }
    service = google_workspace.build_service(_workspace_path(workspace), "drive", "v3")
    result = (
        service.permissions()
        .create(
            fileId=file_id,
            body=permission,
            sendNotificationEmail=notify,
            fields="id",
        )
        .execute()
    )
    return {
        "status": "shared",
        "permissionId": str(result.get("id", "")),
        "fileId": file_id,
        "role": role,
        "type": permission_type,
    }


def drive_delete(
    workspace: str | Path, file_id: str, *, permanent: bool = False
) -> dict[str, object]:
    """Trash or permanently delete a Google Drive file.

    Args:
        workspace (str | Path): Parameter.
        file_id (str): Parameter.
        permanent (bool): Parameter.

    Returns:
        dict[str, object]: Result.

    Examples:
        >>> drive_delete  # doctest: +SKIP
    """

    params = {"file_id": file_id, "permanent": permanent}
    if _dry_run_requested():
        return _dry_run(
            workspace,
            service="drive",
            operation="delete",
            parameters=params,
            scopes=_drive_scopes(),
        )
    if permanent:
        gws_payload = _gws_if_preferred(
            workspace,
            ["drive", "files", "delete"],
            params={"fileId": file_id},
        )
        if gws_payload is not None:
            return {"status": "deleted", "fileId": file_id, "permanent": True}
    else:
        gws_payload = _gws_if_preferred(
            workspace,
            ["drive", "files", "update"],
            params={"fileId": file_id},
            body={"trashed": True},
        )
        if gws_payload is not None:
            return {"status": "trashed", "fileId": file_id, "permanent": False}
    service = google_workspace.build_service(_workspace_path(workspace), "drive", "v3")
    if permanent:
        service.files().delete(fileId=file_id).execute()
        return {"status": "deleted", "fileId": file_id, "permanent": True}
    service.files().update(fileId=file_id, body={"trashed": True}).execute()
    return {"status": "trashed", "fileId": file_id, "permanent": False}


def contacts_list(
    workspace: str, max_results: int = 20
) -> list[dict[str, object]] | dict[str, object]:
    """List Google contacts via the People API.

    Args:
        workspace (str): Parameter.
        max_results (int): Parameter.

    Returns:
        list[dict[str, object]] | dict[str, object]: Result.

    Examples:
        >>> contacts_list  # doctest: +SKIP
    """

    params = {"max_results": max_results}
    if _dry_run_requested():
        return _dry_run(
            workspace,
            service="contacts",
            operation="list",
            parameters=params,
            scopes=_contacts_scopes(),
        )
    gws_payload = _gws_if_preferred(
        workspace,
        ["people", "people", "connections", "list"],
        params={
            "resourceName": "people/me",
            "pageSize": max(max_results, 0),
            "personFields": "names,emailAddresses,phoneNumbers",
        },
    )
    if gws_payload is not None:
        return _gws_as_list(gws_payload, "connections", "people")
    service = google_workspace.build_service(_workspace_path(workspace), "people", "v1")
    results = (
        service.people()
        .connections()
        .list(
            resourceName="people/me",
            pageSize=max(max_results, 0),
            personFields="names,emailAddresses,phoneNumbers",
        )
        .execute()
    )
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
    """Fetch values for a Google Sheets range.

    Args:
        workspace (str | Path): Parameter.
        spreadsheet_id (str): Parameter.
        range_name (str): Parameter.

    Returns:
        list[list[object]] | dict[str, object]: Result.

    Examples:
        >>> sheets_get  # doctest: +SKIP
    """

    params = {"spreadsheet_id": spreadsheet_id, "range": range_name}
    if _dry_run_requested():
        return _dry_run(
            workspace,
            service="sheets",
            operation="get",
            parameters=params,
            scopes=_sheets_scopes(),
        )
    gws_payload = _gws_if_preferred(
        workspace,
        ["sheets", "spreadsheets", "values", "get"],
        params={"spreadsheetId": spreadsheet_id, "range": range_name},
    )
    if gws_payload is not None:
        values = gws_payload.get("values", [])
        if isinstance(values, list):
            return [row for row in values if isinstance(row, list)]
        return []
    service = google_workspace.build_service(_workspace_path(workspace), "sheets", "v4")
    result = (
        service.spreadsheets()
        .values()
        .get(
            spreadsheetId=spreadsheet_id,
            range=range_name,
        )
        .execute()
    )
    values = result.get("values", []) if isinstance(result, dict) else []
    return [row for row in values if isinstance(row, list)]


def sheets_update(
    workspace: str | Path,
    spreadsheet_id: str,
    range_name: str,
    values: list[list[object]],
) -> dict[str, object]:
    """Update a Google Sheets range with user-entered values.

    Args:
        workspace (str | Path): Parameter.
        spreadsheet_id (str): Parameter.
        range_name (str): Parameter.
        values (list[list[object]]): Parameter.

    Returns:
        dict[str, object]: Result.

    Examples:
        >>> sheets_update  # doctest: +SKIP
    """

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
    gws_payload = _gws_if_preferred(
        workspace,
        ["sheets", "spreadsheets", "values", "update"],
        params={
            "spreadsheetId": spreadsheet_id,
            "range": range_name,
            "valueInputOption": "USER_ENTERED",
        },
        body={"values": values},
    )
    if gws_payload is not None:
        updated_cells = gws_payload.get("updatedCells", 0)
        return {
            "updatedCells": int(updated_cells)
            if isinstance(updated_cells, (int, float, str))
            else 0,
            "updatedRange": str(gws_payload.get("updatedRange", "")),
        }
    service = google_workspace.build_service(_workspace_path(workspace), "sheets", "v4")
    result = (
        service.spreadsheets()
        .values()
        .update(
            spreadsheetId=spreadsheet_id,
            range=range_name,
            valueInputOption="USER_ENTERED",
            body={"values": values},
        )
        .execute()
    )
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
    """Append rows to a Google Sheets range.

    Args:
        workspace (str | Path): Parameter.
        spreadsheet_id (str): Parameter.
        range_name (str): Parameter.
        values (list[list[object]]): Parameter.

    Returns:
        dict[str, object]: Result.

    Examples:
        >>> sheets_append  # doctest: +SKIP
    """

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
    gws_payload = _gws_if_preferred(
        workspace,
        ["sheets", "spreadsheets", "values", "append"],
        params={
            "spreadsheetId": spreadsheet_id,
            "range": range_name,
            "valueInputOption": "USER_ENTERED",
            "insertDataOption": "INSERT_ROWS",
        },
        body={"values": values},
    )
    if gws_payload is not None:
        updates = gws_payload.get("updates", {})
        if not isinstance(updates, dict):
            updates = {}
        updated_cells = updates.get("updatedCells", 0)
        return {
            "updatedCells": int(updated_cells)
            if isinstance(updated_cells, (int, float, str))
            else 0,
        }
    service = google_workspace.build_service(_workspace_path(workspace), "sheets", "v4")
    result = (
        service.spreadsheets()
        .values()
        .append(
            spreadsheetId=spreadsheet_id,
            range=range_name,
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": values},
        )
        .execute()
    )
    updates = result.get("updates", {}) if isinstance(result, dict) else {}
    return {"updatedCells": int(updates.get("updatedCells", 0))}


def sheets_create(
    workspace: str | Path,
    title: str,
    *,
    sheet_name: str | None = None,
) -> dict[str, object]:
    """Create a new Google Sheets spreadsheet.

    Args:
        workspace (str | Path): Parameter.
        title (str): Parameter.
        sheet_name (str | None): Parameter.

    Returns:
        dict[str, object]: Result.

    Examples:
        >>> sheets_create  # doctest: +SKIP
    """

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
    gws_payload = _gws_if_preferred(
        workspace,
        ["sheets", "spreadsheets", "create"],
        body=body,
    )
    if gws_payload is not None:
        properties = gws_payload.get("properties", {})
        return {
            "status": "created",
            "spreadsheetId": str(gws_payload.get("spreadsheetId", "")),
            "title": str(properties.get("title", "")) if isinstance(properties, dict) else "",
            "spreadsheetUrl": str(gws_payload.get("spreadsheetUrl", "")),
        }
    service = google_workspace.build_service(_workspace_path(workspace), "sheets", "v4")
    result = (
        service.spreadsheets()
        .create(
            body=body,
            fields="spreadsheetId,properties,spreadsheetUrl",
        )
        .execute()
    )
    properties = result.get("properties", {}) if isinstance(result, dict) else {}
    return {
        "status": "created",
        "spreadsheetId": str(result.get("spreadsheetId", "")),
        "title": str(properties.get("title", "")) if isinstance(properties, dict) else "",
        "spreadsheetUrl": str(result.get("spreadsheetUrl", "")),
    }


def docs_get(workspace: str | Path, document_id: str) -> dict[str, object]:
    """Fetch a Google Doc and return extracted plain text.

    Args:
        workspace (str | Path): Parameter.
        document_id (str): Parameter.

    Returns:
        dict[str, object]: Result.

    Examples:
        >>> docs_get  # doctest: +SKIP
    """

    params = {"document_id": document_id}
    if _dry_run_requested():
        return _dry_run(
            workspace,
            service="docs",
            operation="get",
            parameters=params,
            scopes=_docs_scopes(),
        )
    gws_payload = _gws_if_preferred(
        workspace,
        ["docs", "documents", "get"],
        params={"documentId": document_id},
    )
    if gws_payload is not None:
        return {
            "title": str(gws_payload.get("title", "")),
            "documentId": str(gws_payload.get("documentId", "")),
            "body": _extract_doc_text(gws_payload),
        }
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
    """Create a new Google Doc, optionally with initial body text.

    Args:
        workspace (str | Path): Parameter.
        title (str): Parameter.
        body (str | None): Parameter.

    Returns:
        dict[str, object]: Result.

    Examples:
        >>> docs_create  # doctest: +SKIP
    """

    params = {"title": title, "body": body}
    if _dry_run_requested():
        return _dry_run(
            workspace,
            service="docs",
            operation="create",
            parameters=params,
            scopes=_docs_scopes(),
        )
    gws_payload = _gws_if_preferred(
        workspace,
        ["docs", "documents", "create"],
        body={"title": title},
    )
    if gws_payload is not None:
        document_id = str(gws_payload.get("documentId", ""))
        if body and document_id:
            _docs_insert_text(workspace, document_id, body, 1)
        return {
            "status": "created",
            "documentId": document_id,
            "title": str(gws_payload.get("title", title)),
            "url": (
                f"https://docs.google.com/document/d/{document_id}/edit" if document_id else ""
            ),
        }
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
    """Append text to the end of a Google Doc.

    Args:
        workspace (str | Path): Parameter.
        document_id (str): Parameter.
        text (str): Parameter.

    Returns:
        dict[str, object]: Result.

    Examples:
        >>> docs_append  # doctest: +SKIP
    """

    params = {"document_id": document_id, "text": text}
    if _dry_run_requested():
        return _dry_run(
            workspace,
            service="docs",
            operation="append",
            parameters=params,
            scopes=_docs_scopes(),
        )
    # Append needs document endIndex; keep Python path for correct insert position.
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
