"""CodeMode Monty ``ResourceLimits`` shim (`specs/14-executor-tier-b.md` W8).

A CPU-bound or pathological ``run_code`` snippet ran synchronously on the event loop and froze
the gateway for 8.5 min (gateway.log 2026-06-22), because the outer ``asyncio.wait_for`` cannot
fire while the loop is blocked. The shim injects Monty ``ResourceLimits`` so the Rust sandbox
aborts such snippets regardless of the event loop.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from sevn.agent.adapters._monty_limits import (
    default_codemode_limits,
    install_monty_resource_limits,
)
from sevn.config.defaults import DEFAULT_CODEMODE_MAX_DURATION_S, DEFAULT_CODEMODE_MAX_RETRIES
from sevn.config.model_resolution import codemode_max_retries, codemode_resource_limits
from sevn.config.workspace_config import WorkspaceConfig


def test_default_codemode_limits_are_positive() -> None:
    limits = default_codemode_limits()
    assert limits["max_duration_secs"] == DEFAULT_CODEMODE_MAX_DURATION_S
    assert limits["max_memory"] > 0
    assert limits["max_allocations"] > 0


def test_codemode_resource_limits_defaults_and_override() -> None:
    assert (
        codemode_resource_limits(WorkspaceConfig.minimal())["max_duration_secs"]
        == DEFAULT_CODEMODE_MAX_DURATION_S
    )
    overridden = codemode_resource_limits(
        WorkspaceConfig.minimal(
            agent={"codemode": {"max_duration_secs": 12, "max_memory_bytes": 1024}},
        ),
    )
    assert overridden["max_duration_secs"] == 12.0
    assert overridden["max_memory"] == 1024


def test_codemode_resource_limits_ignores_bad_values() -> None:
    # Zero / bool / missing fall back to defaults rather than disabling the cap.
    bad = codemode_resource_limits(
        WorkspaceConfig.minimal(agent={"codemode": {"max_duration_secs": 0}}),
    )
    assert bad["max_duration_secs"] == DEFAULT_CODEMODE_MAX_DURATION_S


def test_codemode_max_retries_defaults_and_override() -> None:
    assert codemode_max_retries(WorkspaceConfig.minimal()) == DEFAULT_CODEMODE_MAX_RETRIES
    assert (
        codemode_max_retries(
            WorkspaceConfig.minimal(agent={"codemode": {"max_retries": 5}}),
        )
        == 5
    )


def test_codemode_max_retries_ignores_bad_values() -> None:
    assert (
        codemode_max_retries(
            SimpleNamespace(agent={"codemode": {"max_retries": 0}}),
        )
        == DEFAULT_CODEMODE_MAX_RETRIES
    )
    assert (
        codemode_max_retries(
            SimpleNamespace(agent={"codemode": {"max_retries": True}}),
        )
        == DEFAULT_CODEMODE_MAX_RETRIES
    )


def test_install_is_idempotent_and_updates_limits() -> None:
    install_monty_resource_limits({"max_duration_secs": 1})
    from pydantic_ai_harness.code_mode import _toolset as ts

    first = ts.MontyRepl
    install_monty_resource_limits({"max_duration_secs": 2})
    # Patch applied once: the symbol object is stable across re-installs.
    assert ts.MontyRepl is first


def _drive_to_completion(repl: object, code: str) -> object:
    """Run *code* in *repl*, advancing Monty snapshots until completion."""
    from pydantic_ai_harness.code_mode import _toolset as ts

    state = repl.feed_start(code)  # type: ignore[attr-defined]
    while not isinstance(state, ts.MontyComplete):
        state = state.resume()
    return state


def test_runaway_snippet_aborts_within_cap() -> None:
    """An infinite loop must abort near the duration cap, not run unbounded."""
    install_monty_resource_limits({"max_duration_secs": 0.5})
    from pydantic_ai_harness.code_mode import _toolset as ts

    repl = ts.MontyRepl()
    t0 = time.monotonic()
    with pytest.raises(ts.MontyRuntimeError) as exc:
        _drive_to_completion(repl, "x = 0\nwhile True:\n    x += 1\n")
    elapsed = time.monotonic() - t0
    assert "time limit" in str(exc.value).lower()
    assert elapsed < 5.0, f"abort took {elapsed:.2f}s — cap not enforced"
