#!/usr/bin/env python3
"""Emit ``pip-audit --ignore-vuln`` flags from ``security/pip-audit-allowlist.toml``.

Module: scripts.pip_audit_ignore_args
Depends: pathlib, sys

Exports:
    main — CLI entry; prints active ``--ignore-vuln`` flags.

Examples:
    >>> main() in (0, 1)
    True
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST = ROOT / "security" / "pip-audit-allowlist.toml"


def _parse_allowlist(path: Path) -> list[dict[str, str]]:
    """Load ``[[ignore]]`` rows from the allowlist TOML file.

    Args:
        path (Path): Allowlist path.

    Returns:
        list[dict[str, str]]: Ignore rows with string values.

    Raises:
        SystemExit: When the file is missing or TOML is invalid.

    Examples:
        >>> import tempfile
        >>> p = Path(tempfile.mkdtemp()) / "a.toml"
        >>> _ = p.write_text("ignore = []\\n", encoding="utf-8")
        >>> _parse_allowlist(p)
        []
    """
    if not path.is_file():
        print(f"pip-audit allowlist missing: {path}", file=sys.stderr)
        raise SystemExit(1)
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore[no-redef]

    with path.open("rb") as fh:
        data = tomllib.load(fh)
    rows = data.get("ignore", [])
    if not isinstance(rows, list):
        print(f"pip-audit allowlist: `ignore` must be a list in {path}", file=sys.stderr)
        raise SystemExit(1)
    out: list[dict[str, str]] = []
    for row in rows:
        if isinstance(row, dict):
            out.append({str(k): str(v) for k, v in row.items()})
    return out


def main() -> int:
    """Print ``--ignore-vuln <id>`` pairs for active allowlist entries.

    Returns:
        int: Exit code (1 when any ``review_by`` date is expired).

    Examples:
        >>> isinstance(main(), int)
        True
    """
    today = date.today()  # noqa: DTZ011
    flags: list[str] = []
    expired: list[str] = []
    for row in _parse_allowlist(ALLOWLIST):
        vuln_id = row.get("vuln_id", "").strip()
        review_raw = row.get("review_by", "").strip()
        if not vuln_id:
            continue
        if review_raw:
            try:
                review_by = date.fromisoformat(review_raw)
            except ValueError:
                print(
                    f"pip-audit allowlist: invalid review_by for {vuln_id!r}: {review_raw}",
                    file=sys.stderr,
                )
                return 1
            if review_by < today:
                expired.append(f"{vuln_id} (review_by {review_raw})")
                continue
        flags.extend(["--ignore-vuln", vuln_id])
    if expired:
        print("pip-audit allowlist expired — re-evaluate or extend review_by:", file=sys.stderr)
        for item in expired:
            print(f"  - {item}", file=sys.stderr)
        return 1
    sys.stdout.write(" ".join(flags))
    if flags:
        sys.stdout.write(" ")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
