"""Error wire shape and schema export (D14, D18)."""

from __future__ import annotations

import json


def test_error_shape() -> None:
    from sevn.contracts.errors import ProtocolError

    error = ProtocolError("invalid_params", "bad", {"errors": []})
    assert error.dump() == {
        "code": "invalid_params",
        "message": "bad",
        "data": {"errors": []},
    }


def test_export_is_deterministic() -> None:
    from sevn.contracts.export import build_schema

    first = build_schema()
    second = build_schema()
    assert isinstance(first, dict)
    assert json.dumps(first) == json.dumps(second)
    assert {"$defs", "methods", "events"} <= set(first)


def test_method_table() -> None:
    from sevn.contracts.export import build_schema

    methods = build_schema()["methods"]
    expected = {
        "system.info": False,
        "system.ping": True,
        "sync.since": False,
    }
    for name, mutating in expected.items():
        spec = methods[name]
        assert isinstance(spec["params"], str) and spec["params"]
        assert isinstance(spec["result"], str) and spec["result"]
        assert spec["mutating"] is mutating
