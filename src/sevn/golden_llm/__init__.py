"""Golden live-LLM corpus harness (pydantic-stack W11, #91).

Exports:
    GOLDEN_LLM_ROOT — path to case/recording JSON trees (under ``tests/fixtures/golden_llm``).
"""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
GOLDEN_LLM_ROOT: Path = _REPO_ROOT / "tests" / "fixtures" / "golden_llm"

__all__ = ["GOLDEN_LLM_ROOT"]
