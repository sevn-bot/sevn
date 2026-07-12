"""CodeMode string-kwarg coercion at the shared validator boundary (`specs/11-tools-registry.md` §6).

Tier-B models under CodeMode (``run_code``) re-enter ``ToolExecutor.dispatch`` with kwargs as
written in the sandbox — typed values arrive as strings. These assert the central coercion turns
those would-be VALIDATION_ERROR drops (which burn the ``run_code`` retry budget) into normal calls,
while leaving native typed calls and un-coercible values untouched.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from sevn.tools.base import (
    FunctionTool,
    ToolCall,
    ToolDefinition,
    ToolExecutor,
    enveloped_success,
)
from sevn.tools.codes import ToolResultCode
from sevn.tools.context import ToolContext
from sevn.tools.permissions import AllowAllPermissionPolicy
from sevn.tools.validation import coerce_string_scalars_to_schema


def test_coerce_int_number_bool_array_object() -> None:
    schema = {
        "type": "object",
        "properties": {
            "n": {"type": "integer"},
            "f": {"type": "number"},
            "b": {"type": "boolean"},
            "arr": {"type": "array"},
            "obj": {"type": "object"},
        },
    }
    out = coerce_string_scalars_to_schema(
        schema,
        {"n": "100", "f": "0.5", "b": "false", "arr": '["x", "y"]', "obj": '{"k": 1}'},
    )
    assert out == {"n": 100, "f": 0.5, "b": False, "arr": ["x", "y"], "obj": {"k": 1}}


def test_coerce_list_typed_and_correct_values_pass_through() -> None:
    schema = {
        "type": "object",
        "properties": {
            "lines": {"type": ["integer", "string"]},  # widened: validator skips, leave as-is
            "name": {"type": "string"},
            "n": {"type": "integer"},
        },
    }
    data = {"lines": "100", "name": "x", "n": 5}
    out = coerce_string_scalars_to_schema(schema, data)
    assert out == {"lines": "100", "name": "x", "n": 5}


def test_coerce_uncoercible_left_for_validator() -> None:
    schema = {"type": "object", "properties": {"n": {"type": "integer"}, "b": {"type": "boolean"}}}
    out = coerce_string_scalars_to_schema(schema, {"n": "abc", "b": "maybe"})
    assert out == {"n": "abc", "b": "maybe"}


def _ctx(workspace: Path) -> ToolContext:
    return ToolContext(
        session_id="s",
        workspace_path=workspace,
        workspace_id="w",
        registry_version=1,
        trace=None,
        permissions=AllowAllPermissionPolicy(),
    )


def _typed_executor(seen: dict[str, Any]) -> ToolExecutor:
    async def typed(ctx: ToolContext, **kwargs: Any) -> str:
        seen.update(kwargs)
        return enveloped_success({"got": {k: type(v).__name__ for k, v in kwargs.items()}})

    definition = ToolDefinition(
        name="typed",
        category="meta",
        description="typed",
        parameters={
            "type": "object",
            "properties": {
                "lines": {"type": "integer"},
                "summarize": {"type": "boolean"},
            },
        },
    )
    exe = ToolExecutor(default_timeout_seconds=5.0)
    exe.register(FunctionTool(definition, typed))
    return exe


def test_dispatch_coerces_codemode_string_kwargs(tmp_path: Path) -> None:
    """Dispatch with string kwargs (CodeMode form) succeeds and the tool receives typed values."""
    seen: dict[str, Any] = {}
    exe = _typed_executor(seen)
    raw = asyncio.run(
        exe.dispatch(
            _ctx(tmp_path),
            ToolCall(name="typed", arguments={"lines": "100", "summarize": "false"}),
        )
    )
    env = json.loads(raw)
    assert env["ok"] is True
    assert seen == {"lines": 100, "summarize": False}


def test_dispatch_uncoercible_string_still_validation_error(tmp_path: Path) -> None:
    """A non-numeric string for an integer param still returns VALIDATION_ERROR (not a silent drop)."""
    exe = _typed_executor({})
    raw = asyncio.run(
        exe.dispatch(
            _ctx(tmp_path),
            ToolCall(name="typed", arguments={"lines": "abc"}),
        )
    )
    env = json.loads(raw)
    assert env["ok"] is False
    assert env["code"] == ToolResultCode.VALIDATION_ERROR
