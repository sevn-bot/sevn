"""Optional branded logo splash for interactive CLI entry points.

Module: sevn.branding.splash
Depends: os, sys, sevn.branding.unicorn_trot

Exports:
    logo_splash_enabled — whether splash may run on this stdout.
    maybe_play_logo_splash — play the trotting-unicorn animation when enabled.
"""

from __future__ import annotations

import os
import sys

from sevn.branding.unicorn_trot import play_unicorn_trot


def logo_splash_enabled() -> bool:
    """Return whether the logo splash may run on the current stdout.

    Returns:
        bool: ``True`` when stdout is a TTY and splash is not opted out.

    Examples:
        >>> isinstance(logo_splash_enabled(), bool)
        True
    """
    flag = os.environ.get("SEVN_NO_LOGO_SPLASH", "").strip().lower()
    if flag in {"1", "true", "yes", "on"}:
        return False
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def maybe_play_logo_splash(
    *,
    fps: float = 18.0,
    step: int = 2,
) -> None:
    """Play the trotting-unicorn splash when enabled.

    Failures are swallowed so cosmetic splash never blocks operator commands.

    Args:
        fps (float): Animation frames per second.
        step (int): Columns advanced per frame (higher is faster).

    Examples:
        >>> maybe_play_logo_splash()  # doctest: +SKIP
    """
    if not logo_splash_enabled():
        return
    try:
        play_unicorn_trot(fps=fps, step=step)
    except Exception:
        return


__all__ = ["logo_splash_enabled", "maybe_play_logo_splash"]
