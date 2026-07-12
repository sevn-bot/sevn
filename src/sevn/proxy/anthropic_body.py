"""Anthropic Messages request normalization for the egress proxy (`specs/07-egress-proxy.md` §5).

Module: sevn.proxy.anthropic_body
Depends: none (stdlib only)

MiniMax's Anthropic-compatible API rejects bodies that combine top-level ``system`` with
``role: system`` inside ``messages`` (upstream ``invalid chat setting (2013)``). This
module lifts system roles out of ``messages`` and merges them into a single top-level
``system`` field before upstream forward.

Exports:
    normalize_anthropic_request_body — coerce OpenAI-shaped bodies to Anthropic/MiniMax shape.

Examples:
    >>> from sevn.proxy.anthropic_body import normalize_anthropic_request_body
    >>> out = normalize_anthropic_request_body({
    ...     "system": "a",
    ...     "messages": [{"role": "system", "content": "b"}, {"role": "user", "content": "u"}],
    ... })
    >>> out["system"], out["messages"]
    ('a\\n\\nb', [{'role': 'user', 'content': 'u'}])
"""

from __future__ import annotations


def _system_and_messages(messages: list[object]) -> tuple[str | None, list[dict[str, object]]]:
    """Lift ``role: system`` entries out, keep order of remaining roles.

    Args:
        messages (list[object]): OpenAI-shaped ``messages`` array.

    Returns:
        tuple[str | None, list[dict[str, object]]]: Concatenated system text and
        remaining messages. Multiple ``system`` blocks are joined with blank lines.

    Examples:
        >>> _system_and_messages([
        ...     {"role": "system", "content": "a"},
        ...     {"role": "user", "content": "hi"},
        ... ])
        ('a', [{'role': 'user', 'content': 'hi'}])
    """
    system_parts: list[str] = []
    rest: list[dict[str, object]] = []
    for m in messages:
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        content = m.get("content")
        if role == "system":
            if isinstance(content, str) and content.strip():
                system_parts.append(content)
            continue
        rest.append(dict(m))
    system = "\n\n".join(system_parts) if system_parts else None
    return system, rest


def normalize_anthropic_request_body(body: dict[str, object]) -> dict[str, object]:
    """Coerce a request dict into Anthropic/MiniMax-valid shape before egress.

    Lifts every ``role: system`` entry out of ``messages`` into top-level ``system``
    (merging with an existing top-level ``system`` when both are present). When only
    system text remains, inserts a minimal ``user`` message because MiniMax rejects
    empty ``messages``.

    Args:
        body (dict[str, object]): Outbound Anthropic Messages body (may be OpenAI-shaped).

    Returns:
        dict[str, object]: Normalized copy safe to POST upstream.

    Examples:
        >>> out = normalize_anthropic_request_body({
        ...     "model": "MiniMax-M2.7",
        ...     "system": "persona",
        ...     "messages": [
        ...         {"role": "system", "content": "task"},
        ...         {"role": "user", "content": "hi"},
        ...     ],
        ... })
        >>> out["system"], out["messages"]
        ('persona\\n\\ntask', [{'role': 'user', 'content': 'hi'}])
    """
    out = dict(body)
    messages = out.get("messages")
    if isinstance(messages, list):
        lifted, rest = _system_and_messages(list(messages))
        out["messages"] = rest
        if lifted is not None:
            existing = out.get("system")
            if isinstance(existing, str) and existing.strip():
                out["system"] = f"{existing.strip()}\n\n{lifted}"
            elif lifted.strip():
                out["system"] = lifted
    msgs = out.get("messages")
    if isinstance(msgs, list) and not msgs:
        out["messages"] = [{"role": "user", "content": "."}]
    return out


__all__ = ["normalize_anthropic_request_body"]
