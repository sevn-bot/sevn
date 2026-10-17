"""Write the protocol schema and TypeScript method table (D18)."""

from __future__ import annotations

import argparse
from pathlib import Path

from sevn.contracts.export import export_contracts


def main() -> None:
    parser = argparse.ArgumentParser(description="Write protocol schema and methods.ts")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    root = args.root if isinstance(args.root, Path) else Path(str(args.root))
    export_contracts(root)


if __name__ == "__main__":
    main()
