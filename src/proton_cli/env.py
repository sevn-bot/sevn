"""Profile-scoped environment variable resolution."""

from __future__ import annotations

import os


def profile_env_segment(profile: str) -> str:
    """Normalize profile name for env vars: ``work`` → ``WORK``, ``my-work`` → ``MY_WORK``."""
    out: list[str] = []
    for ch in profile.upper():
        if ("A" <= ch <= "Z") or ("0" <= ch <= "9"):
            out.append(ch)
        else:
            out.append("_")
    return "".join(out)


def env_for_profile(profile: str, base: str) -> str:
    """Resolve ``PROTON_<PROFILE>_<base>`` then fall back to ``PROTON_<base>``."""
    seg = profile_env_segment(profile)
    if seg:
        scoped = os.environ.get(f"PROTON_{seg}_{base}", "")
        if scoped:
            return scoped
    return os.environ.get(f"PROTON_{base}", "")


def first_non_empty(*values: str) -> str:
    for v in values:
        if v:
            return v
    return ""
