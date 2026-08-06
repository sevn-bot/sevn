#!/usr/bin/env python3
"""Preflight operator secrets before ``make compose-up`` (C1.3 / D38).

Module: scripts.check_compose_operator_secrets
Depends: os, pathlib, sys

Rejects empty, placeholder (``change-me``), and below-minimum-length values for
``SEVN_PROXY_SHARED_SECRET``, ``SEVN_GATEWAY_TOKEN``, and ``SEVN_SECRETS_PASSPHRASE``.

**W5.3 / generate-once interaction:** when ``allow_absent_proxy_shared_secret`` is
true (CLI / ``compose-up`` default), an unset or blank ``SEVN_PROXY_SHARED_SECRET``
is skipped — Compose ``sevn-operator-perms`` generates
``/operator/.sevn/proxy-shared-secret`` on first boot. An *explicit* low-quality
value still fails. Gateway token and secrets passphrase are always required.

Exports:
    load_env_file — parse a dotenv-style file into a string map.
    validate_operator_secrets — raise ``ValueError`` when any checked value fails.
    main — CLI entry (``.env`` + process env; ``--self-check`` for CI).

Constants (not Exports): ``OPERATOR_SECRET_VARS``, ``MIN_SECRET_CHARS``,
``PLACEHOLDER_VALUES``.
Examples:
    >>> validate_operator_secrets(
    ...     {
    ...         "SEVN_PROXY_SHARED_SECRET": "high-entropy-proxy-secret-value-32b",
    ...         "SEVN_GATEWAY_TOKEN": "high-entropy-gateway-token-value-32b",
    ...         "SEVN_SECRETS_PASSPHRASE": "high-entropy-secrets-passphrase-32b",
    ...     }
    ... ) is None
    True
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

OPERATOR_SECRET_VARS: tuple[str, ...] = (
    "SEVN_PROXY_SHARED_SECRET",
    "SEVN_GATEWAY_TOKEN",
    "SEVN_SECRETS_PASSPHRASE",
)
"""Env vars covered by the compose operator-secret preflight (D38)."""

MIN_SECRET_CHARS = 24
"""Minimum character length; aligns with ``sevn.proxy.bootstrap_secret``."""

PLACEHOLDER_VALUES: frozenset[str] = frozenset(
    {
        "change-me",
        "changeme",
        "password",
        "secret",
        "replace-me",
        "todo",
        "placeholder",
    }
)
"""Case-insensitive placeholder blacklist (``change-me`` is the shipped default)."""

_PROXY_SHARED_SECRET = "SEVN_PROXY_SHARED_SECRET"
_REPO_ROOT = Path(__file__).resolve().parents[1]


def load_env_file(path: Path | str) -> dict[str, str]:
    """Parse a dotenv-style file into a ``key -> value`` map (no expansion).

    Args:
        path (Path | str): Path to ``.env`` (or similar).

    Returns:
        dict[str, str]: Assignments found; missing file yields ``{}``.

    Examples:
        >>> load_env_file("/nonexistent-sevn-env-file")
        {}
    """
    file_path = Path(path)
    if not file_path.is_file():
        return {}
    result: dict[str, str] = {}
    for raw_line in file_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        name = key.strip()
        if not name:
            continue
        text = value.strip()
        if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
            text = text[1:-1]
        result[name] = text
    return result


def validate_operator_secrets(
    env: Mapping[str, str],
    *,
    allow_absent_proxy_shared_secret: bool = False,
) -> None:
    """Validate operator secret env values; raise ``ValueError`` on failure.

    Args:
        env (Mapping[str, str]): Env map (typically ``.env`` merged with process env).
        allow_absent_proxy_shared_secret (bool): When ``True``, skip
            ``SEVN_PROXY_SHARED_SECRET`` if unset/blank so Compose generate-once
            can satisfy it (W5.3). Explicit bad values still fail.

    Raises:
        ValueError: When any required variable is empty, a placeholder, or too short.

    Examples:
        >>> env = {
        ...     "SEVN_PROXY_SHARED_SECRET": "high-entropy-proxy-secret-value-32b",
        ...     "SEVN_GATEWAY_TOKEN": "high-entropy-gateway-token-value-32b",
        ...     "SEVN_SECRETS_PASSPHRASE": "high-entropy-secrets-passphrase-32b",
        ... }
        >>> validate_operator_secrets(env) is None
        True
    """
    for name in OPERATOR_SECRET_VARS:
        raw = env.get(name, "")
        value = raw.strip() if isinstance(raw, str) else ""
        if name == _PROXY_SHARED_SECRET and allow_absent_proxy_shared_secret and not value:
            continue
        if not value:
            msg = (
                f"{name} is empty — set a high-entropy value before compose-up "
                f"(minimum {MIN_SECRET_CHARS} characters; not a placeholder)"
            )
            raise ValueError(msg)
        if value.casefold() in PLACEHOLDER_VALUES:
            msg = (
                f"{name} is a known placeholder — replace "
                f"`change-me` / similar before starting services"
            )
            raise ValueError(msg)
        if len(value) < MIN_SECRET_CHARS:
            msg = f"{name} is below the minimum entropy length ({len(value)} < {MIN_SECRET_CHARS})"
            raise ValueError(msg)


def _self_check() -> int:
    """Exercise reject/accept paths without requiring a real operator ``.env``.

    Returns:
        int: ``0`` when reject/accept fixtures behave; ``1`` on logic drift.

    Examples:
        >>> _self_check() in (0, 1)
        True
    """
    good = {
        "SEVN_PROXY_SHARED_SECRET": "high-entropy-proxy-secret-value-32b",
        "SEVN_GATEWAY_TOKEN": "high-entropy-gateway-token-value-32b",
        "SEVN_SECRETS_PASSPHRASE": "high-entropy-secrets-passphrase-32b",
    }
    validate_operator_secrets(good)
    validate_operator_secrets(
        {**good, _PROXY_SHARED_SECRET: ""},
        allow_absent_proxy_shared_secret=True,
    )
    for name in OPERATOR_SECRET_VARS:
        for bad in ("", "   ", "change-me", "CHANGE-ME", "short"):
            trial = dict(good)
            trial[name] = bad
            try:
                validate_operator_secrets(trial)
            except ValueError:
                continue
            # Fixed message only: interpolating OPERATOR_SECRET_VARS names (or ``bad``)
            # taints prints for CodeQL py/clear-text-logging-sensitive-data.
            print(
                "error: self-check expected rejection for an operator secret",
                file=sys.stderr,
            )
            return 1
    print("check_compose_operator_secrets: self-check ok")
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI: validate ``.env`` + process env, or run ``--self-check``.

    Args:
        argv (list[str] | None): Argument vector; defaults to ``sys.argv[1:]``.

    Returns:
        int: ``0`` on success; ``1`` on validation failure.

    Examples:
        >>> main(["--self-check"]) in (0, 1)
        True
    """
    args = list(sys.argv[1:] if argv is None else argv)
    if "--self-check" in args:
        return _self_check()
    env_path = Path(os.environ.get("SEVN_COMPOSE_ENV_FILE", str(_REPO_ROOT / ".env")))
    merged: dict[str, str] = {**load_env_file(env_path), **dict(os.environ)}
    try:
        validate_operator_secrets(merged, allow_absent_proxy_shared_secret=True)
    except ValueError as exc:
        print(f"error: operator secret preflight failed: {exc}", file=sys.stderr)
        print(
            "hint: copy .env.example → .env and replace change-me / short values; "
            "leave SEVN_PROXY_SHARED_SECRET unset to use Compose generate-once",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
