"""W1 RED: Telegram /config menu walker — offline FakeCDPServer + live smoke (green after W2)."""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any

import pytest

from sevn.browser.recipes.base import RecipeError
from sevn.browser.recipes.telegram_menu import _mutation_target

if TYPE_CHECKING:
    from tests.browser.conftest import FakeCDPServer

# Scripted Telegram Web K inline-keyboard DOM returned by Runtime.evaluate.
_INLINE_KEYBOARD_MATRIX: list[list[dict[str, Any]]] = [
    [
        {"row": 0, "col": 0, "text": "📦 Session", "has_url": False, "url": None},
        {"row": 0, "col": 1, "text": "🤖 Agents", "has_url": False, "url": None},
    ],
    [
        {"row": 1, "col": 0, "text": "⬅ Back", "has_url": False, "url": None},
    ],
]


def _eval_inline_dom(_msg: dict[str, Any]) -> dict[str, Any]:
    flat: list[dict[str, Any]] = []
    for row in _INLINE_KEYBOARD_MATRIX:
        for btn in row:
            flat.append(btn)
    return {"result": {"value": flat}}


def _eval_signature(_msg: dict[str, Any]) -> dict[str, Any]:
    return {"result": {"value": "sig-root-v1"}}


def _eval_toast(_msg: dict[str, Any]) -> dict[str, Any]:
    return {"result": {"value": "🚧 Not ready yet"}}


@pytest.mark.asyncio
async def test_inline_buttons_enumerates_rows_and_labels(fake_cdp: FakeCDPServer) -> None:
    """W1.1 — inline keyboard matrix exposes row/col/text/url metadata."""
    from sevn.browser.cdp import CDPConnection, CDPSession
    from sevn.browser.element import Dom
    from sevn.browser.page import Page
    from sevn.browser.recipes.telegram_web import TelegramWeb

    fake_cdp.on_command("Runtime.evaluate", _eval_inline_dom)
    conn = await CDPConnection.connect(fake_cdp.ws_url)
    session = CDPSession(conn)
    try:
        tg = TelegramWeb(Page(session), Dom(session))
        buttons = await tg.inline_buttons(message="last")
        assert len(buttons) == 3
        assert buttons[0]["text"] == "📦 Session"
        assert buttons[0]["row"] == 0
        assert buttons[0]["col"] == 0
        assert buttons[0]["has_url"] is False
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_tap_inline_by_label_returns_tap_outcome(fake_cdp: FakeCDPServer) -> None:
    """W1.1 — tap-by-label settles edit-in-place and captures toast."""
    from sevn.browser.cdp import CDPConnection, CDPSession
    from sevn.browser.element import Dom
    from sevn.browser.page import Page
    from sevn.browser.recipes.telegram_web import TelegramWeb

    sig_state = {"sig_calls": 0}

    def _eval_runtime(msg: dict[str, Any]) -> dict[str, Any]:
        expr = str(msg.get("params", {}).get("expression", ""))
        if "labels.join" in expr or "labels.push" in expr:
            sig_state["sig_calls"] += 1
            if sig_state["sig_calls"] > 1:
                return {"result": {"value": "sig-after-tap"}}
            return {"result": {"value": "sig-before"}}
        if ".toast" in expr:
            return {"result": {"value": None}}
        if expr.strip().startswith("document.querySelectorAll") and ".length" in expr:
            return {"result": {"value": 1}}
        return _eval_inline_dom(msg)

    fake_cdp.on_command("Runtime.evaluate", _eval_runtime)
    fake_cdp.set_result("DOM.getDocument", {"root": {"nodeId": 1}})
    fake_cdp.set_result("DOM.querySelector", {"nodeId": 2})
    fake_cdp.set_result("DOM.scrollIntoViewIfNeeded", {})
    fake_cdp.set_result("DOM.getBoxModel", {"model": {"content": [0, 0, 4, 0, 4, 4, 0, 4]}})
    fake_cdp.set_result("Input.dispatchMouseEvent", {})
    conn = await CDPConnection.connect(fake_cdp.ws_url)
    session = CDPSession(conn)
    try:
        tg = TelegramWeb(Page(session), Dom(session))
        outcome = await tg.tap_inline("📦 Session", settle_timeout=0.2)
        assert outcome["changed"] is True
        assert "new_signature" in outcome
        assert isinstance(outcome.get("toast"), (str, type(None)))
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_screen_signature_stable_hash(fake_cdp: FakeCDPServer) -> None:
    """W1.1 — screen_signature hashes caption + button matrix."""
    from sevn.browser.cdp import CDPConnection, CDPSession
    from sevn.browser.element import Dom
    from sevn.browser.page import Page
    from sevn.browser.recipes.telegram_web import TelegramWeb

    fake_cdp.on_command("Runtime.evaluate", _eval_signature)
    conn = await CDPConnection.connect(fake_cdp.ws_url)
    session = CDPSession(conn)
    try:
        tg = TelegramWeb(Page(session), Dom(session))
        sig1 = await tg.screen_signature()
        sig2 = await tg.screen_signature()
        assert sig1 == sig2 == "sig-root-v1"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_read_toast_returns_popup_text(fake_cdp: FakeCDPServer) -> None:
    """W1.1 — toast reader captures answerCallbackQuery text."""
    from sevn.browser.cdp import CDPConnection, CDPSession
    from sevn.browser.element import Dom
    from sevn.browser.page import Page
    from sevn.browser.recipes.telegram_web import TelegramWeb

    fake_cdp.on_command("Runtime.evaluate", _eval_toast)
    conn = await CDPConnection.connect(fake_cdp.ws_url)
    session = CDPSession(conn)
    try:
        tg = TelegramWeb(Page(session), Dom(session))
        toast = await tg.read_toast(timeout=0.2)
        assert toast == "🚧 Not ready yet"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_press_back_taps_nav_row(fake_cdp: FakeCDPServer) -> None:
    """W1.1 — back navigation uses cfg:nav callback family, not emoji heuristics."""
    from sevn.browser.cdp import CDPConnection, CDPSession
    from sevn.browser.element import Dom
    from sevn.browser.page import Page
    from sevn.browser.recipes.telegram_web import TelegramWeb

    fake_cdp.on_command("Runtime.evaluate", _eval_inline_dom)
    fake_cdp.set_result("DOM.getDocument", {"root": {"nodeId": 1}})
    fake_cdp.set_result("DOM.querySelector", {"nodeId": 2})
    fake_cdp.set_result("DOM.scrollIntoViewIfNeeded", {})
    fake_cdp.set_result("DOM.getBoxModel", {"model": {"content": [0, 0, 4, 0, 4, 4, 0, 4]}})
    fake_cdp.set_result("Input.dispatchMouseEvent", {})
    conn = await CDPConnection.connect(fake_cdp.ws_url)
    session = CDPSession(conn)
    try:
        tg = TelegramWeb(Page(session), Dom(session))
        await tg.press_back()
        methods = [msg.get("method") for msg in fake_cdp.received if "method" in msg]
        assert "Input.dispatchMouseEvent" in methods
    finally:
        await conn.close()


@pytest.mark.parametrize(
    ("before", "after", "toast", "row_kind", "expected"),
    [
        (
            {"signature": "a", "message_count": 1},
            {"signature": "b", "message_count": 1},
            None,
            "nav",
            "ok",
        ),
        (
            {"signature": "a", "message_count": 1},
            {"signature": "a", "message_count": 1},
            "🚧 gated",
            "disabled",
            "graceful_wip",
        ),
        (
            {"signature": "a", "message_count": 1},
            {"signature": "a", "message_count": 1},
            None,
            "action",
            "dead",
        ),
        (
            {"signature": "a", "message_count": 1},
            {"signature": "a", "message_count": 1},
            "Telegram error",
            "action",
            "error",
        ),
        (
            {"signature": "a", "message_count": 1},
            {"signature": "b", "message_count": 1},
            "🚧 gated",
            "disabled",
            "error",
        ),
    ],
)
def test_classify_outcome_verdict_table(
    before: dict[str, Any],
    after: dict[str, Any],
    toast: str | None,
    row_kind: str,
    expected: str,
) -> None:
    """W1.1 — pure verdict classifier encodes D5 (ok/graceful_wip/dead/error)."""
    from sevn.browser.recipes.telegram_menu import classify_outcome

    verdict = classify_outcome(before, after, toast, row_kind=row_kind)
    assert verdict.value == expected


def test_walker_dfs_order_from_live_keyboard() -> None:
    """W1.2 — walker plan follows depth-first order with Back tracking."""
    from sevn.browser.recipes.telegram_menu import expected_tree

    plan = expected_tree()
    section_ids = [node.section_id for node in plan]
    assert section_ids[0] == "root"
    assert section_ids.count("root") == 1
    assert len(section_ids) >= 8


@pytest.mark.parametrize(
    "callback",
    [
        "act:gateway:restart",
        "act:tunnel:on",
        "act:subagents:kill:abc",
        "act:unboard",
        "act:secrets:export-secrets",
        "act:deploy:remote",
    ],
)
def test_deny_list_marks_destructive_callbacks_skipped(callback: str) -> None:
    """W1.2 — deny-listed callbacks report skipped(destructive), never execute."""
    from sevn.browser.recipes.telegram_menu import DEFAULT_DENY, classify_row, row_verdict_for_skip

    row = classify_row(callback_data=callback, label="destructive", readiness="Ready")
    assert DEFAULT_DENY.match(callback) is not None
    assert row_verdict_for_skip(row) == "skipped"


def test_mutate_mode_refuses_without_dual_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """W1.2 — mutate refuses unless SEVN_TELEGRAM_MENU_E2E_MUTATE=1 and non-default workspace."""
    from sevn.browser.recipes.telegram_menu import validate_mutate_guards

    monkeypatch.delenv("SEVN_TELEGRAM_MENU_E2E_MUTATE", raising=False)
    with pytest.raises(Exception, match="mutate"):
        validate_mutate_guards(safe=False, workspace_root="/Users/alex/.sevn/workspace")


def test_walk_fails_when_spec_id_not_visited_or_denylisted() -> None:
    """W1.3 — coverage report fails when a spec id is neither visited nor skipped."""
    from sevn.browser.recipes.telegram_menu import assert_spec_coverage

    report = {
        "visited": {"C0.1"},
        "skipped": {},
    }
    with pytest.raises(Exception, match="coverage"):
        assert_spec_coverage(report, missing_spec_id="C99.9")


@pytest.mark.telegram_menu_e2e
@pytest.mark.skipif(
    os.environ.get("SEVN_TELEGRAM_MENU_E2E") != "1",
    reason="Set SEVN_TELEGRAM_MENU_E2E=1 for live Telegram menu walk smoke",
)
def test_live_menu_walk_smoke_returns_report_without_dead() -> None:
    """W1.4 / D11 — optional live smoke: open /config and assert zero dead verdicts."""
    from sevn.browser.recipes.telegram_menu_walk import run_walk_cli

    out = run_walk_cli(
        chat=os.environ.get("SEVN_TELEGRAM_MENU_E2E_CHAT", "alexstestee_bot"),
        safe=True,
        as_json=True,
    )
    payload = json.loads(out)
    assert payload["summary"]["dead"] == 0
    assert payload["summary"]["visited"] >= 1


class _FakeTelegramWeb:
    """In-memory Telegram Web that serves exactly the real ``expected_tree`` shape.

    Screens come from the live keyboard builders, so the walker is exercised
    against the actual nesting depth of the shipped tree rather than a two-level
    toy fixture.
    """

    def __init__(self, plan: list[Any]) -> None:
        self.screens: dict[str, tuple[Any, ...]] = {n.section_id: n.rows for n in plan}
        self.path: list[str] = ["root"]
        self.entered: list[str] = []
        self.max_depth = 0
        self.taps: list[str] = []
        self.mut_index: dict[str, int] = {}
        self.mut_ring: dict[str, list[str]] = {}
        self._counter = 0
        for node in plan:
            for row in node.rows:
                for btn in row:
                    cb = str(btn.get("callback_data") or "")
                    target = _mutation_target(cb)
                    if target and target not in self.mut_ring:
                        suffix = cb.rsplit(":", 1)[-1]
                        if cb.startswith("cfg:toggle:"):
                            other = "true" if suffix == "false" else "false"
                            self.mut_ring[target] = [suffix, other]
                        else:
                            self.mut_ring[target] = [suffix, "_alt1", "_alt2"]
                        self.mut_index[target] = 0

    def _current_buttons(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for row in self.screens.get(self.path[-1], ()):
            for btn in row:
                item = dict(btn)
                cb = str(item.get("callback_data") or "")
                target = _mutation_target(cb)
                if target:
                    prefix = cb[: cb.rindex(":")]
                    ring = self.mut_ring[target]
                    item["callback_data"] = f"{prefix}:{ring[self.mut_index[target]]}"
                out.append(item)
        if len(self.path) > 1:
            out.append({"text": "⬅ Back", "callback_data": "cfg:nav:back"})
        return out

    async def open_menu(self, _cmd: str) -> None:
        self.path = ["root"]

    async def inline_buttons(self, *, message: str = "last") -> list[dict[str, Any]]:
        _ = message
        return self._current_buttons()

    async def screen_signature(self) -> str:
        return f"{'/'.join(self.path)}#{sorted(self.mut_index.items())}"

    async def _message_count(self) -> int:
        return self._counter

    async def press_back(self) -> dict[str, Any]:
        if len(self.path) == 1:
            msg = "no back button on root"
            raise RecipeError(msg)
        self.path.pop()
        return {"new_signature": await self.screen_signature(), "new_message": False}

    async def tap_inline(self, label: str, *, settle_timeout: float = 0.0) -> dict[str, Any]:
        _ = settle_timeout
        match = next((b for b in self._current_buttons() if str(b.get("text")) == label), None)
        if match is None:
            msg = f"no button labelled {label!r}"
            raise RecipeError(msg)
        cb = str(match.get("callback_data") or "")
        self.taps.append(cb)
        if cb == "cfg:nav:back":
            return await self.press_back()
        if cb.startswith("cfg:section:"):
            target = cb.removeprefix("cfg:section:")
            if target not in self.screens:
                msg = f"unknown section {target!r}"
                raise RecipeError(msg)
            self.path.append(target)
            self.entered.append(target)
            self.max_depth = max(self.max_depth, len(self.path) - 1)
            return {"new_signature": await self.screen_signature(), "new_message": False}
        target = _mutation_target(cb)
        if target:
            ring = self.mut_ring[target]
            self.mut_index[target] = (self.mut_index[target] + 1) % len(ring)
            return {"new_signature": await self.screen_signature(), "new_message": False}
        self._counter += 1
        return {
            "new_signature": await self.screen_signature(),
            "new_message": True,
            "toast": f"ran {cb}",
        }


@pytest.mark.asyncio
async def test_walk_reaches_every_section_including_nested_ones() -> None:
    """PR #63 review: one blind ``press_back()`` per node could not go past depth 1.

    ``expected_tree`` is a flat pre-order DFS, so consecutive plan nodes are often
    not parent/child. With a single back-tap the walker sat on the wrong screen and
    ``_enter_section`` raised ``RecipeError``, aborting the run — so the "full-tree
    navigation evidence" claim only ever covered the first level.
    """
    from sevn.browser.recipes.telegram_menu import TelegramMenuWalker, expected_tree

    plan = expected_tree()
    fake = _FakeTelegramWeb(plan)
    walker = TelegramMenuWalker(tg=fake, safe=True)  # type: ignore[arg-type]
    await walker.walk()

    planned = {node.section_id for node in plan} - {"root"}
    assert set(fake.entered) >= planned, planned - set(fake.entered)
    assert fake.max_depth >= 2, "fixture must exercise a section nested two levels deep"
    assert not [line for line in walker._log_lines if "navigation_failed" in line]

    # Sections whose rows are all nav/chrome record nothing by design; every
    # section that does hold an actionable row must appear in the walk log.
    from sevn.gateway.menu.menu_registry import is_nav_chrome_callback

    actionable = {
        node.section_id
        for node in plan
        if any(
            (cb := str(btn.get("callback_data") or ""))
            and not cb.startswith("cfg:section:")
            and not is_nav_chrome_callback(cb)
            for row in node.rows
            for btn in row
        )
    }
    walked_sections = {row["section"] for row in walker.rows}
    assert walked_sections >= actionable, actionable - walked_sections
    deep = {node.section_id for node in plan if len(node.path) >= 3}
    assert walked_sections & deep, "no section nested two levels deep recorded any row"


@pytest.mark.asyncio
async def test_mutate_mode_taps_and_restores_toggle_rows() -> None:
    """PR #63 review: ``--mutate`` tapped nothing and always raised ``CoverageError``.

    Toggle/cycle rows returned early without being tapped *and* without being
    recorded as skipped, so their spec ids were in neither coverage set.
    """
    from sevn.browser.recipes.telegram_menu import TelegramMenuWalker, expected_tree

    plan = expected_tree()
    fake = _FakeTelegramWeb(plan)
    walker = TelegramMenuWalker(tg=fake, safe=False)  # type: ignore[arg-type]
    report = await walker.walk()

    mutated = [cb for cb in fake.taps if _mutation_target(cb)]
    assert mutated, "mutate mode tapped no toggle/cycle rows"
    assert all(idx == 0 for idx in fake.mut_index.values()), "rows left mutated after the walk"

    toggle_rows = [r for r in report["rows"] if r["row_kind"] in {"toggle", "cycle"}]
    assert toggle_rows, "no toggle rows recorded in mutate mode"
    assert not [r for r in toggle_rows if r["skip_reason"] == "mutate_only"]
    assert not [r for r in toggle_rows if r["verdict"] == "error"], toggle_rows[:3]


@pytest.mark.asyncio
async def test_safe_mode_leaves_toggle_rows_untouched() -> None:
    """--safe still records toggle rows as skipped(mutate_only) without tapping."""
    from sevn.browser.recipes.telegram_menu import TelegramMenuWalker, expected_tree

    fake = _FakeTelegramWeb(expected_tree())
    walker = TelegramMenuWalker(tg=fake, safe=True)  # type: ignore[arg-type]
    report = await walker.walk()

    assert not [cb for cb in fake.taps if _mutation_target(cb)]
    assert all(idx == 0 for idx in fake.mut_index.values())
    toggle_rows = [r for r in report["rows"] if r["row_kind"] in {"toggle", "cycle"}]
    assert toggle_rows
    assert all(r["skip_reason"] == "mutate_only" for r in toggle_rows)
