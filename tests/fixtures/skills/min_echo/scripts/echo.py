"""Emit a §3.1 JSON envelope echoing CLI argv (Wave 4 E2E fixture)."""

from __future__ import annotations

import json
import sys

_argv = sys.argv[1:]
echo = " ".join(_argv)
print(json.dumps({"ok": True, "data": {"echo": echo}, "message": None}), flush=True)
