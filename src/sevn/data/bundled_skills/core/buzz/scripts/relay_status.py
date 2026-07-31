#!/usr/bin/env python3
"""Probe Buzz relay health (#72)."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from _buzz_common import emit_json, load_identity  # noqa: E402


def main() -> int:
    identity = load_identity()
    if identity is None:
        emit_json(
            {
                "ok": False,
                "error": {"code": "MISSING_IDENTITY", "message": "Buzz credentials not configured"},
            }
        )
        return 1
    url = f"{identity.relay_url}/health"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {identity.private_key}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        emit_json({"ok": False, "error": {"code": "HTTP_ERROR", "message": str(exc.code)}})
        return 1
    except urllib.error.URLError as exc:
        emit_json({"ok": False, "error": {"code": "NETWORK_ERROR", "message": str(exc.reason)}})
        return 1
    try:
        data = json.loads(body) if body.strip() else {"status": "ok"}
    except json.JSONDecodeError:
        data = {"status": body[:200]}
    emit_json({"ok": True, "data": {"relay_url": identity.relay_url, "health": data}})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
