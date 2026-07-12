"""Shipped README template and prompt directory paths.

Module: sevn.docs.readme.paths
Depends: pathlib

Exports:
    templates_dir — Jinja2 templates shipped in the wheel.
    prompts_dir — Section prompt TOML files shipped in the wheel.

Examples:
    >>> templates_dir.name
    'templates'
    >>> prompts_dir.name
    'prompts'
"""

from __future__ import annotations

from pathlib import Path

_PACKAGE_ROOT = Path(__file__).resolve().parent
templates_dir = _PACKAGE_ROOT / "templates"
prompts_dir = _PACKAGE_ROOT / "prompts"
