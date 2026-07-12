"""Shipped about-docs prompt directory paths.

Module: sevn.docs.about.paths
Depends: pathlib

Exports:
    prompts_dir — per-kind prose prompt TOML files for about-docs generation.

Examples:
    >>> prompts_dir.name
    'prompts'
"""

from __future__ import annotations

from pathlib import Path

_PACKAGE_ROOT = Path(__file__).resolve().parent
prompts_dir = _PACKAGE_ROOT / "prompts"
