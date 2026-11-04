"""Secret redaction for exported telemetry (plan 0015 D7).

``scrub`` applies the log redaction rules (registered secret values first,
longest first, then known key shapes) plus JWT-shaped strings. The OTLP path
runs every span through ``RedactingExporter``; the Logfire path also hands
``logfire_callback`` to Logfire's own scrubber.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from typing import TYPE_CHECKING, cast

from opentelemetry.sdk.trace import Event, ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from opentelemetry.trace import Link, Status
from opentelemetry.util.types import Attributes, AttributeValue

from sevn.log import redact_string

if TYPE_CHECKING:
    from logfire import ScrubMatch

_JWT = re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]*")
_MARKER = "«redacted»"

CONTENT_SIZE = "sevn.content.size"
CONTENT_SHA256 = "sevn.content.sha256"
CONTENT_TEXT = "sevn.content.text"


def _scrub_text(text: str) -> str:
    return _JWT.sub(_MARKER, redact_string(text))


def scrub[T](value: T) -> T:
    """Return ``value`` with secrets masked.

    A ``str`` is scrubbed; a ``list`` or ``tuple`` keeps its type with each
    string item scrubbed; any other value is returned unchanged.
    """
    if isinstance(value, str):
        return cast("T", _scrub_text(value))
    if isinstance(value, list):
        items = cast("list[object]", value)
        return cast("T", [scrub(item) for item in items])
    if isinstance(value, tuple):
        items_tuple = cast("tuple[object, ...]", value)
        return cast("T", tuple(scrub(item) for item in items_tuple))
    return value


def scrub_attributes(attributes: Attributes) -> dict[str, AttributeValue]:
    """A scrubbed copy of an OTel attribute mapping."""
    if not attributes:
        return {}
    return {key: scrub(value) for key, value in attributes.items()}


def content_attributes(text: str, *, capture: bool) -> dict[str, str | int]:
    """Size and hash of the scrubbed ``text``, and the scrubbed text itself when ``capture``."""
    scrubbed = scrub(text)
    encoded = scrubbed.encode("utf-8")
    attributes: dict[str, str | int] = {
        CONTENT_SIZE: len(encoded),
        CONTENT_SHA256: hashlib.sha256(encoded).hexdigest(),
    }
    if capture:
        attributes[CONTENT_TEXT] = scrubbed
    return attributes


def scrub_span(span: ReadableSpan) -> ReadableSpan:
    """A copy of ``span`` whose attributes, events, links and status are scrubbed."""
    status = span.status
    description = status.description
    if description:
        status = Status(status.status_code, scrub(description))
    return ReadableSpan(
        name=span.name,
        context=span.get_span_context(),
        parent=span.parent,
        resource=span.resource,
        attributes=scrub_attributes(span.attributes),
        events=[
            Event(event.name, scrub_attributes(event.attributes), event.timestamp)
            for event in span.events
        ],
        links=[Link(link.context, scrub_attributes(link.attributes)) for link in span.links],
        kind=span.kind,
        status=status,
        start_time=span.start_time,
        end_time=span.end_time,
        instrumentation_scope=span.instrumentation_scope,
    )


class RedactingExporter(SpanExporter):
    """Scrubs every span before ``inner`` sees it; flush and shutdown delegate."""

    def __init__(self, inner: SpanExporter) -> None:
        self.inner = inner

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        return self.inner.export([scrub_span(span) for span in spans])

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self.inner.force_flush(timeout_millis)

    def shutdown(self) -> None:
        self.inner.shutdown()


def logfire_callback(match: ScrubMatch) -> object | None:
    """Logfire ``ScrubbingOptions.callback``: keep the value, with sevn's redaction applied.

    A value holding a registered secret or a key pattern comes back scrubbed.
    Anything else Logfire flagged returns ``None``, so Logfire redacts it whole.
    """
    original: object = match.value
    scrubbed = scrub(original)
    if scrubbed != original:
        return scrubbed
    return None


__all__ = [
    "CONTENT_SHA256",
    "CONTENT_SIZE",
    "CONTENT_TEXT",
    "RedactingExporter",
    "content_attributes",
    "logfire_callback",
    "scrub",
    "scrub_attributes",
    "scrub_span",
]
