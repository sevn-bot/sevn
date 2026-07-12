"""Golden live-LLM corpus fixtures (pydantic-stack W11).

Exports:
    GOLDEN_LLM_ROOT — path to this fixture tree.
"""

from __future__ import annotations

from pathlib import Path

GOLDEN_LLM_ROOT: Path = Path(__file__).resolve().parent

__all__ = ["GOLDEN_LLM_ROOT"]
