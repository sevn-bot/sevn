"""Sub-agent operator surfaces shared by slash commands and Telegram menus (D6/D7).

Module: sevn.gateway.subagents.surfaces
Depends: sevn.gateway.mission.mission_subagents_snapshot

Exports:
    subagent_menu_snapshot_from_router — live L1/L2 counts and serialized rows.
    format_running_agents_inventory — rich ``/agents`` inventory formatter.
    build_stop_l1_keyboard — ``/stop`` L1 kill picker inline keyboard.
    build_subagent_kill_keyboard_rows — shared kill rows for Config Running and ``/stop``.
    subagent_kill_button_label_config — Config→Running kill button labels.
    stop_l1_button_label — ``/stop`` picker kill button labels.
    STOP_L1_PICKER_COPY / STOP_L1_OWNER_ONLY_COPY — ``/stop`` picker message bodies.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sevn.gateway.channel_router import ChannelRouter

STOP_L1_PICKER_COPY = "Select a level-1 agent to stop, or ALL to stop every L1 run."
STOP_L1_OWNER_ONLY_COPY = "Running level-1 agents. Kill controls are owner-only."

_AGENTS_EMPTY_COPY = "No agents running."
_AGENTS_INVENTORY_DETAIL_CAP = 12


def subagent_kill_button_label_config(row: dict[str, Any]) -> str:
    """Label for Config→Sub-agents Running kill rows.

    Args:
        row (dict[str, Any]): Serialized running row (id/role/level).

    Returns:
        str: Telegram inline button label.

    Examples:
        >>> subagent_kill_button_label_config(
        ...     {"id": "a1", "role": "tier_b", "level": 1},
        ... )
        'Kill a1 L1 tier_b'
    """
    run_id = str(row.get("id", "")).strip()
    role = str(row.get("role", "?"))
    level = row.get("level", "?")
    return f"Kill {run_id} L{level} {role}"


def stop_l1_button_label(row: dict[str, Any]) -> str:
    """Label for ``/stop`` picker rows: short id + role + truncated task summary (D7).

    Args:
        row (dict[str, Any]): Serialized level-1 running row.

    Returns:
        str: Telegram inline button label.

    Examples:
        >>> stop_l1_button_label(
        ...     {"id": "a1", "role": "tier_b", "level": 1, "task_summary": "slow job"},
        ... )
        'a1 tier_b slow job'
    """
    run_id = str(row.get("id", "")).strip()
    role = str(row.get("role", "?"))
    summary = " ".join(str(row.get("task_summary", "")).split())
    if len(summary) > 20:
        summary = summary[:19].rstrip() + "…"
    parts = [run_id, role]
    if summary:
        parts.append(summary)
    return " ".join(parts)


def build_subagent_kill_keyboard_rows(
    rows: Sequence[dict[str, Any]],
    *,
    is_owner: bool,
    label_for_row: Callable[[dict[str, Any]], str],
    kill_all_label: str,
    max_buttons: int = 8,
) -> list[list[dict[str, Any]]]:
    """Build owner-only kill inline rows shared by Config Running and ``/stop`` (D7/D11).

    Args:
        rows (Sequence[dict[str, Any]]): Serialized running rows to expose as kill targets.
        is_owner (bool): When ``False``, omit kill buttons.
        label_for_row (Callable[[dict[str, Any]], str]): Per-row button label builder.
        kill_all_label (str): Text for the ``act:subagents:kill_all`` button.
        max_buttons (int): Maximum per-run kill buttons before the ALL row.

    Returns:
        list[list[dict[str, Any]]]: Inline keyboard rows (no nav chrome).

    Examples:
        >>> build_subagent_kill_keyboard_rows(
        ...     ({"id": "a1", "role": "tier_b", "level": 1},),
        ...     is_owner=True,
        ...     label_for_row=subagent_kill_button_label_config,
        ...     kill_all_label="Kill all L1",
        ... )[0][0]["callback_data"]
        'act:subagents:kill:a1'
    """
    keyboard: list[list[dict[str, Any]]] = []
    if rows and is_owner:
        for row in rows[:max_buttons]:
            run_id = str(row.get("id", "")).strip()
            if not run_id:
                continue
            keyboard.append(
                [
                    {
                        "text": label_for_row(row),
                        "callback_data": f"act:subagents:kill:{run_id}",
                    },
                ],
            )
        keyboard.append(
            [
                {
                    "text": kill_all_label,
                    "callback_data": "act:subagents:kill_all",
                },
            ],
        )
    return keyboard


def build_stop_l1_keyboard(
    running_rows: Sequence[dict[str, Any]],
    *,
    is_owner: bool,
) -> dict[str, Any]:
    """Build ``/stop`` inline keyboard for active level-1 runs (D7/D11).

    Args:
        running_rows (Sequence[dict[str, Any]]): Serialized registry rows.
        is_owner (bool): When ``False``, omit kill buttons.

    Returns:
        dict[str, Any]: ``reply_markup``-shaped dict for outbound metadata.

    Examples:
        >>> kb = build_stop_l1_keyboard(
        ...     ({"id": "a1", "role": "tier_b", "level": 1, "task_summary": "slow"},),
        ...     is_owner=True,
        ... )
        >>> kb["inline_keyboard"][-1][0]["callback_data"]
        'act:subagents:kill_all'
    """
    l1_rows = sorted(
        (row for row in running_rows if row.get("level") == 1),
        key=lambda row: str(row.get("id", "")),
    )
    inline = build_subagent_kill_keyboard_rows(
        l1_rows,
        is_owner=is_owner,
        label_for_row=stop_l1_button_label,
        kill_all_label="ALL",
    )
    return {"inline_keyboard": inline}


async def subagent_menu_snapshot_from_router(
    router: ChannelRouter | None,
) -> tuple[int, int, tuple[dict[str, Any], ...]]:
    """Fetch live sub-agent counts and running rows for Telegram menu captions.

    Args:
        router (ChannelRouter | None): Gateway router (may lack supervisor when unwired).

    Returns:
        tuple[int, int, tuple[dict[str, Any], ...]]: ``(level1_count, level2_count, running_rows)``.

    Examples:
        >>> import asyncio
        >>> asyncio.run(subagent_menu_snapshot_from_router(None))
        (0, 0, ())
    """
    if router is None:
        return 0, 0, ()
    supervisor = getattr(router, "_subagent_supervisor", None)
    if supervisor is None:
        return 0, 0, ()
    from sevn.gateway.mission.mission_subagents_snapshot import _serialize_subagent_run

    counts_map = await supervisor.registry.counts()
    level1 = sum(count for (level, _role), count in counts_map.items() if level == 1)
    level2 = sum(count for (level, _role), count in counts_map.items() if level == 2)
    runs = await supervisor.registry.running()
    rows = tuple(
        _serialize_subagent_run(run)
        for run in sorted(runs, key=lambda row: (row.level, row.role, row.id))
    )
    return level1, level2, rows


def format_running_agents_inventory(
    rows: Sequence[dict[str, Any]],
    *,
    max_detail: int = _AGENTS_INVENTORY_DETAIL_CAP,
) -> str:
    """Format live L1/L2 sub-agent runs for ``/agents`` and operator surfaces (D6).

    Groups level-2 rows under their ``parent_id`` L1. Caps full detail blocks and
    summarizes overflow when many runs are active.

    Args:
        rows (Sequence[dict[str, Any]]): Serialized registry rows (see
            ``_serialize_subagent_run``).
        max_detail (int): Maximum number of full per-run lines before overflow copy.

    Returns:
        str: Rich plain-text inventory, or empty-state copy when no runs are active.

    Examples:
        >>> format_running_agents_inventory(())
        'No agents running.'
        >>> body = format_running_agents_inventory([
        ...     {"id": "a1", "level": 1, "role": "tier_b", "parent_id": None,
        ...      "task_summary": "parent", "status": "running", "age_s": 1.0},
        ...     {"id": "b2", "level": 2, "role": "tier_b", "parent_id": "a1",
        ...      "task_summary": "child", "status": "running", "age_s": 0.5},
        ... ])
        >>> "a1" in body and body.index("a1") < body.index("b2")
        True
    """
    if not rows:
        return _AGENTS_EMPTY_COPY

    cap = max(1, int(max_detail))
    l1_rows = sorted(
        (row for row in rows if row.get("level") == 1),
        key=lambda row: str(row.get("id", "")),
    )
    l2_by_parent: dict[str, list[dict[str, Any]]] = {}
    orphan_l2: list[dict[str, Any]] = []
    for row in rows:
        if row.get("level") != 2:
            continue
        parent_id = row.get("parent_id")
        if isinstance(parent_id, str) and parent_id.strip():
            l2_by_parent.setdefault(parent_id, []).append(row)
        else:
            orphan_l2.append(row)
    for child_rows in l2_by_parent.values():
        child_rows.sort(key=lambda row: str(row.get("id", "")))
    orphan_l2.sort(key=lambda row: str(row.get("id", "")))

    def _format_line(row: dict[str, Any], *, indent: str = "") -> str:
        run_id = str(row.get("id", "?"))
        level = row.get("level", "?")
        status = row.get("status", "?")
        role = row.get("role", "")
        summary = row.get("task_summary", "")
        age = row.get("age_s")
        elapsed = f"{float(age):.0f}s" if isinstance(age, (int, float)) else "?"
        return f"{indent}• {run_id} L{level} [{status}] {role} ({elapsed}) — {summary!r}"

    lines = ["Running agents:", ""]
    detail_count = 0
    total = len(rows)
    overflow = False

    def _append_row(row: dict[str, Any], *, indent: str = "") -> None:
        nonlocal detail_count, overflow
        if detail_count >= cap:
            overflow = True
            return
        lines.append(_format_line(row, indent=indent))
        detail_count += 1

    for l1 in l1_rows:
        if detail_count >= cap:
            overflow = True
            break
        _append_row(l1)
        for l2 in l2_by_parent.get(str(l1.get("id")), ()):
            if detail_count >= cap:
                overflow = True
                break
            _append_row(l2, indent="  ↳ ")

    for l2 in orphan_l2:
        if detail_count >= cap:
            overflow = True
            break
        _append_row(l2)

    if overflow or detail_count < total:
        remaining = total - detail_count
        if remaining > 0:
            lines.append(f"… and {remaining} more running agent(s).")

    return "\n".join(lines)


__all__ = [
    "STOP_L1_OWNER_ONLY_COPY",
    "STOP_L1_PICKER_COPY",
    "build_stop_l1_keyboard",
    "build_subagent_kill_keyboard_rows",
    "format_running_agents_inventory",
    "stop_l1_button_label",
    "subagent_kill_button_label_config",
    "subagent_menu_snapshot_from_router",
]
