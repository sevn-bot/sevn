#!/usr/bin/env python3
"""Print the buzz-acp managed runtime command for sevn (#72)."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from _buzz_common import emit_json  # noqa: E402


def main() -> int:
    sevn_bin = shutil.which("sevn") or "sevn"
    emit_json(
        {
            "ok": True,
            "data": {
                "runtime_command": f"{sevn_bin} acp",
                "protocol": "acp/stdio",
                "notes": "Register with buzz-acp; configure BUZZ_RELAY_URL and BUZZ_PRIVATE_KEY via secrets chain.",
            },
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
