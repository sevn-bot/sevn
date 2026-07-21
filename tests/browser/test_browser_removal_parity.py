"""W1 RED — C6 telegram_web replacement + zero-browser-driver proof helpers (DP10/DP14)."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from sevn.browser.cdp import CDPConnection, CDPSession
from sevn.browser.element import Dom
from sevn.browser.page import Page
from sevn.browser.recipes.telegram_web import TelegramWeb

_REPO_ROOT = Path(__file__).resolve().parents[2]
# Split so repo-wide DP14 grep stays clean while still matching the real package name.
_DRIVER = "play" + "wright"
_IMPORT_RE = re.compile(rf"(import|from)\s+{_DRIVER}")

# Intentional survivors (W8 note): prior-wave CHANGELOG bullets must not be rewritten.
_INTENTIONAL_SURVIVOR_PREFIXES: tuple[str, ...] = ("CHANGELOG.md:",)


def _git_grep_driver_imports(*, under: str) -> list[str]:
    """Return matching lines for retired browser-driver imports under a repo subtree."""
    proc = subprocess.run(
        [
            "git",
            "grep",
            "-nE",
            rf"(import|from)\s+{_DRIVER}",
            "--",
            under,
        ],
        cwd=_REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode not in (0, 1):
        msg = f"git grep failed ({proc.returncode}): {proc.stderr}"
        raise RuntimeError(msg)
    return [ln for ln in proc.stdout.splitlines() if ln.strip()]


@pytest.mark.asyncio
async def test_telegram_web_replacement_send_receive_invocable(fake_cdp: object) -> None:
    """DP10 / C6: browser telegram_web recipe exposes send/read/reply for E2E replacement."""
    fake_cdp.set_result("Runtime.evaluate", {"result": {"value": True}})  # type: ignore[attr-defined]
    fake_cdp.set_result("Page.navigate", {"frameId": "f1"})  # type: ignore[attr-defined]
    conn = await CDPConnection.connect(fake_cdp.ws_url)  # type: ignore[attr-defined]
    session = CDPSession(conn)
    recipe = TelegramWeb(Page(session), Dom(session))
    try:
        assert callable(recipe.send)
        assert callable(recipe.read)
        assert callable(recipe.reply)
        assert callable(recipe.list_chats)
        # Shape probe: send requires login; with logged_in=True marker it should attempt composer.
        out = await recipe.list_chats(limit=5)
        assert isinstance(out, dict)
    finally:
        await conn.close()


def test_telegram_tester_directory_removed() -> None:
    """DP10: tools/telegram-tester is gone after browser telegram_web replacement lands."""
    assert not (_REPO_ROOT / "tools" / "telegram-tester").exists()


def test_telegram_test_cli_module_removed() -> None:
    """DP10: cli/commands/telegram_test.py is removed with the host E2E harness."""
    assert not (_REPO_ROOT / "src" / "sevn" / "cli" / "commands" / "telegram_test.py").exists()


def test_zero_driver_imports_across_src_and_tools() -> None:
    """DP14: ``git grep`` for retired browser-driver imports is empty under src/ and tools/."""
    hits = _git_grep_driver_imports(under="src/") + _git_grep_driver_imports(under="tools/")
    assert hits == [], "unexpected driver imports:\n" + "\n".join(hits)


def test_repo_wide_driver_grep_clean() -> None:
    """DP14: case-insensitive driver-name grep has no unexpected survivors."""
    proc = subprocess.run(
        [
            "git",
            "grep",
            "-inE",
            _DRIVER,
            "--",
            ":!.ignorelocal",
            ":!*.lock",
            ":!docs/test-plans/*",
        ],
        cwd=_REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode not in (0, 1):
        msg = f"git grep failed ({proc.returncode}): {proc.stderr}"
        raise RuntimeError(msg)
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    filtered = [
        ln
        for ln in lines
        if not any(ln.startswith(prefix) for prefix in _INTENTIONAL_SURVIVOR_PREFIXES)
    ]
    assert filtered == [], "unexpected survivors remain:\n" + "\n".join(filtered[:40])


def test_driver_import_helper_detects_pattern() -> None:
    """Deterministic unit check for the DP14 import regex helper itself."""
    assert _IMPORT_RE.search(f"from {_DRIVER}.async_api import async_{_DRIVER}")
    assert _IMPORT_RE.search(f"import {_DRIVER}")
    assert not _IMPORT_RE.search("browser tool not driver-named here")


@pytest.mark.asyncio
@pytest.mark.xfail(
    reason="green after W13: telegram_checks assert_send_receive upgrade", strict=False
)
async def test_telegram_web_replacement_send_receive_via_telegram_checks() -> None:
    """PR #47: upgrade callable-only probe to drive ``assert_send_receive``."""
    from unittest.mock import AsyncMock, MagicMock

    from sevn.browser.recipes import telegram_checks

    tg = MagicMock()
    tg.send = AsyncMock(return_value=None)
    tg.read = AsyncMock(return_value="bot says ping-xyz")
    out = await telegram_checks.assert_send_receive(tg, chat="Saved Messages", text="ping-xyz")
    assert isinstance(out, dict)
    assert out.get("sent") is True
    assert "ping-xyz" in str(out.get("text", ""))
