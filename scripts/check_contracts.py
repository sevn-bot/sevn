"""Fail when generated contracts drift from the tree (D18, D21)."""

from __future__ import annotations

import argparse
import filecmp
import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

from sevn.contracts.export import export_contracts

_ROOT = Path(__file__).resolve().parents[1]
_JSON2TS = (
    "--unreachableDefinitions",
    "--unknownAny",
    "--no-additionalProperties",
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check or write generated protocol.ts")
    parser.add_argument(
        "--write-ts",
        action="store_true",
        help="Write web/src/contracts/protocol.ts from the schema on disk",
    )
    args = parser.parse_args()
    if args.write_ts:
        schema = _ROOT / "contracts" / "protocol.schema.json"
        dest = _ROOT / "web" / "src" / "contracts" / "protocol.ts"
        _write_protocol_ts(schema, dest)
        return 0
    return _check()


def _check() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        export_contracts(root)
        vectors = root / "contracts" / "vectors" / "frames.json"
        vectors.parent.mkdir(parents=True, exist_ok=True)
        vectors.write_text(_vectors_text(), encoding="utf-8")
        schema = root / "contracts" / "protocol.schema.json"
        protocol = root / "web" / "src" / "contracts" / "protocol.ts"
        _write_protocol_ts(schema, protocol)
        pairs = (
            ("contracts/protocol.schema.json", schema),
            ("web/src/contracts/methods.ts", root / "web" / "src" / "contracts" / "methods.ts"),
            ("web/src/contracts/protocol.ts", protocol),
            ("contracts/vectors/frames.json", vectors),
        )
        drifted = False
        for relative, generated in pairs:
            live = _ROOT / relative
            if not live.is_file() or not filecmp.cmp(live, generated, shallow=False):
                sys.stderr.write(f"contracts drift: {relative}\n")
                drifted = True
        return 1 if drifted else 0


def _vectors_text() -> str:
    path = Path(__file__).resolve().parent / "gen_frame_vectors.py"
    spec = importlib.util.spec_from_file_location("gen_frame_vectors", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load gen_frame_vectors")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    text = module.render_vectors()
    if not isinstance(text, str):
        raise RuntimeError("render_vectors must return str")
    return text


def _write_protocol_ts(schema: Path, dest: Path) -> None:
    binary = _ROOT / "web" / "node_modules" / ".bin" / "json2ts"
    dest.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(  # noqa: S603
        [
            str(binary),
            "--input",
            str(schema),
            "--output",
            str(dest),
            *_JSON2TS,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        sys.stderr.write(result.stderr or result.stdout)
        raise SystemExit(result.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
