"""Framework adapter entrypoints bridging ``ToolSet`` + ``ToolExecutor``.

Module: sevn.agent.adapters
Depends: sevn.agent.adapters.dspy_adapter, sevn.agent.adapters.pydantic_adapter

Exports:
    dspy_adapter — Tier C/D callable facades (DSPy/λ-RLM readiness).
    pydantic_adapter — Tier B descriptions-only scaffolding.

Examples:
    >>> from sevn.agent import adapters
    >>> adapters.dspy_adapter.lambda_rlm_filter({"a": 1, "b": 2}, allowlist={"a"})
    {'a': 1}
"""

from __future__ import annotations

from . import dspy_adapter as dspy_adapter
from . import pydantic_adapter as pydantic_adapter

__all__ = [
    "dspy_adapter",
    "pydantic_adapter",
]
