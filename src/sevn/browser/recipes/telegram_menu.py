"""Telegram ``/config`` menu walker — tree-agnostic E2E over Telegram Web K.

Derives the expected keyboard tree from :func:`build_config_menu_keyboard` and
``MENU_BUTTON_SPECS`` at run time (D1), drives Telegram Web via
:class:`~sevn.browser.recipes.telegram_web.TelegramWeb`, and emits per-row verdicts
(D5) plus spec-id coverage accounting (D9).

Live selectors (D12, tuned 2026-07-26 against Telegram Web K):
  ``.reply-markup`` / ``.reply-markup-row`` / ``.reply-markup-button``
  ``.bubbles .bubble:last-of-type`` for the active menu bubble
  ``.toast`` / ``.popup-alert`` for callback toasts

Module: sevn.browser.recipes.telegram_menu
Depends: asyncio, dataclasses, enum, json, os, pathlib, re, time, typing,
    sevn.browser.recipes.base, sevn.browser.recipes.telegram_web,
    sevn.config.workspace_config, sevn.gateway.menu.menu,
    sevn.gateway.menu.menu_readiness, sevn.gateway.menu.menu_registry

Exports:
    Verdict — row outcome enum (ok / graceful_wip / dead / error / skipped).
    CoverageError — coverage accounting failure.
    MenuTreeNode — one planned section screen.
    MenuRow — classified inline button row.
    expected_tree — DFS plan from live keyboard builders (D1).
    max_leaf_depth_from_root — minimum tap depth from root to each section (W3 tests).
    classify_row — nav/toggle/form/action/url/disabled/destructive classifier.
    classify_row_from_button — classify one inline button dict.
    classify_outcome — pure verdict function over before/after/toast (D5).
    row_verdict_for_skip — skipped verdict label for deny-listed rows.
    validate_mutate_guards — refuse ``--mutate`` without dual guard (D7).
    assert_spec_coverage — fail when a spec id is neither visited nor skipped (D9).
    ensure_login — human-in-the-loop login poll (D3).
    TelegramMenuWalker — DFS walk + evidence writer (D10).
    run_menu_walk — async entry for CLI and browser tool.

Examples:
    >>> from sevn.browser.recipes.telegram_menu import classify_outcome, Verdict
    >>> classify_outcome(
    ...     {"signature": "a", "message_count": 1},
    ...     {"signature": "b", "message_count": 1},
    ...     None,
    ...     row_kind="nav",
    ... ).value
    'ok'
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlparse

from sevn.browser.recipes.base import RecipeError
from sevn.browser.recipes.telegram_web import TelegramWeb
from sevn.config.workspace_config import WorkspaceConfig
from sevn.gateway.menu.menu import build_config_menu_keyboard
from sevn.gateway.menu.menu_readiness import DISABLED_CALLBACK_PREFIX, readiness_for_callback
from sevn.gateway.menu.menu_registry import (
    MENU_BUTTON_SPECS,
    is_nav_chrome_callback,
    match_menu_button_spec,
)

_DEFAULT_OPERATOR_WS: Final[str] = str(Path.home() / ".sevn" / "workspace")
_DEFAULT_PROFILE_DIR: Final[Path] = Path(".sevn/browser-profiles/telegram-e2e")
_CHROME_CALLBACKS: Final[frozenset[str]] = frozenset(
    {"cfg:nav:back", "cfg:nav:help", "cfg:nav:home", "cfg:nav:close"}
)
_SECTION_PREFIX: Final[str] = "cfg:section:"
_MUTATION_PREFIXES: Final[tuple[str, ...]] = ("cfg:toggle:", "cfg:cycle:")
#: Upper bound on re-taps when restoring a cycle row; the longest live cycle is
#: four-valued (dm_policy), so this leaves headroom without looping forever.
_MAX_RESTORE_TAPS: Final[int] = 8


def _is_mutation_pattern(callback_pattern: str) -> bool:
    """Return whether a registry pattern describes a toggle/cycle row.

    Args:
        callback_pattern (str): ``MenuButtonSpec.callback_pattern`` value.

    Returns:
        bool: ``True`` for toggle/cycle patterns, anchored or bare.

    Examples:
        >>> _is_mutation_pattern(r"^cfg:toggle:gateway\\.queue_mode:.+$")
        True
        >>> _is_mutation_pattern("cfg:cycle:x:.+")
        True
        >>> _is_mutation_pattern("^act:doctor:run$")
        False
    """
    stripped = callback_pattern.removeprefix("^")
    return stripped.startswith(_MUTATION_PREFIXES)


def _mutation_target(callback_data: str) -> str:
    """Return the dot-path a toggle/cycle callback mutates, or ``""``.

    Args:
        callback_data (str): Raw ``callback_data`` from an inline button.

    Returns:
        str: Dot-path being mutated, empty when the callback is not a mutation.

    Examples:
        >>> _mutation_target("cfg:toggle:channels.telegram.show_routing:false")
        'channels.telegram.show_routing'
        >>> _mutation_target("cfg:cycle:channels.telegram.dm_policy:pairing")
        'channels.telegram.dm_policy'
        >>> _mutation_target("act:doctor:run")
        ''
    """
    for prefix in _MUTATION_PREFIXES:
        if callback_data.startswith(prefix):
            rest = callback_data[len(prefix) :]
            return rest.rsplit(":", 1)[0] if ":" in rest else rest
    return ""


class Verdict(StrEnum):
    """Per-row walk outcome (D5)."""

    OK = "ok"
    GRACEFUL_WIP = "graceful_wip"
    DEAD = "dead"
    ERROR = "error"
    SKIPPED = "skipped"


class CoverageError(RecipeError):
    """Raised when spec-id coverage accounting fails (D9)."""


@dataclass(frozen=True)
class MenuTreeNode:
    """One section screen in the DFS walk plan."""

    section_id: str
    rows: tuple[tuple[dict[str, Any], ...], ...]
    #: Section ids from ``root`` down to and including this node. The walker
    #: needs the full path to navigate: one blind ``press_back()`` per node only
    #: works while the tree is one level deep.
    path: tuple[str, ...] = ()


@dataclass(frozen=True)
class MenuRow:
    """One classified inline button row."""

    callback_data: str
    label: str
    readiness: str
    row_kind: str
    spec_id: str | None = None
    url: str | None = None


DEFAULT_DENY: Final[re.Pattern[str]] = re.compile(
    r"(?:"
    r"act:(?:gateway:restart|proxy:restart|tunnel:on|subagents:kill|deploy:remote|secrets:export-secrets)"
    r"|act:.*unboard"
    r"|export-secrets"
    r"|secrets.*rm"
    r")",
    re.IGNORECASE,
)


def expected_tree(*, workspace: WorkspaceConfig | None = None) -> list[MenuTreeNode]:
    """Build a DFS section plan from the live keyboard builders (D1).

    Args:
        workspace (WorkspaceConfig | None): Workspace for keyboard rendering.

    Returns:
        list[MenuTreeNode]: Depth-first section order starting at ``root``.

    Examples:
        >>> plan = expected_tree()
        >>> plan[0].section_id
        'root'
        >>> plan[0].path
        ('root',)
        >>> len(plan) >= 19
        True
        >>> all(node.path[-1] == node.section_id for node in plan)
        True
    """
    ws = workspace or WorkspaceConfig.minimal()
    plan: list[MenuTreeNode] = []
    visited: set[str] = set()

    def dfs(section_id: str, path: tuple[str, ...]) -> None:
        if section_id in visited:
            return
        visited.add(section_id)
        markup = build_config_menu_keyboard(ws, section=section_id)  # type: ignore[arg-type]
        raw_rows = markup.get("inline_keyboard") or []
        frozen_rows = tuple(tuple(dict(btn) for btn in row) for row in raw_rows)
        plan.append(MenuTreeNode(section_id=section_id, rows=frozen_rows, path=path))
        for row in raw_rows:
            for btn in row:
                cb = str(btn.get("callback_data") or "")
                if cb.startswith(_SECTION_PREFIX):
                    target = cb[len(_SECTION_PREFIX) :]
                    dfs(target, (*path, target))

    dfs("root", ("root",))
    return plan


def max_leaf_depth_from_root(*, workspace: WorkspaceConfig | None = None) -> dict[str, int]:
    """Return minimum tap depth from ``root`` to each reachable section id.

    Args:
        workspace (WorkspaceConfig | None): Workspace for keyboard rendering.

    Returns:
        dict[str, int]: Section id → hop count from root (root is ``0``).

    Examples:
        >>> depths = max_leaf_depth_from_root()
        >>> depths["root"] == 0
        True
        >>> depths["chat"] == 1
        True
    """
    ws = workspace or WorkspaceConfig.minimal()
    best: dict[str, int] = {"root": 0}
    queue: list[tuple[str, int]] = [("root", 0)]
    seen: set[str] = set()

    while queue:
        section_id, depth = queue.pop(0)
        if section_id in seen:
            continue
        seen.add(section_id)
        if section_id not in best or depth < best[section_id]:
            best[section_id] = depth
        markup = build_config_menu_keyboard(ws, section=section_id)  # type: ignore[arg-type]
        for row in markup.get("inline_keyboard") or []:
            for btn in row:
                cb = str(btn.get("callback_data") or "")
                if cb.startswith(_SECTION_PREFIX):
                    child = cb[len(_SECTION_PREFIX) :]
                    queue.append((child, depth + 1))

    return best


def classify_row(*, callback_data: str, label: str, readiness: str) -> MenuRow:
    """Classify one inline row by callback pattern and readiness tier.

    Args:
        callback_data (str): Telegram ``callback_data`` payload.
        label (str): Visible button label.
        readiness (str): Readiness tier from the menu registry.

    Returns:
        MenuRow: Classified row metadata.

    Examples:
        >>> classify_row(callback_data="cfg:nav:back", label="Back", readiness="Ready").row_kind
        'nav'
    """
    cb = callback_data.strip()
    spec = match_menu_button_spec(cb) if cb else None
    spec_id = spec.spec_id if spec else None
    if DEFAULT_DENY.search(cb):
        return MenuRow(cb, label, readiness, "destructive", spec_id=spec_id)
    if cb.startswith(DISABLED_CALLBACK_PREFIX):
        return MenuRow(cb, label, readiness, "disabled", spec_id=spec_id)
    if is_nav_chrome_callback(cb) or cb.startswith(_SECTION_PREFIX):
        return MenuRow(cb, label, readiness, "nav", spec_id=spec_id)
    if cb.startswith("form:"):
        return MenuRow(cb, label, readiness, "form", spec_id=spec_id)
    if cb.startswith("cfg:toggle:"):
        return MenuRow(cb, label, readiness, "toggle", spec_id=spec_id)
    if cb.startswith("cfg:cycle:"):
        return MenuRow(cb, label, readiness, "cycle", spec_id=spec_id)
    if cb.startswith("act:"):
        return MenuRow(cb, label, readiness, "action", spec_id=spec_id)
    return MenuRow(cb, label, readiness, "action", spec_id=spec_id)


def classify_row_from_button(btn: dict[str, Any]) -> MenuRow:
    """Classify one Telegram inline button dict.

    Args:
        btn (dict[str, Any]): Inline button with ``text`` and optional ``callback_data``/``url``.

    Returns:
        MenuRow: Classified row metadata.

    Examples:
        >>> classify_row_from_button({"text": "Back", "callback_data": "cfg:nav:back"}).row_kind
        'nav'
    """
    label = str(btn.get("text") or "")
    url = btn.get("url")
    if url:
        return MenuRow("", label, "Ready", "url", url=str(url))
    cb = str(btn.get("callback_data") or "")
    readiness = readiness_for_callback(cb) if cb else "WIP"
    return classify_row(callback_data=cb, label=label, readiness=readiness)


def classify_outcome(
    before: dict[str, Any],
    after: dict[str, Any],
    toast: str | None,
    *,
    row_kind: str,
) -> Verdict:
    """Pure verdict classifier encoding D5.

    Args:
        before (dict[str, Any]): Screen state before the tap.
        after (dict[str, Any]): Screen state after the tap.
        toast (str | None): Callback toast text, if any.
        row_kind (str): Classified row kind.

    Returns:
        Verdict: Row outcome.

    Examples:
        >>> classify_outcome({"signature": "a", "message_count": 1}, {"signature": "b", "message_count": 1}, None, row_kind="nav")
        <Verdict.OK: 'ok'>
    """
    before_sig = str(before.get("signature") or "")
    after_sig = str(after.get("signature") or "")
    before_count = int(before.get("message_count") or 0)
    after_count = int(after.get("message_count") or 0)
    screen_changed = before_sig != after_sig
    new_message = after_count > before_count
    toast_text = (toast or "").strip()

    if toast_text and _looks_like_error(toast_text):
        return Verdict.ERROR
    if row_kind == "disabled":
        if screen_changed:
            return Verdict.ERROR
        if toast_text and ("🚧" in toast_text or DISABLED_CALLBACK_PREFIX in toast_text):
            return Verdict.GRACEFUL_WIP
        if toast_text:
            return Verdict.GRACEFUL_WIP
        return Verdict.DEAD
    if row_kind in {"nav", "toggle", "cycle", "form", "action", "url"}:
        if screen_changed or new_message:
            return Verdict.OK
        if toast_text:
            if toast_text.startswith("🚧"):
                return Verdict.GRACEFUL_WIP
            return Verdict.OK
        if row_kind == "action":
            return Verdict.DEAD
        return Verdict.DEAD
    return Verdict.ERROR if screen_changed and row_kind == "destructive" else Verdict.DEAD


def row_verdict_for_skip(row: MenuRow) -> str:
    """Return the skipped verdict label for deny-listed rows.

    Args:
        row (MenuRow): Classified row (unused; kept for call-site clarity).

    Returns:
        str: ``skipped`` verdict value.

    Examples:
        >>> row_verdict_for_skip(classify_row(callback_data="act:tunnel:on", label="x", readiness="Ready"))
        'skipped'
    """
    _ = row
    return Verdict.SKIPPED.value


def validate_mutate_guards(*, safe: bool, workspace_root: str | Path) -> None:
    """Refuse ``--mutate`` unless both D7 guards are satisfied.

    Args:
        safe (bool): When ``True``, mutate guards are not checked.
        workspace_root (str | Path): Workspace root bound to the walk.

    Raises:
        RecipeError: When mutate mode is requested without both guards.

    Examples:
        >>> validate_mutate_guards(safe=True, workspace_root="/tmp/ws")
    """
    if safe:
        return
    if os.environ.get("SEVN_TELEGRAM_MENU_E2E_MUTATE") != "1":
        msg = "mutate mode requires SEVN_TELEGRAM_MENU_E2E_MUTATE=1"
        raise RecipeError(msg)
    normalized = str(Path(workspace_root).expanduser().resolve())
    default_ws = str(Path(_DEFAULT_OPERATOR_WS).expanduser().resolve())
    if normalized == default_ws:
        msg = "mutate mode refuses the default operator workspace — use a throwaway root"
        raise RecipeError(msg)


def assert_spec_coverage(
    report: dict[str, Any],
    *,
    missing_spec_id: str | None = None,
) -> None:
    """Fail when any ``MenuButtonSpec`` id is neither visited nor skipped (D9).

    Args:
        report (dict[str, Any]): Walk report with ``visited`` and ``skipped`` sets.
        missing_spec_id (str | None): Optional extra id that must be accounted for.

    Raises:
        CoverageError: When one or more spec ids are uncovered.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(assert_spec_coverage)
        True
    """
    visited: set[str] = set(report.get("visited") or [])
    skipped_raw = report.get("skipped") or {}
    skipped: set[str] = set(skipped_raw.keys()) if isinstance(skipped_raw, dict) else set()
    required = {spec.spec_id for spec in MENU_BUTTON_SPECS}
    if missing_spec_id:
        required.add(missing_spec_id)
    uncovered = sorted(required - visited - skipped)
    if (
        missing_spec_id
        and missing_spec_id not in visited
        and missing_spec_id not in skipped
        and missing_spec_id not in uncovered
    ):
        uncovered.append(missing_spec_id)
    if uncovered:
        msg = f"coverage miss: {', '.join(uncovered[:8])}"
        raise CoverageError(msg)


def _looks_like_error(toast: str) -> bool:
    """Return whether ``toast`` text indicates a Telegram/gateway error.

    Args:
        toast (str): Toast or alert text.

    Returns:
        bool: ``True`` when the text looks like an error.

    Examples:
        >>> _looks_like_error("Telegram error: bad request")
        True
    """
    lowered = toast.lower()
    return "error" in lowered or "failed" in lowered or "invalid" in lowered


async def ensure_login(tg: TelegramWeb, *, timeout_s: float = 300.0) -> None:
    """Reuse ``TelegramWeb.login`` and poll until logged in (D3).

    Args:
        tg (TelegramWeb): Bound Telegram Web recipe.
        timeout_s (float): Seconds to wait for operator login.

    Raises:
        RecipeError: When login times out.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(ensure_login)
        True
    """
    result = await tg.login()
    if result.get("logged_in"):
        return
    reason = str(result.get("reason") or "Complete Telegram Web login in the browser window.")
    sys.stderr.write(reason + "\n")
    if url := result.get("url"):
        sys.stderr.write(f"URL: {url}\n")
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if await tg.logged_in():
            return
        await asyncio.sleep(3.0)
    msg = f"Telegram login timed out after {timeout_s:.0f}s"
    raise RecipeError(msg)


@dataclass
class TelegramMenuWalker:
    """DFS walker for the ``/config`` inline keyboard tree."""

    tg: TelegramWeb
    workspace: WorkspaceConfig = field(default_factory=WorkspaceConfig.minimal)
    safe: bool = True
    deny: re.Pattern[str] = DEFAULT_DENY
    max_depth: int = 4
    out_dir: Path | None = None
    rows: list[dict[str, Any]] = field(default_factory=list)
    visited_spec_ids: set[str] = field(default_factory=set)
    skipped_spec_ids: dict[str, str] = field(default_factory=dict)
    _log_lines: list[str] = field(default_factory=list)

    async def walk(self) -> dict[str, Any]:
        """Walk every reachable row and return a structured report.

        Returns:
            dict[str, Any]: Report with ``summary``, ``rows``, and spec-id accounting.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TelegramMenuWalker.walk)
            True
        """
        await self.tg.open_menu("/config")
        plan = expected_tree(workspace=self.workspace)
        current: tuple[str, ...] = ("root",)
        for node in plan:
            target = node.path or (node.section_id,)
            current = await self._navigate_to(target, current=current)
            await self._walk_section(node.section_id)
        report = self._build_report()
        if self.out_dir is not None:
            self._write_evidence(report)
        self._reconcile_skipped_specs()
        assert_spec_coverage({"visited": self.visited_spec_ids, "skipped": self.skipped_spec_ids})
        return report

    async def _navigate_to(
        self,
        target: tuple[str, ...],
        *,
        current: tuple[str, ...],
    ) -> tuple[str, ...]:
        """Walk from ``current`` to ``target`` via the nearest common ancestor.

        The plan is a flat pre-order DFS, so consecutive nodes are frequently not
        parent/child: finishing ``chat_voice`` and starting ``agent`` means going
        up two levels and down one. Popping back to the shared prefix and then
        entering the remaining segments is what makes sections two or more levels
        deep reachable at all.

        Args:
            target (tuple[str, ...]): Section path to land on, ``root`` first.
            current (tuple[str, ...]): Section path currently displayed.

        Returns:
            tuple[str, ...]: The path actually reached (``target`` on success).

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TelegramMenuWalker._navigate_to)
            True
        """
        if target == current:
            return current
        shared = 0
        for left, right in zip(current, target, strict=False):
            if left != right:
                break
            shared += 1
        for _ in range(len(current) - shared):
            try:
                await self.tg.press_back()
            except RecipeError:
                # Back chrome missing (or the screen never rendered) — fall back to
                # /config so the walk resumes from a known screen instead of
                # aborting every remaining section.
                await self.tg.open_menu("/config")
                current = ("root",)
                shared = 1 if target and target[0] == "root" else 0
                break
        reached = list(target[:shared]) or ["root"]
        for section_id in target[shared:]:
            try:
                await self._enter_section(section_id)
            except RecipeError as exc:
                self._log_lines.append(
                    json.dumps(
                        {
                            "event": "navigation_failed",
                            "section": section_id,
                            "path": list(target),
                            "error": str(exc),
                        },
                        sort_keys=True,
                    ),
                )
                return tuple(reached)
            reached.append(section_id)
        return tuple(reached)

    async def _enter_section(self, section_id: str) -> None:
        """Navigate into ``section_id`` from the current keyboard.

        Args:
            section_id (str): Target section id.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TelegramMenuWalker._enter_section)
            True
        """
        buttons = await self.tg.inline_buttons(message="last")
        for btn in buttons:
            cb = str(btn.get("callback_data") or "")
            if cb == f"{_SECTION_PREFIX}{section_id}":
                await self.tg.tap_inline(str(btn.get("text") or ""), settle_timeout=6.0)
                return
        # `tap_inline` matches on visible button text, so passing a raw callback
        # string here never matched — it only produced a confusing "no button
        # labelled cfg:section:x" error. Say what actually went wrong instead.
        visible = ", ".join(sorted(str(b.get("text") or "") for b in buttons)) or "<none>"
        msg = (
            f"section {section_id!r} not reachable from the current screen; "
            f"visible buttons: {visible}"
        )
        raise RecipeError(msg)

    async def _walk_section(self, section_id: str) -> None:
        """Tap every actionable row on ``section_id`` and record verdicts.

        Args:
            section_id (str): Section being walked.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TelegramMenuWalker._walk_section)
            True
        """
        if self.out_dir is not None:
            shot = self.out_dir / "screens" / f"{section_id.replace(':', '_')}.png"
            shot.parent.mkdir(parents=True, exist_ok=True)
            with contextlib.suppress(Exception):
                await self.tg._page.screenshot(shot)
        buttons = await self.tg.inline_buttons(message="last")
        for btn in buttons:
            await self._tap_button(btn, section_id=section_id)

    async def _tap_button(self, btn: dict[str, Any], *, section_id: str) -> None:
        """Tap one inline button and record its verdict.

        Args:
            btn (dict[str, Any]): Inline button metadata from Telegram Web.
            section_id (str): Active section id.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TelegramMenuWalker._tap_button)
            True
        """
        row = classify_row_from_button({**btn, "callback_data": btn.get("callback_data") or ""})
        cb = row.callback_data
        if cb in _CHROME_CALLBACKS or is_nav_chrome_callback(cb):
            return
        if cb.startswith(_SECTION_PREFIX):
            return
        if self.deny.search(cb):
            if row.spec_id:
                self.skipped_spec_ids[row.spec_id] = "destructive"
            self._record_row(section_id, row, Verdict.SKIPPED, reason="destructive")
            return
        if row.row_kind == "url":
            url = row.url or str(btn.get("url") or "")
            parsed = urlparse(url)
            ok = bool(parsed.scheme in {"http", "https"} and parsed.netloc)
            verdict = Verdict.OK if ok else Verdict.ERROR
            self._record_row(section_id, row, verdict, detail=url)
            if row.spec_id:
                self.visited_spec_ids.add(row.spec_id)
            return
        if row.row_kind in {"toggle", "cycle"}:
            if self.safe:
                if row.spec_id:
                    self.skipped_spec_ids[row.spec_id] = "mutate_only"
                self._record_row(section_id, row, Verdict.SKIPPED, reason="mutate_only")
                return
            await self._mutate_and_restore(btn, row, section_id=section_id)
            return
        label = str(btn.get("text") or cb or "button")
        before = {
            "signature": await self.tg.screen_signature(),
            "message_count": await self.tg._message_count(),
        }
        raw_count = before.get("message_count", 0)
        before_count = raw_count if isinstance(raw_count, int) else 0
        try:
            outcome = await self.tg.tap_inline(label, settle_timeout=6.0)
        except RecipeError as exc:
            self._record_row(section_id, row, Verdict.ERROR, detail=str(exc))
            return
        after = {
            "signature": outcome.get("new_signature") or before["signature"],
            "message_count": before_count + (1 if outcome.get("new_message") else 0),
        }
        verdict = classify_outcome(
            before,
            after,
            outcome.get("toast"),
            row_kind=row.row_kind,
        )
        if row.row_kind == "form" and self.safe and verdict == Verdict.OK:
            await self._cancel_form()
        self._record_row(section_id, row, verdict, detail=outcome.get("toast"))
        if row.spec_id:
            if verdict == Verdict.SKIPPED:
                self.skipped_spec_ids[row.spec_id] = "skipped"
            else:
                self.visited_spec_ids.add(row.spec_id)

    async def _mutate_and_restore(
        self,
        btn: dict[str, Any],
        row: MenuRow,
        *,
        section_id: str,
    ) -> None:
        """Tap a toggle/cycle row in ``--mutate`` mode, then restore it (D7).

        Previously this path returned without tapping *and* without recording a
        skip, so every toggle spec landed in neither ``visited_spec_ids`` nor
        ``skipped_spec_ids`` and ``assert_spec_coverage`` failed the whole run.

        Restore works off the callback itself: a toggle/cycle button encodes the
        value the *next* tap would apply, so the original state is back exactly
        when the row's ``callback_data`` matches what it was before the first tap.

        Args:
            btn (dict[str, Any]): Inline button metadata from Telegram Web.
            row (MenuRow): Classified row metadata.
            section_id (str): Active section id.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TelegramMenuWalker._mutate_and_restore)
            True
        """
        original_cb = row.callback_data
        target = _mutation_target(original_cb)
        label = str(btn.get("text") or original_cb or "button")
        before = {
            "signature": await self.tg.screen_signature(),
            "message_count": await self.tg._message_count(),
        }
        raw_count = before.get("message_count", 0)
        before_count = raw_count if isinstance(raw_count, int) else 0
        try:
            outcome = await self.tg.tap_inline(label, settle_timeout=6.0)
        except RecipeError as exc:
            self._record_row(section_id, row, Verdict.ERROR, detail=str(exc))
            if row.spec_id:
                self.visited_spec_ids.add(row.spec_id)
            return
        after = {
            "signature": outcome.get("new_signature") or before["signature"],
            "message_count": before_count + (1 if outcome.get("new_message") else 0),
        }
        verdict = classify_outcome(before, after, outcome.get("toast"), row_kind=row.row_kind)
        restored = await self._restore_mutation(target, original_cb)
        detail = outcome.get("toast")
        if not restored:
            verdict = Verdict.ERROR
            detail = f"could not restore {target or original_cb!r} to its original value"
        self._record_row(section_id, row, verdict, detail=detail)
        if row.spec_id:
            self.visited_spec_ids.add(row.spec_id)

    async def _restore_mutation(self, target: str, original_cb: str) -> bool:
        """Re-tap a toggle/cycle row until its callback matches ``original_cb``.

        Args:
            target (str): Dot-path the row mutates (``channels.telegram.dm_policy``).
            original_cb (str): Callback the row carried before the first tap.

        Returns:
            bool: ``True`` when the row is back to its original value.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TelegramMenuWalker._restore_mutation)
            True
        """
        if not target:
            return False
        for _ in range(_MAX_RESTORE_TAPS):
            try:
                buttons = await self.tg.inline_buttons(message="last")
            except RecipeError:
                return False
            match = next(
                (
                    b
                    for b in buttons
                    if _mutation_target(str(b.get("callback_data") or "")) == target
                ),
                None,
            )
            if match is None:
                return False
            if str(match.get("callback_data") or "") == original_cb:
                return True
            try:
                await self.tg.tap_inline(str(match.get("text") or ""), settle_timeout=6.0)
            except RecipeError:
                return False
        return False

    async def _cancel_form(self) -> None:
        """Send ``/cancel`` to close an opened form prompt (D8).

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TelegramMenuWalker._cancel_form)
            True
        """
        with contextlib.suppress(RecipeError):
            await self.tg.tap_inline("/cancel", settle_timeout=3.0)

    def _record_row(
        self,
        section_id: str,
        row: MenuRow,
        verdict: Verdict,
        *,
        detail: str | None = None,
        reason: str | None = None,
    ) -> None:
        """Append one row verdict to the in-memory walk log.

        Args:
            section_id (str): Section id for the row.
            row (MenuRow): Classified row metadata.
            verdict (Verdict): Row outcome.
            detail (str | None): Optional detail (toast text, error, url).
            reason (str | None): Optional skip reason.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(TelegramMenuWalker._record_row)
            True
        """
        entry = {
            "section": section_id,
            "label": row.label,
            "callback": row.callback_data,
            "row_kind": row.row_kind,
            "spec_id": row.spec_id,
            "verdict": verdict.value,
            "detail": detail,
            "skip_reason": reason,
            "ts": datetime.now(tz=UTC).isoformat(),
        }
        self.rows.append(entry)
        self._log_lines.append(json.dumps(entry, sort_keys=True))

    def _reconcile_skipped_specs(self) -> None:
        """Mark spec ids that were not tapped but are exempt from coverage (D9).

        Examples:
            >>> walker = TelegramMenuWalker.__new__(TelegramMenuWalker)
            >>> walker.workspace = __import__('sevn.config.workspace_config', fromlist=['WorkspaceConfig']).WorkspaceConfig.minimal()
            >>> walker.visited_spec_ids = set()
            >>> walker.skipped_spec_ids = {}
            >>> walker._reconcile_skipped_specs()
            >>> isinstance(walker.skipped_spec_ids, dict)
            True
        """
        rendered: set[str] = set()
        for node in expected_tree(workspace=self.workspace):
            for row in node.rows:
                for btn in row:
                    cb = str(btn.get("callback_data") or "")
                    if cb:
                        rendered.add(cb)
        for spec in MENU_BUTTON_SPECS:
            sid = spec.spec_id
            if sid in self.visited_spec_ids or sid in self.skipped_spec_ids:
                continue
            if DEFAULT_DENY.search(spec.callback_pattern):
                self.skipped_spec_ids[sid] = "destructive"
                continue
            if not spec.implemented:
                self.skipped_spec_ids[sid] = "not_implemented"
                continue
            if "cfg:nav:" in spec.callback_pattern or "cfg:section:" in spec.callback_pattern:
                self.skipped_spec_ids[sid] = "nav_or_section"
                continue
            if _is_mutation_pattern(spec.callback_pattern):
                # In --safe these are skipped by design. In --mutate they are
                # tapped, so anything still unaccounted for here was never
                # rendered on a reachable screen — record that, don't silently
                # leave it out of both sets and fail coverage.
                self.skipped_spec_ids[sid] = "mutate_only" if self.safe else "not_in_tree"
                continue
            matched_rendered = any(
                (m := match_menu_button_spec(cb)) is not None and m.spec_id == sid
                for cb in rendered
            )
            if not matched_rendered:
                self.skipped_spec_ids[sid] = "not_in_tree"

    def _build_report(self) -> dict[str, Any]:
        """Build the structured walk report dict.

        Returns:
            dict[str, Any]: Report payload with ``summary`` and ``rows``.

        Examples:
            >>> walker = TelegramMenuWalker.__new__(TelegramMenuWalker)
            >>> walker.rows = []
            >>> walker.visited_spec_ids = set()
            >>> walker.skipped_spec_ids = {}
            >>> walker._build_report()["summary"]["total_rows"]
            0
        """
        summary = {
            verdict.value: sum(1 for r in self.rows if r["verdict"] == verdict.value)
            for verdict in Verdict
        }
        summary["visited"] = len(self.visited_spec_ids)
        summary["skipped_specs"] = len(self.skipped_spec_ids)
        summary["total_rows"] = len(self.rows)
        return {
            "summary": summary,
            "rows": self.rows,
            "visited_spec_ids": sorted(self.visited_spec_ids),
            "skipped_spec_ids": dict(self.skipped_spec_ids),
        }

    def _write_evidence(self, report: dict[str, Any]) -> None:
        """Write ``report.json``, ``report.md``, and ``walk.log`` under ``out_dir`` (D10).

        Args:
            report (dict[str, Any]): Walk report from :meth:`_build_report`.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(TelegramMenuWalker._write_evidence)
            True
        """
        if self.out_dir is None:
            return
        out_dir = self.out_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        md_lines = ["| Section | Label | Verdict | Callback |", "|---|---|---|---|"]
        for row in self.rows:
            md_lines.append(
                f"| {row['section']} | {row['label']} | {row['verdict']} | {row['callback']} |"
            )
        (out_dir / "report.md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")
        (out_dir / "walk.log").write_text("\n".join(self._log_lines) + "\n", encoding="utf-8")


async def _resolve_work_page(
    session: Any,
    content_root: Path,
    session_id: str,
) -> tuple[Any, Any]:
    """Return ``(Page, Dom)`` for the active tab, opening Telegram Web when needed.

    Args:
        session (Any): Active CDP browser session.
        content_root (Path): Workspace content root.
        session_id (str): Gateway session id.

    Returns:
        tuple[Any, Any]: ``(Page, Dom)`` bound to the resolved tab.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_resolve_work_page)
        True
    """
    from sevn.browser.element import Dom
    from sevn.browser.page import Page
    from sevn.browser.recipes.telegram_web import TELEGRAM_WEB_URL
    from sevn.browser.registry import read_registry

    reg = read_registry(content_root, session_id)
    active_id = reg.active_target_id if reg is not None else None
    pages = await session.page_targets()
    page_ids = {str(item.get("targetId")) for item in pages}
    target_id = active_id if active_id and active_id in page_ids else None
    if not target_id and pages:
        target_id = str(pages[-1].get("targetId"))
    if not target_id:
        row = await session.open_tab(TELEGRAM_WEB_URL)
        target_id = str(row.get("target_id") or "")
    if not target_id:
        msg = "no open browser tab (NO_CDP or TAB_NOT_FOUND)"
        raise RecipeError(msg)
    cdp_session = await session.session_for(target_id)
    return Page(cdp_session), Dom(cdp_session)


async def run_menu_walk(
    *,
    chat: str,
    content_root: Path,
    session_id: str = "telegram-menu-e2e",
    safe: bool = True,
    profile_dir: Path | None = None,
    login_timeout: float = 300.0,
    out: Path | None = None,
    max_depth: int = 4,
) -> dict[str, Any]:
    """Bring up Chrome, log into Telegram Web, and walk the ``/config`` menu.

    Args:
        chat (str): Bot @username or chat title.
        content_root (Path): Workspace content root for browser lifecycle.
        session_id (str): Browser session id.
        safe (bool): Safe mode (no toggle/cycle mutations).
        profile_dir (Path | None): Reserved Chrome profile override.
        login_timeout (float): Login poll timeout in seconds.
        out (Path | None): Evidence output directory.
        max_depth (int): Reserved max DFS depth.

    Returns:
        dict[str, Any]: Walk report from :meth:`TelegramMenuWalker.walk`.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(run_menu_walk)
        True
    """
    from sevn.browser import HAS_CDP
    from sevn.browser.lifecycle import get_or_create_session, release_session

    if not HAS_CDP:
        msg = "browser engine missing — run: uv sync --extra browser-cdp"
        raise RecipeError(msg)

    validate_mutate_guards(safe=safe, workspace_root=content_root)
    _ = profile_dir  # lifecycle uses workspace browser profile; reserved for CLI flag
    _ = max_depth
    session = await get_or_create_session(content_root, session_id)
    try:
        page, dom = await _resolve_work_page(session, content_root, session_id)
        tg = TelegramWeb(page, dom)
        await ensure_login(tg, timeout_s=login_timeout)
        await tg.open_chat(chat)
        evidence_dir = out
        if evidence_dir is None:
            ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
            evidence_dir = Path("evidence/telegram-menu-e2e") / ts
        walker = TelegramMenuWalker(
            tg=tg,
            safe=safe,
            out_dir=evidence_dir,
            max_depth=max_depth,
        )
        return await walker.walk()
    finally:
        await release_session(session_id)


__all__ = [
    "DEFAULT_DENY",
    "CoverageError",
    "MenuRow",
    "MenuTreeNode",
    "TelegramMenuWalker",
    "Verdict",
    "assert_spec_coverage",
    "classify_outcome",
    "classify_row",
    "classify_row_from_button",
    "ensure_login",
    "expected_tree",
    "max_leaf_depth_from_root",
    "row_verdict_for_skip",
    "run_menu_walk",
    "validate_mutate_guards",
]
