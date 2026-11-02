"""The scope table ``scope_allows`` enforces (plan 0001 D7, plan 0055 D12).

D12: ``member`` = ``owner`` for now, decided in this one place; ``read_only`` is refused every
owner- and member-scoped method. A device keeps its stored scope, so narrowing ``member`` later
changes only this table.
"""

from __future__ import annotations

import pytest

D12 = pytest.mark.xfail(strict=False, reason="green after D12 member scope")


@pytest.mark.parametrize(
    ("have", "need", "allowed"),
    [
        ("owner", None, True),
        ("member", None, True),
        ("read_only", None, True),
        ("owner", "owner", True),
        pytest.param("member", "owner", True, marks=D12),
        ("read_only", "owner", False),
        ("owner", "member", True),
        ("member", "member", True),
        ("read_only", "member", False),
        ("owner", "read_only", True),
        ("member", "read_only", True),
        ("read_only", "read_only", True),
        ("admin", "owner", False),
        ("", "owner", False),
        ("admin", "read_only", False),
    ],
)
def test_scope_allows_table(have: str, need: str | None, allowed: bool) -> None:
    from sevn.protocol.errors import scope_allows

    assert scope_allows(have, need) is allowed  # type: ignore[arg-type]
