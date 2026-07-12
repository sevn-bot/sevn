"""Branded terminal assets (ASCII logo, splash animation).

Module: sevn.branding
Depends: sevn.branding.splash

Exports:
    maybe_play_logo_splash — optional trotting-unicorn animation on TTY stdout.
"""

from __future__ import annotations

from sevn.branding.splash import maybe_play_logo_splash

__all__ = ["maybe_play_logo_splash"]
