"""Batch B W7 RED — non-root images + Chromium sandbox (#145; green after W8).

Contracts (plan D12): ``docker/Dockerfile.gateway``, ``docker/Dockerfile.proxy`` and
``docker/Dockerfile.gateway.browser`` create a ``sevn`` account at uid ``10001`` and end
with ``USER sevn`` before ``CMD``; the browser image no longer disables the Chromium
sandbox. ``docker/Dockerfile.gateway.gui`` is out of scope — its supervised programs
already run as a non-root user.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOCKER_DIR = _REPO_ROOT / "docker"
_HARDENED_IMAGES = (
    "Dockerfile.gateway",
    "Dockerfile.proxy",
    "Dockerfile.gateway.browser",
)
_NON_ROOT_USER = "sevn"
_NON_ROOT_UID = "10001"
_USER_RE = re.compile(r"^\s*USER\s+(?P<user>\S+)", re.MULTILINE)
_CMD_RE = re.compile(r"^\s*CMD\s", re.MULTILINE)
_USER_CREATE_RE = re.compile(r"\b(useradd|adduser)\b")


def _dockerfile_text(name: str) -> str:
    return (_DOCKER_DIR / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("dockerfile", _HARDENED_IMAGES)
def test_hardened_dockerfile_present(dockerfile: str) -> None:
    """Baseline: the three Gate B images exist and are readable."""
    assert (_DOCKER_DIR / dockerfile).is_file()


@pytest.mark.xfail(reason="green after W8: USER sevn in gateway/proxy/browser images", strict=False)
@pytest.mark.parametrize("dockerfile", _HARDENED_IMAGES)
def test_dockerfile_switches_to_non_root_user(dockerfile: str) -> None:
    """Each Gate B image ends on a non-root ``USER`` instruction."""
    users = _USER_RE.findall(_dockerfile_text(dockerfile))
    assert users, f"{dockerfile} declares no USER instruction"
    assert users[-1] == _NON_ROOT_USER, f"{dockerfile} last USER is {users[-1]!r}"


@pytest.mark.xfail(reason="green after W8: uid 10001 sevn account created", strict=False)
@pytest.mark.parametrize("dockerfile", _HARDENED_IMAGES)
def test_dockerfile_creates_non_root_account_at_pinned_uid(dockerfile: str) -> None:
    """The runtime account is created explicitly at uid ``10001`` (stable bind-mount owner)."""
    text = _dockerfile_text(dockerfile)
    assert _USER_CREATE_RE.search(text), f"{dockerfile} never creates an account"
    assert _NON_ROOT_UID in text, f"{dockerfile} does not pin uid {_NON_ROOT_UID}"


@pytest.mark.xfail(reason="green after W8: USER switch precedes CMD", strict=False)
@pytest.mark.parametrize("dockerfile", _HARDENED_IMAGES)
def test_user_switch_precedes_cmd(dockerfile: str) -> None:
    """The drop to ``sevn`` happens before the entrypoint so the process is never root."""
    text = _dockerfile_text(dockerfile)
    user_matches = list(_USER_RE.finditer(text))
    cmd_match = _CMD_RE.search(text)
    assert user_matches, f"{dockerfile} declares no USER instruction"
    assert cmd_match is not None, f"{dockerfile} declares no CMD instruction"
    assert user_matches[-1].start() < cmd_match.start()


@pytest.mark.xfail(reason="green after W8: browser image keeps the Chromium sandbox", strict=False)
def test_browser_image_does_not_disable_chromium_sandbox() -> None:
    """``--no-sandbox`` is removed once the browser image runs as a non-root uid."""
    text = _dockerfile_text("Dockerfile.gateway.browser")
    assert "--no-sandbox" not in text


def test_browser_image_keeps_brave_engine_pinned() -> None:
    """Regression guard: hardening must not drop the Brave CDP engine wiring."""
    text = _dockerfile_text("Dockerfile.gateway.browser")
    assert "SEVN_CHROME_EXECUTABLE=/usr/bin/brave-browser" in text
    assert "SEVN_BROWSER_ENGINE=brave" in text
