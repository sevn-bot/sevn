"""Trace redaction wrapper applied once before sink fan-out (`specs/04-tracing.md` §2.5).

Module: sevn.agent.tracing.redacting_sink
Depends: copy, dataclasses, re, sevn.agent.tracing.sink, sevn.config.defaults
Exports:
    TraceRedactionPolicy — deny-key and pattern rules for one emit pass.
    redact_attrs — redact one attrs mapping without building a ``TraceEvent``.
    redact — return a copy of ``TraceEvent`` with redacted ``attrs``.
    RedactingSink — ``TraceSink`` decorator that redacts once then delegates.
Examples:
    >>> from sevn.agent.tracing.redacting_sink import TraceRedactionPolicy, redact
    >>> from sevn.agent.tracing.sink import TraceEvent
    >>> policy = TraceRedactionPolicy.from_defaults()
    >>> event = TraceEvent(
    ...     kind="tool.call",
    ...     span_id="s1",
    ...     parent_span_id=None,
    ...     session_id="se",
    ...     turn_id="tu",
    ...     tier="B",
    ...     ts_start_ns=1,
    ...     ts_end_ns=2,
    ...     status="ok",
    ...     attrs={"api_key": "sk-abcdefghijklmnopqrstuvwxyz123456"},
    ... )
    >>> out = redact(event, policy)
    >>> out.attrs["api_key"]
    '<redacted>'
"""

from __future__ import annotations

import copy
import dataclasses
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sevn.agent.tracing.redaction_config import TRACE_USAGE_METRIC_ATTR_KEYS
from sevn.config.defaults import (
    DEFAULT_TRACE_REDACTION_DENY_KEYS,
    DEFAULT_TRACE_REDACTION_DENY_VALUE_PATTERNS,
    DEFAULT_TRACE_REDACTION_ENABLED,
)

if TYPE_CHECKING:
    from sevn.agent.tracing.sink import TraceEvent, TraceSink

_REDACTED = "<redacted>"


@dataclass(frozen=True)
class TraceRedactionPolicy:
    """Workspace ``tracing.redaction`` rules resolved for one gateway boot."""

    enabled: bool
    deny_keys: tuple[str, ...]
    deny_value_patterns: tuple[str, ...]
    _compiled_patterns: tuple[re.Pattern[str], ...] = dataclasses.field(
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        """Compile ``deny_value_patterns`` once for reuse on each emit.

        Examples:
            >>> policy = TraceRedactionPolicy.from_defaults()
            >>> len(policy._compiled_patterns) >= 1
            True
        """
        if not self._compiled_patterns:
            compiled = tuple(re.compile(p) for p in self.deny_value_patterns)
            object.__setattr__(self, "_compiled_patterns", compiled)

    @classmethod
    def from_defaults(cls) -> TraceRedactionPolicy:
        """Build the shipped default redaction policy.

        Returns:
            TraceRedactionPolicy: Enabled policy from ``config/defaults.py``.
        Examples:
            >>> policy = TraceRedactionPolicy.from_defaults()
            >>> policy.enabled
            True
        """
        return cls(
            enabled=DEFAULT_TRACE_REDACTION_ENABLED,
            deny_keys=DEFAULT_TRACE_REDACTION_DENY_KEYS,
            deny_value_patterns=DEFAULT_TRACE_REDACTION_DENY_VALUE_PATTERNS,
            _compiled_patterns=(),
        )


def _key_denied(key: object, deny_keys: tuple[str, ...]) -> bool:
    """Return whether ``key`` matches any deny-list substring.

    Args:
        key (object): Attribute name from a trace attrs mapping.
        deny_keys (tuple[str, ...]): Lowercase substrings to match.
    Returns:
        bool: ``True`` when the key should be redacted.
    Examples:
        >>> _key_denied("api_key", ("api_key",))
        True
    """
    lowered = str(key).lower()
    if lowered in TRACE_USAGE_METRIC_ATTR_KEYS:
        return False
    return any(part in lowered for part in deny_keys)


def _redact_value(value: object, policy: TraceRedactionPolicy) -> object:
    """Recursively redact nested structures and pattern-matched strings.

    Args:
        value (object): Scalar or collection from trace attrs.
        policy (TraceRedactionPolicy): Active redaction rules.
    Returns:
        object: Redacted copy of ``value``.
    Examples:
        >>> policy = TraceRedactionPolicy.from_defaults()
        >>> _redact_value("sk-abcdefghijklmnopqrstuvwxyz123456", policy)
        '<redacted>'
    """
    if isinstance(value, dict):
        return _redact_mapping(value, policy)
    if isinstance(value, list):
        return [_redact_value(item, policy) for item in value]
    if isinstance(value, str):
        for pattern in policy._compiled_patterns:
            if pattern.search(value):
                return _REDACTED
    return value


def _redact_mapping(attrs: dict[str, object], policy: TraceRedactionPolicy) -> dict[str, object]:
    """Redact one attrs mapping without mutating the input dict.

    Args:
        attrs (dict[str, object]): Trace event attributes.
        policy (TraceRedactionPolicy): Active redaction rules.
    Returns:
        dict[str, object]: New mapping with sensitive keys and values masked.
    Examples:
        >>> policy = TraceRedactionPolicy.from_defaults()
        >>> _redact_mapping({"password": "x"}, policy)
        {'password': '<redacted>'}
    """
    out: dict[str, object] = {}
    for key, value in attrs.items():
        if _key_denied(key, policy.deny_keys):
            out[str(key)] = _REDACTED
        else:
            out[str(key)] = _redact_value(value, policy)
    return out


def redact_attrs(attrs: dict[str, object], policy: TraceRedactionPolicy) -> dict[str, object]:
    """Return a redacted copy of ``attrs`` per ``policy`` without mutating input.

    Args:
        attrs (dict[str, object]): Trace event attributes from storage.
        policy (TraceRedactionPolicy): Resolved workspace redaction rules.
    Returns:
        dict[str, object]: Redacted attrs copy (identity when policy disabled).
    Examples:
        >>> policy = TraceRedactionPolicy.from_defaults()
        >>> raw = {"api_key": "sk-abcdefghijklmnopqrstuvwxyz123456", "safe": "x"}
        >>> out = redact_attrs(raw, policy)
        >>> raw["api_key"].startswith("sk-")
        True
        >>> out["api_key"]
        '<redacted>'
    """
    attrs_copy = copy.deepcopy(attrs)
    if not policy.enabled:
        return attrs_copy
    return _redact_mapping(attrs_copy, policy)


def redact(event: TraceEvent, policy: TraceRedactionPolicy) -> TraceEvent:
    """Return a copy of ``event`` with ``attrs`` redacted per ``policy``.

    The caller's ``event.attrs`` dict is never mutated.
    Args:
        event (TraceEvent): Raw trace row from emit sites.
        policy (TraceRedactionPolicy): Resolved workspace redaction rules.
    Returns:
        TraceEvent: Same identity fields with a redacted ``attrs`` copy.
    Examples:
        >>> from sevn.agent.tracing.redacting_sink import TraceRedactionPolicy, redact
        >>> from sevn.agent.tracing.sink import TraceEvent
        >>> policy = TraceRedactionPolicy.from_defaults()
        >>> raw = {"token": "keep-me", "nested": {"password": "x"}}
        >>> event = TraceEvent(
        ...     kind="k",
        ...     span_id="s",
        ...     parent_span_id=None,
        ...     session_id="se",
        ...     turn_id="tu",
        ...     tier=None,
        ...     ts_start_ns=1,
        ...     ts_end_ns=None,
        ...     status="ok",
        ...     attrs=raw,
        ... )
        >>> out = redact(event, policy)
        >>> raw["token"]
        'keep-me'
        >>> out.attrs["nested"]
        {'password': '<redacted>'}
    """
    attrs_copy = copy.deepcopy(event.attrs)
    redacted_attrs = _redact_mapping(attrs_copy, policy)
    return dataclasses.replace(event, attrs=redacted_attrs)


class RedactingSink:
    """Wrap one inner sink and redact each ``emit`` once before delegation."""

    def __init__(self, inner: TraceSink, policy: TraceRedactionPolicy) -> None:
        """Attach ``inner`` and the redaction policy used on every ``emit``.

        Args:
            inner (TraceSink): Composite or leaf sink (for example ``MultiSink``).
            policy (TraceRedactionPolicy): Rules applied once per ``emit``.
        Examples:
            >>> from sevn.agent.tracing.sink import NullTraceSink
            >>> sink = RedactingSink(NullTraceSink(), TraceRedactionPolicy.from_defaults())
            >>> sink is not None
            True
        """
        self._inner = inner
        self._policy = policy

    async def emit(self, event: TraceEvent) -> None:
        """Redact ``event`` once, then forward the copy to ``inner``.

        Args:
            event (TraceEvent): Raw trace row from emit sites.
        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(RedactingSink.emit)
            True
        """
        redacted = redact(event, self._policy)
        await self._inner.emit(redacted)

    async def flush(self) -> None:
        """Flush the wrapped inner sink.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(RedactingSink.flush)
            True
        """
        await self._inner.flush()

    async def close(self) -> None:
        """Close the wrapped inner sink.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(RedactingSink.close)
            True
        """
        await self._inner.close()


__all__ = ["RedactingSink", "TraceRedactionPolicy", "redact", "redact_attrs"]
