"""Shared type aliases for the self-improve loop (`specs/33-self-improvement.md` §2).

The ``ImproveJobId`` symbol is declared via ``typing.NewType`` below (SQLite primary keys).

Module: sevn.self_improve.types
Depends: typing

Exports:
    OwnerPrincipal — owner-only gate for enqueue/abort surfaces.
"""

from __future__ import annotations

from typing import Literal, NewType, TypedDict

ImproveJobId = NewType("ImproveJobId", str)


class OwnerPrincipal(TypedDict):
    """Authenticated owner subject for privileged self-improve actions.

    Attributes:
        principal_id: Opaque stable id from the dashboard / operator session.

    Examples:
        >>> OwnerPrincipal(principal_kind="owner", principal_id="op-1")["principal_id"]
        'op-1'
    """

    principal_id: str
    principal_kind: Literal["owner"]


__all__ = ["ImproveJobId", "OwnerPrincipal"]
