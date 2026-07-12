#!/usr/bin/env python3
"""Static gate: Telegram menu completeness + TMF registry sync.

Builds keyboards from :mod:`sevn.gateway.menu`, :mod:`sevn.gateway.dashboard_pin`,
:mod:`sevn.channels.telegram`, and :mod:`sevn.gateway.telegram_quick_actions`, then asserts:

* No ``Coming soon`` stubs; every inline button has ``callback_data`` or ``url``.
* Config/menu action callbacks parse via existing parsers.
* Rendered ``callback_data`` rows match :mod:`sevn.gateway.menu_registry` and only
  ``implemented=True`` specs appear (nav chrome and section tiles exempt).
* Forbidden NOOP patterns: section self-loops, ``cfg:shortcuts``, unparsed shortcuts.

Emits ``reports/telegram-menu-gap.json`` and exits **1** when violations remain.

Module: scripts.check_telegram_menu
Depends: json, pathlib, sys, tempfile, typing

Exports:
    Violation — one menu completeness violation.
    collect_violations — scan all rendered keyboards.
    build_gap_report — machine-readable gap snapshot.
    main — CLI entry; writes JSON report and returns exit code.

Examples:
    >>> isinstance(REPO, Path)
    True
"""

from __future__ import annotations

import json
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, get_args

from sevn.channels.telegram import build_reply_keyboard_markup
from sevn.config.workspace_config import WorkspaceConfig
from sevn.gateway.commands.menu_action_router import parse_action_callback
from sevn.gateway.dashboard_pin import default_pin_keyboard
from sevn.gateway.menu import (
    _EMPTY_TOOL_SURFACE,
    ConfigSection,
    MenuSection,
    build_config_menu_keyboard,
    build_menu_keyboard,
    model_picker_slot_keys,
    parse_config_callback_data,
    parse_menu_callback_data,
    parse_models_callback_data,
)
from sevn.gateway.menu_registry import (
    is_nav_chrome_callback,
    is_section_tile_callback,
    match_menu_button_spec,
    registry_implementation_counts,
)
from sevn.gateway.telegram_quick_actions import (
    build_quick_action_inline_keyboard,
    parse_qa_callback_data,
)

REPO = Path(__file__).resolve().parents[1]
GAP_REPORT = REPO / "reports" / "telegram-menu-gap.json"

ALL_CONFIG_SECTIONS: tuple[ConfigSection, ...] = get_args(ConfigSection)
ALL_MENU_SECTIONS: tuple[MenuSection, ...] = get_args(MenuSection)

KeyboardSource = Literal[
    "config",
    "menu",
    "pin",
    "qa_bar",
]


@dataclass(frozen=True)
class Violation:
    """One Telegram menu completeness or registry violation."""

    source: str
    section: str
    button_text: str
    violation: str
    callback_data: str | None = None
    url: str | None = None


def _iter_buttons(keyboard: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten inline-keyboard button dicts from a ``reply_markup`` payload.

    Args:
        keyboard (dict[str, Any]): Keyboard builder return value.

    Returns:
        list[dict[str, Any]]: Button dicts in row-major order.

    Examples:
        >>> _iter_buttons({"inline_keyboard": [[{"text": "A", "callback_data": "cfg:nav:home"}]]})
        [{'text': 'A', 'callback_data': 'cfg:nav:home'}]
    """
    rows = keyboard.get("inline_keyboard")
    if not isinstance(rows, list):
        return []
    buttons: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, list):
            continue
        for btn in row:
            if isinstance(btn, dict):
                buttons.append(btn)
    return buttons


def _is_self_loop_callback(callback_data: str, *, active_section: str) -> bool:
    """Return whether ``callback_data`` navigates to the same section (NOOP).

    Args:
        callback_data (str): Telegram inline ``callback_data``.
        active_section (str): Active config or menu section id.

    Returns:
        bool: ``True`` when the callback is a section self-loop.

    Examples:
        >>> _is_self_loop_callback("menu:section:identity", active_section="identity")
        True
        >>> _is_self_loop_callback("cfg:section:voice", active_section="session")
        False
    """
    stripped = callback_data.strip()
    for prefix in ("cfg:section:", "menu:section:"):
        if stripped == f"{prefix}{active_section}":
            return True
    return False


def _check_parsed_callback(
    callback_data: str,
    *,
    source: KeyboardSource,
    section: str,
    button_text: str,
    violations: list[Violation],
) -> None:
    """Append parse violations when config/action parsers reject ``callback_data``.

    Args:
        callback_data (str): Raw callback payload.
        source (KeyboardSource): Keyboard builder origin label.
        section (str): Active section id.
        button_text (str): Button label text.
        violations (list[Violation]): Accumulator (mutated in place).

    Returns:
        None: Mutates *violations* only.

    Examples:
        >>> v: list[Violation] = []
        >>> _check_parsed_callback("cfg:nav:home", source="config", section="session", button_text="Home", violations=v)
        >>> v
        []
    """
    if parse_config_callback_data(callback_data) is not None:
        return
    if parse_menu_callback_data(callback_data) is not None:
        return
    if parse_qa_callback_data(callback_data) is not None:
        return
    if parse_models_callback_data(callback_data) is not None:
        return
    if parse_action_callback(callback_data) is None:
        violations.append(
            Violation(
                source=source,
                section=section,
                button_text=button_text,
                violation="unparsed_action_callback",
                callback_data=callback_data,
            ),
        )


def _check_registry_callback(
    callback_data: str,
    *,
    source: KeyboardSource,
    section: str,
    button_text: str,
    violations: list[Violation],
) -> None:
    """Append registry violations for unregistered or not-implemented callbacks.

    Args:
        callback_data (str): Raw callback payload.
        source (KeyboardSource): Keyboard builder origin label.
        section (str): Active section id.
        button_text (str): Button label text.
        violations (list[Violation]): Accumulator (mutated in place).

    Returns:
        None: Mutates *violations* only.

    Examples:
        >>> v: list[Violation] = []
        >>> _check_registry_callback(
        ...     "cfg:section:session",
        ...     source="config",
        ...     section="root",
        ...     button_text="Session",
        ...     violations=v,
        ... )
        >>> v
        []
    """
    stripped = callback_data.strip()
    if stripped == "cfg:shortcuts":
        violations.append(
            Violation(
                source=source,
                section=section,
                button_text=button_text,
                violation="forbidden_unparsed_cfg_shortcuts",
                callback_data=stripped,
            ),
        )
        return
    if is_nav_chrome_callback(stripped) or is_section_tile_callback(stripped):
        return
    spec = match_menu_button_spec(stripped)
    if spec is None:
        violations.append(
            Violation(
                source=source,
                section=section,
                button_text=button_text,
                violation="unregistered_callback",
                callback_data=stripped,
            ),
        )
        return
    if not spec.implemented:
        violations.append(
            Violation(
                source=source,
                section=section,
                button_text=button_text,
                violation="not_implemented_in_keyboard",
                callback_data=stripped,
            ),
        )


def _scan_keyboard(
    keyboard: dict[str, Any],
    *,
    source: KeyboardSource,
    section: str,
    violations: list[Violation],
) -> None:
    """Scan one inline keyboard for completeness, parse, and registry rules.

    Args:
        keyboard (dict[str, Any]): ``reply_markup``-shaped dict.
        source (KeyboardSource): Builder origin label.
        section (str): Active section id for self-loop detection.
        violations (list[Violation]): Accumulator (mutated in place).

    Returns:
        None: Mutates *violations* only.

    Examples:
        >>> v: list[Violation] = []
        >>> _scan_keyboard(
        ...     {"inline_keyboard": [[{"text": "Home", "callback_data": "cfg:nav:home"}]]},
        ...     source="config",
        ...     section="session",
        ...     violations=v,
        ... )
        >>> v
        []
    """
    for btn in _iter_buttons(keyboard):
        text = str(btn.get("text", ""))
        callback_data = btn.get("callback_data")
        url = btn.get("url")
        cb = callback_data if isinstance(callback_data, str) else None
        link = url if isinstance(url, str) else None

        if text == "Coming soon":
            violations.append(
                Violation(
                    source=source,
                    section=section,
                    button_text=text,
                    violation="coming_soon_stub",
                    callback_data=cb,
                    url=link,
                ),
            )
            continue

        if not cb and not link:
            violations.append(
                Violation(
                    source=source,
                    section=section,
                    button_text=text,
                    violation="missing_callback_or_url",
                    callback_data=cb,
                    url=link,
                ),
            )
            continue

        if link:
            continue

        assert cb is not None
        if _is_self_loop_callback(cb, active_section=section):
            violations.append(
                Violation(
                    source=source,
                    section=section,
                    button_text=text,
                    violation="self_loop_callback",
                    callback_data=cb,
                ),
            )
        _check_parsed_callback(
            cb,
            source=source,
            section=section,
            button_text=text,
            violations=violations,
        )
        _check_registry_callback(
            cb,
            source=source,
            section=section,
            button_text=text,
            violations=violations,
        )


def collect_violations(
    workspace: WorkspaceConfig,
    *,
    content_root: Path,
) -> list[Violation]:
    """Scan every rendered Telegram control keyboard for violations.

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings for keyboard build.
        content_root (Path): Workspace content root (Shortcuts section rows).

    Returns:
        list[Violation]: All violations found across surfaces.

    Examples:
        >>> ws = WorkspaceConfig(schema_version=1, web_ui={"url": "https://app.example/"})
        >>> with tempfile.TemporaryDirectory() as tmp:
        ...     v = collect_violations(ws, content_root=Path(tmp))
        >>> isinstance(v, list)
        True
    """
    violations: list[Violation] = []

    for section in ALL_CONFIG_SECTIONS:
        keyboard = build_config_menu_keyboard(
            workspace,
            section=section,
            content_root=content_root,
            user_id="check",
            is_owner=True,
        )
        _scan_keyboard(keyboard, source="config", section=section, violations=violations)
        if section == "models":
            for slot_key in model_picker_slot_keys():
                picker_kb = build_config_menu_keyboard(
                    workspace,
                    section="models",
                    content_root=content_root,
                    user_id="check",
                    is_owner=True,
                    models_picker_slot=slot_key,
                    models_picker_page=0,
                )
                _scan_keyboard(
                    picker_kb,
                    source="config",
                    section=f"models_picker_{slot_key}",
                    violations=violations,
                )

    for section in ALL_MENU_SECTIONS:
        keyboard = build_menu_keyboard(
            workspace,
            tool_set=_EMPTY_TOOL_SURFACE,
            section=section,
        )
        _scan_keyboard(keyboard, source="menu", section=section, violations=violations)

    _scan_keyboard(default_pin_keyboard(), source="pin", section="pin", violations=violations)

    qa_keyboard = build_quick_action_inline_keyboard(
        42,
        workspace=workspace,
    )
    _scan_keyboard(qa_keyboard, source="qa_bar", section="qa_bar", violations=violations)

    # Reply keyboard (surface A) uses text labels only — registry inventory, no callbacks.
    _ = build_reply_keyboard_markup()

    return violations


def build_gap_report(
    workspace: WorkspaceConfig,
    *,
    content_root: Path,
) -> dict[str, Any]:
    """Build machine-readable gap snapshot for Telegram menu gates.

    Args:
        workspace (WorkspaceConfig): Parsed workspace settings for keyboard build.
        content_root (Path): Workspace content root (Shortcuts section rows).

    Returns:
        dict[str, Any]: Report payload written to ``reports/telegram-menu-gap.json``.

    Examples:
        >>> ws = WorkspaceConfig(schema_version=1, web_ui={"url": "https://app.example/"})
        >>> with tempfile.TemporaryDirectory() as tmp:
        ...     report = build_gap_report(ws, content_root=Path(tmp))
        >>> "violations" in report
        True
    """
    violations = collect_violations(workspace, content_root=content_root)
    counts = registry_implementation_counts()
    return {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "registry": counts,
        "config_sections_checked": len(ALL_CONFIG_SECTIONS),
        "menu_sections_checked": len(ALL_MENU_SECTIONS),
        "total_violation_count": len(violations),
        "violations": [asdict(v) for v in violations],
    }


def main() -> int:
    """Write gap JSON and fail when Telegram menu checks fail.

    Returns:
        int: ``0`` only when ``total_violation_count`` is zero.

    Examples:
        >>> main() in (0, 1)
        True
    """
    workspace = WorkspaceConfig.minimal(
        web_ui={"url": "https://app.example/mission-control"},
    )
    with tempfile.TemporaryDirectory(prefix="sevn-telegram-menu-check-") as tmp:
        report = build_gap_report(workspace, content_root=Path(tmp))
    GAP_REPORT.parent.mkdir(parents=True, exist_ok=True)
    GAP_REPORT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    total = int(report["total_violation_count"])
    reg = report.get("registry", {})
    print(
        f"telegram-menu-check: {total} violation(s); registry "
        f"{reg.get('implemented', '?')}/{reg.get('total', '?')} implemented "
        f"-> {GAP_REPORT.relative_to(REPO)}",
        file=sys.stderr,
    )
    if total:
        for item in report["violations"]:
            print(
                f"  [{item['source']}/{item['section']}] {item['violation']}: "
                f"{item['button_text']!r} callback={item['callback_data']!r}",
                file=sys.stderr,
            )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
