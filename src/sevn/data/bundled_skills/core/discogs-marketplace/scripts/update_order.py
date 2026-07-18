#!/usr/bin/env python3
"""Bundled ``discogs-marketplace`` skill — update a marketplace order.

Module: sevn.data.bundled_skills.core.discogs-marketplace.scripts.update_order
Depends: argparse, _discogs_common, _helpers

Exports:
    main — CLI entry; JSON envelope on stdout.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from _discogs_common import write_ok  # noqa: E402
from _helpers import finish, run_write_script, serialize_object  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--order-id", required=True, type=int, help="Discogs order id")
    parser.add_argument("--status", help="New order status")
    parser.add_argument("--shipping", type=float, help="Shipping amount")
    parser.add_argument("--confirm", action="store_true", help="Apply the mutation")
    return parser


def _would_do(args: argparse.Namespace) -> dict[str, Any]:
    changes: dict[str, Any] = {"action": "update_order", "order_id": args.order_id}
    if args.status is not None:
        changes["status"] = args.status
    if args.shipping is not None:
        changes["shipping"] = args.shipping
    return changes


def _worker(args: argparse.Namespace, client: Any) -> tuple[int, dict[str, Any]]:
    order = client.order(args.order_id)
    if args.status is not None:
        order.status = args.status
    if args.shipping is not None:
        order.shipping = args.shipping
    order.save()
    payload = write_ok({"order": serialize_object(order), "updated": _would_do(args)})
    return 0, payload


def main(argv: list[str] | None = None) -> tuple[int, dict[str, Any]]:
    """Run update-order CLI.

    Args:
        argv (list[str] | None, optional): CLI args; defaults to ``sys.argv[1:]``.

    Returns:
        tuple[int, dict[str, Any]]: Exit code and parsed envelope dict.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(main)
        True
    """
    return finish(*run_write_script(_build_parser(), argv, _worker, would_do=_would_do))


if __name__ == "__main__":
    exit_code, _ = main()
    raise SystemExit(exit_code)
