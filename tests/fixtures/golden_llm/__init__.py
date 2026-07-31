"""Golden live-LLM corpus fixtures (pydantic-stack W11).

Re-exports :mod:`sevn.golden_llm` for pytest discovery paths under ``tests/fixtures/``.
"""

from __future__ import annotations

from sevn.golden_llm import GOLDEN_LLM_ROOT

__all__ = ["GOLDEN_LLM_ROOT"]
