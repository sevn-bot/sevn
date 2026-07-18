"""Re-export shared Discogs runtime helpers from ``discogs-shared``.

Module: sevn.data.bundled_skills.core.discogs-database.scripts._discogs_common
Depends: importlib.util, pathlib

Exports:
    build_client, write_ok, write_err, paginate, require_confirm, map_discogs_error, emit_json
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

_SHARED_RUNTIME = (
    Path(__file__).resolve().parents[2] / "discogs-shared" / "scripts" / "_discogs_runtime.py"
)


def _load_runtime() -> Any:
    spec = importlib.util.spec_from_file_location("_discogs_runtime", _SHARED_RUNTIME)
    assert spec is not None
    loader = spec.loader
    assert loader is not None
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


_runtime = _load_runtime()

build_client = _runtime.build_client
write_ok = _runtime.write_ok
write_err = _runtime.write_err
paginate = _runtime.paginate
require_confirm = _runtime.require_confirm
map_discogs_error = _runtime.map_discogs_error
emit_json = _runtime.emit_json

__all__ = [
    "build_client",
    "emit_json",
    "map_discogs_error",
    "paginate",
    "require_confirm",
    "write_err",
    "write_ok",
]
