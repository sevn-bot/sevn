"""REF resolution helpers."""

from __future__ import annotations

from proton_cli.errors import Ambiguous, NotFound


def pick(kind: str, ref: str, items: list, id_fn, label_fn) -> object:
    if not items:
        raise NotFound(kind, ref)
    if len(items) == 1:
        return items[0]
    candidates = [(id_fn(it), label_fn(it)) for it in items]
    raise Ambiguous(kind, ref, candidates)
