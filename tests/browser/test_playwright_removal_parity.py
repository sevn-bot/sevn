"""W1 RED — C6 telegram_web replacement + zero-Playwright proof helpers (DP10/DP14)."""

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
_PLAYWRIGHT_IMPORT_RE = re.compile(r"(import|from)\s+playwright")


def _git_grep_playwright_imports(*, under: str) -> list[str]:
    """Return matching lines for Playwright imports under a repo subtree."""
    proc = subprocess.run(
        [
            "git",
            "grep",
            "-nE",
            r"(import|from)\s+playwright",
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
    """DP10: cli/commands/telegram_test.py is removed with the Playwright harness."""
    assert not (_REPO_ROOT / "src" / "sevn" / "cli" / "commands" / "telegram_test.py").exists()


@pytest.mark.xfail(
    reason="green after W8: DP14 zero playwright imports in src/ and tools/", strict=False
)
def test_zero_playwright_imports_across_src_and_tools() -> None:
    """DP14: ``git grep`` for Playwright imports is empty under src/ and tools/."""
    hits = _git_grep_playwright_imports(under="src/") + _git_grep_playwright_imports(under="tools/")
    assert hits == [], "unexpected playwright imports:\n" + "\n".join(hits)


@pytest.mark.xfail(
    reason="green after W8: DP14 intentional playwright survivors none by default", strict=False
)
def test_repo_wide_playwright_grep_clean() -> None:
    """DP14: case-insensitive playwright grep has no survivors outside lock/ignorelocal."""
    proc = subprocess.run(
        [
            "git",
            "grep",
            "-inE",
            "playwright",
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
    # Allow this test file's own contract strings until W8 un-xfails and survivors are gone.
    filtered = [
        ln
        for ln in lines
        if "test_zero_playwright" not in ln and "test_repo_wide_playwright" not in ln
    ]
    assert filtered == [], "playwright survivors remain:\n" + "\n".join(filtered[:40])


def test_playwright_import_helper_detects_pattern() -> None:
    """Deterministic unit check for the DP14 import regex helper itself."""
    assert _PLAYWRIGHT_IMPORT_RE.search("from playwright.async_api import async_playwright")
    assert _PLAYWRIGHT_IMPORT_RE.search("import playwright")
    assert not _PLAYWRIGHT_IMPORT_RE.search("browser tool not playwright-named here")
