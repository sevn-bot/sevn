from __future__ import annotations

"""Shared helper for bundled ``playwright-browser`` scripts (_bootstrap).

Module: sevn.data.bundled_skills.core.playwright-browser.scripts._lib._bootstrap
Depends: sevn.lcm.script_cli

Exports:
    (see module members)
"""

import sys
from pathlib import Path

_LIB = Path(__file__).resolve().parent
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))
