"""Docker compose helpers for local Telegram E2E runs.

Module: sevn_telegram_tester.compose
Depends: subprocess, urllib.request

Exports:
    apply_local_e2e_compose — recreate gateway with E2E echo override.
    wait_for_gateway_ready — poll ``GET /ready`` on the local gateway port.
"""

from __future__ import annotations

import subprocess  # nosec B404
import time
import urllib.error
import urllib.request
from pathlib import Path

from loguru import logger

from sevn_telegram_tester.config import TelegramTesterSettings, package_root

COMPOSE_OVERRIDE = package_root / "compose.override.e2e.yml"


def repo_root() -> Path:
    """Return the sevn.bot repository root (parent of ``tools/telegram-tester``).

    Returns:
        Repository root path.

    Examples:
        >>> root = repo_root()
        >>> (root / "docker/docker-compose.yml").is_file()
        True
    """
    return package_root.parent.parent


def apply_local_e2e_compose(settings: TelegramTesterSettings) -> None:
    """Apply ``compose.override.e2e.yml`` and recreate ``sevn-gateway``.

    Args:
        settings: Tester settings (port used for readiness after recreate).

    Raises:
        RuntimeError: When ``docker compose`` exits non-zero.

    Examples:
        >>> from sevn_telegram_tester.config import TelegramTesterSettings
        >>> apply_local_e2e_compose  # doctest: +SKIP
    """
    root = repo_root()
    base = root / "docker/docker-compose.yml"
    if not base.is_file():
        msg = f"missing compose file: {base}"
        raise RuntimeError(msg)
    if not COMPOSE_OVERRIDE.is_file():
        msg = f"missing E2E override: {COMPOSE_OVERRIDE}"
        raise RuntimeError(msg)
    cmd = [
        "docker",
        "compose",
        "-f",
        str(base),
        "-f",
        str(COMPOSE_OVERRIDE),
        "up",
        "-d",
        "--force-recreate",
        "sevn-gateway",
    ]
    logger.info("applying E2E compose override: {}", " ".join(cmd))
    completed = subprocess.run(cmd, cwd=root, check=False, capture_output=True, text=True)  # nosec B603
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        msg = f"docker compose failed ({completed.returncode}): {detail}"
        raise RuntimeError(msg)
    wait_for_gateway_ready(settings)


def wait_for_gateway_ready(
    settings: TelegramTesterSettings,
    *,
    timeout_s: float = 120.0,
    interval_s: float = 2.0,
) -> None:
    """Poll the gateway ``/ready`` endpoint until success or timeout.

    Args:
        settings: Tester settings supplying ``gateway_base_url``.
        timeout_s: Maximum wait in seconds.
        interval_s: Sleep between attempts.

    Raises:
        TimeoutError: When the gateway never becomes ready.

    Examples:
        >>> from sevn_telegram_tester.config import TelegramTesterSettings
        >>> wait_for_gateway_ready  # doctest: +SKIP
    """
    url = f"{settings.gateway_base_url}/ready"
    deadline = time.monotonic() + timeout_s
    last_error: str | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:  # nosec B310
                if 200 <= resp.status < 300:
                    logger.info("gateway ready at {}", url)
                    return
                last_error = f"HTTP {resp.status}"
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = str(exc)
        time.sleep(interval_s)
    msg = f"gateway not ready at {url} within {timeout_s}s: {last_error}"
    raise TimeoutError(msg)
