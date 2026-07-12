"""Egress LLM proxy (ASGI): vendor auth injection for ``/llm/*`` routes.

Module: sevn.proxy
Depends: starlette, httpx, pydantic-settings

Exports:
    (none) — import ``sevn.proxy.app`` for the ASGI ``app``.

Examples:
    >>> import sevn.proxy
    >>> sevn.proxy.__doc__ is not None
    True
"""
