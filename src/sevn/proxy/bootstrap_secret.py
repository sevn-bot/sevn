"""Generate-once proxy shared secret under the operator state root (C1.2 / D37).

Module: sevn.proxy.bootstrap_secret
Depends: contextlib, os, pathlib, secrets, sys

Compose ``sevn-operator-perms`` and host onboarding both land the secret at
``{SEVN_HOME}/.sevn/proxy-shared-secret`` (mode ``0600``, uid ``10001`` when
running as root). Explicit ``SEVN_PROXY_SHARED_SECRET`` still wins at resolve time.

Exports:
    proxy_shared_secret_path — resolve the absolute file path.
    ensure_proxy_shared_secret_file — create once when absent; return the path.
    read_proxy_shared_secret_file — read trimmed contents when the file exists.
    resolve_effective_proxy_shared_secret — env wins, else the generated file.
    main — CLI entry that ensures the file and prints its path.

Examples:
    >>> from sevn.proxy.bootstrap_secret import PROXY_SHARED_SECRET_RELPATH
    >>> PROXY_SHARED_SECRET_RELPATH
    '.sevn/proxy-shared-secret'
"""

from __future__ import annotations

import contextlib
import os
import secrets
import sys
from collections.abc import Mapping
from pathlib import Path

PROXY_SHARED_SECRET_RELPATH = ".sevn/proxy-shared-secret"  # nosec B105 — path segment, not a credential
"""Path under the operator state root (``SEVN_HOME`` / compose ``/operator``)."""

OPERATOR_SECRET_UID = 10001
"""Compose gateway/proxy uid; applied when the ensure helper runs as root."""

_ENV_NAME = "SEVN_PROXY_SHARED_SECRET"
_MIN_SECRET_CHARS = 24


def proxy_shared_secret_path(state_root: Path | str) -> Path:
    """Return ``{state_root}/.sevn/proxy-shared-secret``.

    Args:
        state_root (Path | str): Operator state root (``SEVN_HOME`` / ``/operator``).

    Returns:
        Path: Absolute path to the generate-once secret file.

    Examples:
        >>> proxy_shared_secret_path("/operator").as_posix()
        '/operator/.sevn/proxy-shared-secret'
    """
    return Path(state_root).expanduser().resolve() / PROXY_SHARED_SECRET_RELPATH


def ensure_proxy_shared_secret_file(
    state_root: Path | str,
    *,
    secret: str | None = None,
) -> Path:
    """Create the proxy shared-secret file when absent; never regenerate.

    Args:
        state_root (Path | str): Operator state root (``SEVN_HOME`` / ``/operator``).
        secret (str | None): Optional plaintext to write when the file is absent;
            when omitted, a high-entropy value is generated.

    Returns:
        Path: Path to the existing or newly created secret file.

    Examples:
        >>> import tempfile
        >>> root = Path(tempfile.mkdtemp())
        >>> path = ensure_proxy_shared_secret_file(root)
        >>> path.is_file() and path.name == "proxy-shared-secret"
        True
        >>> ensure_proxy_shared_secret_file(root) == path
        True
    """
    path = proxy_shared_secret_path(state_root)
    if path.is_file():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    value = (secret or "").strip() or secrets.token_urlsafe(32)
    if len(value) < _MIN_SECRET_CHARS:
        msg = f"proxy shared secret must be at least {_MIN_SECRET_CHARS} characters"
        raise ValueError(msg)
    # Write privately then chmod; avoid world-readable temp windows.
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(value)
            handle.write("\n")
    except Exception:
        path.unlink(missing_ok=True)
        raise
    os.chmod(path, 0o600)
    if hasattr(os, "geteuid") and os.geteuid() == 0:  # pragma: no cover — root-only
        with contextlib.suppress(OSError):
            os.chown(path, OPERATOR_SECRET_UID, OPERATOR_SECRET_UID)
    return path


def read_proxy_shared_secret_file(state_root: Path | str) -> str | None:
    """Return the trimmed secret from the generate-once file, if present.

    Args:
        state_root (Path | str): Operator state root.

    Returns:
        str | None: Trimmed secret, or ``None`` when absent/blank/unreadable.

    Examples:
        >>> read_proxy_shared_secret_file("/nonexistent-sevn-state-root") is None
        True
    """
    path = proxy_shared_secret_path(state_root)
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    trimmed = text.strip()
    return trimmed or None


def resolve_effective_proxy_shared_secret(
    *,
    env: Mapping[str, str] | None = None,
    state_root: Path | str | None = None,
) -> str | None:
    """Resolve the proxy shared secret: non-empty env wins, else the file.

    Args:
        env (mapping | None): Env mapping; defaults to ``os.environ``.
        state_root (Path | str | None): Operator state root for the file fallback.
            When ``None`` and ``env`` is omitted (process environ), uses ``SEVN_HOME``
            or ``~/.sevn`` (same default as ``operator_home_dir``). When ``env`` is an
            explicit mapping without ``SEVN_HOME``, the file fallback is skipped so
            callers that pass ``env={}`` do not pick up a host generate-once file.

    Returns:
        str | None: Effective secret, or ``None`` when neither source provides one.

    Examples:
        >>> resolve_effective_proxy_shared_secret(
        ...     env={"SEVN_PROXY_SHARED_SECRET": "  explicit  "},
        ...     state_root="/tmp",
        ... )
        'explicit'
    """
    mapping = os.environ if env is None else env
    raw = mapping.get(_ENV_NAME, "")
    text = raw.strip() if isinstance(raw, str) else ""
    if text:
        return text
    root: Path | str
    if state_root is not None:
        root = state_root
    else:
        home_raw = mapping.get("SEVN_HOME", "")
        home_text = home_raw.strip() if isinstance(home_raw, str) else ""
        if home_text:
            root = home_text
        elif env is None:
            # Match operator_home_dir(): SEVN_HOME defaults to ~/.sevn on host.
            root = Path.home() / ".sevn"
        else:
            return None
    return read_proxy_shared_secret_file(root)


def main(argv: list[str] | None = None) -> int:
    """CLI: ``ensure_proxy_shared_secret.py [state_root]`` → print path, exit 0.

    Args:
        argv (list[str] | None): Optional argv override (excludes program name).

    Returns:
        int: Process exit code.

    Examples:
        >>> import tempfile
        >>> from contextlib import redirect_stdout
        >>> from io import StringIO
        >>> root = tempfile.mkdtemp()
        >>> buf = StringIO()
        >>> with redirect_stdout(buf):
        ...     code = main([root])
        >>> code == 0 and "proxy-shared-secret" in buf.getvalue()
        True
    """
    args = list(sys.argv[1:] if argv is None else argv)
    if args:
        root = Path(args[0])
    else:
        raw = os.environ.get("SEVN_HOME", "").strip()
        root = Path(raw).expanduser().resolve() if raw else (Path.home() / ".sevn")
    path = ensure_proxy_shared_secret_file(root)
    sys.stdout.write(f"{path}\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
