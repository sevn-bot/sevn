"""Unit tests for browser tab CRUD (Wave W3T)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from sevn.skills.browser_session import (
    BrowserSessionRegistry,
    TabOperationError,
    TabSessionView,
    _match_cdp_target_for_page,
    activate_tab,
    close_tab,
    list_tabs,
    open_tab,
    page_target_id,
    persist_active_target_id,
    pick_work_page,
    read_registry,
    write_registry,
)


class _FakePage:
    def __init__(
        self,
        guid: str,
        *,
        url: str = "https://example.com/",
        title: str = "Example",
        context: _FakeContext | None = None,
    ) -> None:
        self._guid = guid
        self.url = url
        self._title = title
        self.closed = False
        self._context = context

    async def title(self) -> str:
        return self._title

    async def goto(self, url: str, **kwargs: Any) -> None:
        self.url = url

    async def bring_to_front(self) -> None:
        return None

    async def wait_for_load_state(self, _state: str, **kwargs: Any) -> None:
        return None

    async def close(self) -> None:
        self.closed = True
        if self._context is not None and self in self._context.pages:
            self._context.pages.remove(self)


class _FakeContext:
    def __init__(self, pages: list[_FakePage] | None = None) -> None:
        self.pages: list[_FakePage] = []
        for page in pages or []:
            page._context = self
            self.pages.append(page)

    async def new_page(self) -> _FakePage:
        page = _FakePage(f"page-{len(self.pages) + 1}", context=self)
        self.pages.append(page)
        return page


class _FakeBrowser:
    def __init__(self, pages: list[_FakePage]) -> None:
        self.contexts = [_FakeContext(pages)]


@pytest.mark.asyncio
async def test_open_tab_sets_active(tmp_path: Path) -> None:
    """open_tab activates a new tab and persists active_target_id in the registry."""
    view = TabSessionView(context=_FakeContext([_FakePage("tab-1", url="https://one.example/")]))
    write_registry(
        tmp_path,
        "s1",
        BrowserSessionRegistry(
            pid=1,
            cdp_url="http://127.0.0.1:1",
            cdp_port=1,
            profile_dir=str(tmp_path / "p"),
            headless=False,
            spawned_by_sevn=True,
            last_used_at=datetime.now(tz=UTC).isoformat(),
        ),
    )
    result = await open_tab(
        view,
        "https://two.example/",
        activate=True,
        content_root=tmp_path,
        session_id="s1",
    )
    assert result["active"] is True
    assert result["target_id"] == "page-2"
    row = read_registry(tmp_path, "s1")
    assert row is not None
    assert row.active_target_id == "page-2"


@pytest.mark.asyncio
async def test_close_tab_refuses_last() -> None:
    """close_tab raises LAST_TAB when only one tab remains."""
    page = _FakePage("only-tab")
    view = TabSessionView(context=_FakeContext([page]))
    with pytest.raises(TabOperationError) as exc_info:
        await close_tab(view, "only-tab")
    assert exc_info.value.code == "LAST_TAB"


@pytest.mark.asyncio
async def test_activate_tab_updates_registry(tmp_path: Path) -> None:
    """activate_tab bring_to_front and writes active_target_id to the registry."""
    view = TabSessionView(
        context=_FakeContext(
            [
                _FakePage("tab-a", url="https://a.example/"),
                _FakePage("tab-b", url="https://b.example/"),
            ],
        ),
    )
    write_registry(
        tmp_path,
        "s1",
        BrowserSessionRegistry(
            pid=1,
            cdp_url="http://127.0.0.1:1",
            cdp_port=1,
            profile_dir=str(tmp_path / "p"),
            headless=False,
            spawned_by_sevn=True,
            last_used_at=datetime.now(tz=UTC).isoformat(),
            active_target_id="tab-a",
        ),
    )
    result = await activate_tab(
        view,
        "tab-b",
        content_root=tmp_path,
        session_id="s1",
    )
    assert result["active"] is True
    assert result["target_id"] == "tab-b"
    row = read_registry(tmp_path, "s1")
    assert row is not None
    assert row.active_target_id == "tab-b"


@pytest.mark.asyncio
async def test_pick_work_page_prefers_active_target() -> None:
    """pick_work_page returns the registry active tab before recency heuristics."""
    page1 = _FakePage("older", url="https://older.example/")
    page2 = _FakePage("active-tab", url="about:blank")
    browser = _FakeBrowser([page1, page2])
    chosen = await pick_work_page(browser, active_target_id="active-tab")
    assert page_target_id(chosen) == "active-tab"


@pytest.mark.asyncio
async def test_list_tabs_marks_active(tmp_path: Path) -> None:
    """list_tabs returns target_id rows and flags the registry active tab."""
    view = TabSessionView(
        context=_FakeContext(
            [
                _FakePage("tab-1", url="https://one.example/", title="One"),
                _FakePage("tab-2", url="https://two.example/", title="Two"),
            ],
        ),
    )
    payload = await list_tabs(view, active_target_id="tab-2")
    tabs = payload["tabs"]
    assert isinstance(tabs, list)
    assert payload["count"] == 2
    assert payload["page_count"] == 2
    active_rows = [row for row in tabs if row.get("active") is True]
    assert len(active_rows) == 1
    assert active_rows[0]["target_id"] == "tab-2"


@pytest.mark.asyncio
async def test_list_tabs_reports_untrackable_pages() -> None:
    """When pages lack GUIDs and CDP fallback fails, report untrackable_count."""
    page = _FakePage("", url="https://orphan.example/")
    view = TabSessionView(context=_FakeContext([page]), cdp_url="http://127.0.0.1:1")
    payload = await list_tabs(view)
    assert payload["count"] == 0
    assert payload["page_count"] == 1
    assert payload["untrackable_count"] == 1
    assert "note" in payload


def test_page_target_id_falls_back_to_cdp_target() -> None:
    """CDP /json/list ids are used when Playwright pages expose no _guid."""
    page = _FakePage("", url="https://example.com/path")
    targets = [{"id": "CDP-TARGET-1", "url": "https://example.com/path", "title": ""}]
    assert page_target_id(page, cdp_targets=targets) == "CDP-TARGET-1"
    assert _match_cdp_target_for_page(page, targets) == "CDP-TARGET-1"


def test_persist_active_target_id(tmp_path: Path) -> None:
    """persist_active_target_id updates only the active_target_id field."""
    write_registry(
        tmp_path,
        "s1",
        BrowserSessionRegistry(
            pid=9,
            cdp_url="http://127.0.0.1:9",
            cdp_port=9,
            profile_dir="/p",
            headless=False,
            spawned_by_sevn=True,
            last_used_at=datetime.now(tz=UTC).isoformat(),
        ),
    )
    persist_active_target_id(tmp_path, "s1", "focus-1")
    row = read_registry(tmp_path, "s1")
    assert row is not None
    assert row.active_target_id == "focus-1"
    assert row.pid == 9


@pytest.mark.asyncio
async def test_close_tab_updates_active_pointer(tmp_path: Path) -> None:
    """Closing the active tab moves active_target_id to a remaining tab."""
    ctx = _FakeContext([_FakePage("tab-1"), _FakePage("tab-2")])
    page2 = ctx.pages[1]
    view = TabSessionView(context=ctx)
    write_registry(
        tmp_path,
        "s1",
        BrowserSessionRegistry(
            pid=1,
            cdp_url="http://127.0.0.1:1",
            cdp_port=1,
            profile_dir=str(tmp_path / "p"),
            headless=False,
            spawned_by_sevn=True,
            last_used_at=datetime.now(tz=UTC).isoformat(),
            active_target_id="tab-2",
        ),
    )
    await close_tab(view, "tab-2", content_root=tmp_path, session_id="s1")
    assert page2.closed is True
    row = read_registry(tmp_path, "s1")
    assert row is not None
    assert row.active_target_id == "tab-1"
