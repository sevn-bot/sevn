#!/usr/bin/env python3
"""Emit Trivy ``--ignorefile`` path from ``security/trivy-allowlist.toml``.

Module: scripts.trivy_ignore_args
Depends: argparse, os, pathlib, sys

Exports:
    main — CLI entry; writes ignore file and prints ``--ignorefile <path>``.

Examples:
    >>> main() in (0, 1)
    True
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ALLOWLIST = ROOT / "security" / "trivy-allowlist.toml"
DEFAULT_OUTPUT = ROOT / "security" / ".trivyignore.generated"


def _allowlist_path() -> Path:
    """Resolve allowlist path from ``TRIVY_ALLOWLIST_PATH`` or the repo default.

    Returns:
        Path: Allowlist TOML path.

    Examples:
        >>> _allowlist_path().name
        'trivy-allowlist.toml'
    """
    override = os.environ.get("TRIVY_ALLOWLIST_PATH", "").strip()
    return Path(override) if override else DEFAULT_ALLOWLIST


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
        print(f"trivy allowlist missing: {path}", file=sys.stderr)
        raise SystemExit(1)
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore[no-redef]

    with path.open("rb") as fh:
        data = tomllib.load(fh)
    rows = data.get("ignore", [])
    if not isinstance(rows, list):
        print(f"trivy allowlist: `ignore` must be a list in {path}", file=sys.stderr)
        raise SystemExit(1)
    out: list[dict[str, str]] = []
    for row in rows:
        if isinstance(row, dict):
            out.append({str(k): str(v) for k, v in row.items()})
    return out


def _image_short_name(image: str) -> str:
    """Normalize allowlist ``image`` to a short GHCR component name.

    Args:
        image (str): Row ``image`` field (``gateway`` or full ref suffix).

    Returns:
        str: Short name used by ``scan_image()`` (e.g. ``gateway``).

    Examples:
        >>> _image_short_name("ghcr.io/sevn-bot/sevn/gateway")
        'gateway'
        >>> _image_short_name("sandbox")
        'sandbox'
    """
    trimmed = image.strip()
    if not trimmed:
        return ""
    if "/" in trimmed:
        return trimmed.rsplit("/", 1)[-1]
    return trimmed


def _row_matches_image(row: dict[str, str], image_filter: str | None) -> bool:
    """Return whether an allowlist row applies to the requested image.

    Args:
        row (dict[str, str]): Parsed allowlist row.
        image_filter (str | None): Short image name from ``scan_image()``, or
            ``None`` to include every row (``make trivy-allowlist-check``).

    Returns:
        bool: True when the row should contribute to the ignore file.

    Examples:
        >>> _row_matches_image({"image": "gateway"}, "gateway")
        True
        >>> _row_matches_image({"image": "gateway"}, "proxy")
        False
    """
    if not image_filter:
        return True
    row_image = row.get("image", "").strip()
    if not row_image:
        return False
    return _image_short_name(row_image) == image_filter.strip()


def _write_ignorefile(path: Path, vuln_ids: list[str]) -> None:
    """Write Trivy ignore entries (one CVE id per line).

    Args:
        path (Path): Output ignore file path.
        vuln_ids (list[str]): Active vulnerability identifiers.

    Examples:
        >>> import tempfile
        >>> out = Path(tempfile.mkdtemp()) / "ignore"
        >>> _write_ignorefile(out, ["CVE-2026-0001"])
        >>> out.read_text(encoding="utf-8")
        'CVE-2026-0001\\n'
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(vuln_ids)
    if body:
        body += "\n"
    path.write_text(body, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """Write the generated ignore file and print ``--ignorefile <path>``.

    Args:
        argv (list[str] | None): Optional CLI argv override for tests.

    Returns:
        int: Exit code (1 when any ``review_by`` date is expired).

    Examples:
        >>> isinstance(main([]), int)
        True
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Generated Trivy ignore file (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--image",
        default="",
        help="Short GHCR image name (e.g. gateway) — emit ignores for that image only",
    )
    args = parser.parse_args(argv)

    today = date.today()  # noqa: DTZ011
    image_filter = args.image.strip() or None
    active_ids: list[str] = []
    expired: list[str] = []
    for row in _parse_allowlist(_allowlist_path()):
        vuln_id = row.get("vuln_id", "").strip()
        review_raw = row.get("review_by", "").strip()
        if not vuln_id:
            continue
        if not _row_matches_image(row, image_filter):
            continue
        if not review_raw:
            print(
                f"trivy allowlist: missing review_by for {vuln_id!r} "
                f"(image={row.get('image', '')!r})",
                file=sys.stderr,
            )
            return 1
        try:
            review_by = date.fromisoformat(review_raw)
        except ValueError:
            print(
                f"trivy allowlist: invalid review_by for {vuln_id!r}: {review_raw}",
                file=sys.stderr,
            )
            return 1
        if review_by < today:
            expired.append(f"{vuln_id} (review_by {review_raw})")
            continue
        active_ids.append(vuln_id)
    if expired:
        print("trivy allowlist expired — re-evaluate or extend review_by:", file=sys.stderr)
        for item in expired:
            print(f"  - {item}", file=sys.stderr)
        return 1

    output = args.output
    _write_ignorefile(output, active_ids)
    sys.stdout.write(f"--ignorefile {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
