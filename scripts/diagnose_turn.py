#!/usr/bin/env python3
"""Forensic turn reconstructor for gateway.log.

Resolve a turn by free-text message string, message-id, or turn-id, then
reconstruct exactly what the gateway did: triager decision, every round's
tool calls, which of those tool calls *actually dispatched* (registry
``tool_call.finish``) versus were *dropped* (counted in ``round_tools`` but
never reached the dispatcher and later removed by ``strip_orphan_tool_use``),
the final ``b_pass`` outcome, and any grounding/guard fires.

The headline diagnostic is the **dropped-call gap**: tools the model emitted
that never produced a registry result. That is the signature of the MiniMax
native-tool-call converter drop (see plan/heuristics-consolidation-wave-plan.md
and the tier_b MiniMax handling notes).

Module: scripts.diagnose_turn
Depends: argparse, re, pathlib

Exports:
    Turn — Parsed gateway turn with triager, rounds, dispatch, and problems.
    parse — Build a ``turn_id`` → ``Turn`` map from raw log lines.
    resolve — Filter parsed turns by message substring, msg-id, or turn-id.
    report — Render one ``Turn`` as a human-readable diagnostic block.
    main — CLI entry; exits non-zero when no match or log missing.

Examples:
    >>> Turn(turn_id="t1").problems
    []
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_LOG = Path.home() / ".sevn" / "workspace" / "logs" / "gateway.log"

# A loguru line: "<ts> | <LEVEL> | <correlation> | <loc> | <message>"
_LINE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} [\d:.]+\+[\d:]+) \| (?P<level>\w+)\s+\| "
    r"(?P<corr>[^|]*?) \| (?P<loc>[^|]+) \| (?P<msg>.*)$"
)
# turn_id appears as turn_id='X' (structured events) or turn_id=X (registry).
_TURN_Q = re.compile(r"turn_id='([^']+)'")
_TURN_B = re.compile(r"turn_id=([^\s']+)")
# b_pass / summarize lines key the per-turn id off correlation_id= instead.
_CORR = re.compile(r"correlation_id=([^\s']+)")
_EVENT = re.compile(r"event=([\w.]+)")
_TOOL_NAME = re.compile(r"(?:tool_name|name)=['\"]?([\w]+)['\"]?")
_STATUS = re.compile(r"status=(\w+)")
_ROUND_TOOLS = re.compile(r"tool_names=\[([^\]]*)\]")
_INTENT = re.compile(r"intent='([^']*)'")
_FIRST_MSG = re.compile(r"first_message='([^']*)'")
_TOOLS_FIELD = re.compile(r"\btools=\[([^\]]*)\]")
_SKILLS_FIELD = re.compile(r"skills=\[([^\]]*)\]")
_SUCC_TOOLS = re.compile(r"successful_tools=\[([^\]]*)\]")
_FAIL_DETAIL = re.compile(r"failure_detail=(.+?) reason=")
_STRIPPED = re.compile(r"stripped_count=(\d+)")
_DUR = re.compile(r"dur_ms=([\d.]+)")

# Reply phrases that, when emitted by a turn that *did* dispatch tools, indicate
# a false self-report ("I used no tools / I fabricated").
_FALSE_CONFESSION = (
    "no tools",
    "none.",
    "**none**",
    "fabricat",
    "hallucinat",
    "didn't call",
    "did not call",
    "made it up",
    "replay stub",
    "cannot see",
    "can't see",
)


@dataclass
class Turn:
    """One gateway turn reconstructed from structured log events.

    Args:
        turn_id (str): Correlation / turn identifier from log lines.
        intent (str): Triager intent label when present.
        triager_tools (str): Raw ``tools=[...]`` field from triager output.
        triager_skills (str): Raw ``skills=[...]`` field from triager output.
        first_message (str): Triager ``first_message`` when present.
        rounds (list[str]): Per-round ``tool_names`` from ``tier_b.round_tools``.
        dispatched (list[tuple[str, str, str]]): ``(tool, status, dur_ms)`` finishes.
        stripped_events (int): Count of ``strip_orphan_tool_use`` log lines.
        stripped_total (int): Max ``stripped_count`` seen across those events.
        b_pass (str): ``pass/status`` from ``b_pass`` summary when logged.
        succ_tools (str): ``successful_tools=[...]`` from ``b_pass``.
        failure_detail (str): Failure detail string when the turn failed.
        guard_events (list[str]): Grounding/guard event names fired this turn.
        final_text (str): Truncated assistant reply head from ``tier_b.output``.
        user_message (str): User message from ``triager.input``.

    Examples:
        >>> t = Turn(turn_id="x", rounds=["'serp'"])
        >>> t.emitted_tools
        {'serp'}
    """

    turn_id: str
    intent: str = ""
    triager_tools: str = ""
    triager_skills: str = ""
    first_message: str = ""
    rounds: list[str] = field(default_factory=list)  # round_tools per round
    dispatched: list[tuple[str, str, str]] = field(default_factory=list)  # (tool, status, dur)
    stripped_events: int = 0  # number of strip_orphan_tool_use log lines
    stripped_total: int = 0  # max stripped_count seen
    b_pass: str = ""
    succ_tools: str = ""
    failure_detail: str = ""
    guard_events: list[str] = field(default_factory=list)  # fabricated_*, triager_bound_*
    rewritten_tools: list[str] = field(default_factory=list)  # codemode native→run_code rewrites
    final_text: str = ""
    user_message: str = ""

    @property
    def emitted_tools(self) -> set[str]:
        """Return tool names the model emitted across all ``round_tools`` rounds.

        Returns:
            set[str]: Unique tool names parsed from round log lines.

        Examples:
            >>> Turn(turn_id="t", rounds=["'a', 'b'"]).emitted_tools
            {'a', 'b'}
        """
        out: set[str] = set()
        for r in self.rounds:
            for t in r.split(","):
                t = t.strip().strip("'\"")
                if t:
                    out.add(t)
        return out

    @property
    def dispatched_tools(self) -> set[str]:
        """Return tool names that reached the registry dispatcher.

        Returns:
            set[str]: Tool names with a ``tool_call.finish`` log line.

        Examples:
            >>> Turn(turn_id="t", dispatched=[("serp", "ok", "12")]).dispatched_tools
            {'serp'}
        """
        return {t for (t, _s, _d) in self.dispatched}

    @property
    def dropped_tools(self) -> set[str]:
        """Return emitted tools that never produced a registry finish.

        ``run_code`` is excluded because CodeMode inner tools dispatch under
        their own names. A tool that was *rewritten* into ``run_code`` (Layer 1
        recovery, event ``tier_b.codemode_native_call_rewritten``) is also
        excluded — it was recovered, not dropped.

        Returns:
            set[str]: Emitted minus dispatched/rewritten tool names.

        Examples:
            >>> t = Turn(turn_id="t", rounds=["'serp'"], dispatched=[])
            >>> t.dropped_tools
            {'serp'}
            >>> t2 = Turn(turn_id="t", rounds=["'serp'"], rewritten_tools=["serp"])
            >>> t2.dropped_tools
            set()
        """
        emitted = self.emitted_tools - {"run_code"}
        return emitted - self.dispatched_tools - set(self.rewritten_tools)

    @property
    def problems(self) -> list[str]:
        """Return human-readable problem strings for this turn.

        Returns:
            list[str]: Dropped calls, failures, guard fires, false self-reports.

        Examples:
            >>> Turn(turn_id="t", rounds=["'serp'"], dispatched=[]).problems[0]
            "DROPPED native tool calls (emitted, never dispatched): ['serp'] - orphan-stripped 0x"
        """
        out: list[str] = []
        if self.dropped_tools:
            out.append(
                f"DROPPED native tool calls (emitted, never dispatched): "
                f"{sorted(self.dropped_tools)} - orphan-stripped {self.stripped_total}x"
            )
        if self.failure_detail and self.failure_detail != "None":
            out.append(f"TURN FAILED: {self.failure_detail}")
        if self.guard_events:
            out.append(f"GUARD/GROUNDING fired: {sorted(set(self.guard_events))}")
        low = self.final_text.lower()
        if self.dispatched and any(p in low for p in _FALSE_CONFESSION):
            out.append(
                "FALSE SELF-REPORT: reply denies/discredits tool use, but "
                f"{sorted(self.dispatched_tools)} dispatched OK this turn"
            )
        return out


def _turn_of(msg: str) -> str | None:
    """Extract ``turn_id`` or ``correlation_id`` from one log message line.

    Args:
        msg (str): Loguru message body (not the full line).

    Returns:
        str | None: Turn identifier when a known pattern matches.

    Examples:
        >>> _turn_of("event=triager.input turn_id='abc'")
        'abc'
    """
    m = _TURN_Q.search(msg) or _TURN_B.search(msg) or _CORR.search(msg)
    return m.group(1) if m else None


def parse(log_lines: list[str]) -> dict[str, Turn]:
    """Parse gateway log lines into a ``turn_id`` → ``Turn`` map.

    Args:
        log_lines (list[str]): Raw lines from ``gateway.log``.

    Returns:
        dict[str, Turn]: One ``Turn`` per discovered correlation id.

    Examples:
        >>> parse([]) == {}
        True
    """
    turns: dict[str, Turn] = {}

    def get(tid: str) -> Turn:
        if tid not in turns:
            turns[tid] = Turn(turn_id=tid)
        return turns[tid]

    for raw in log_lines:
        m = _LINE.match(raw.rstrip("\n"))
        if not m:
            continue
        msg = m.group("msg")
        tid = _turn_of(msg)
        if not tid:
            continue
        t = get(tid)
        ev = _EVENT.search(msg)
        event = ev.group(1) if ev else ""

        if event == "triager.input":
            cm = re.search(r"current_message='([^']*)'", msg)
            if cm:
                t.user_message = cm.group(1)
        elif event == "triager.output":
            if im := _INTENT.search(msg):
                t.intent = im.group(1)
            if fm := _FIRST_MSG.search(msg):
                t.first_message = fm.group(1)
            if tm := _TOOLS_FIELD.search(msg):
                t.triager_tools = tm.group(1)
            if sm := _SKILLS_FIELD.search(msg):
                t.triager_skills = sm.group(1)
        elif event == "tier_b.round_tools":
            if rm := _ROUND_TOOLS.search(msg):
                t.rounds.append(rm.group(1))
        elif event == "tier_b.strip_orphan_tool_use":
            t.stripped_events += 1
            if sm := _STRIPPED.search(msg):
                t.stripped_total = max(t.stripped_total, int(sm.group(1)))
        elif event == "tier_b.codemode_native_call_rewritten":
            if tm := _TOOL_NAME.search(msg):
                t.rewritten_tools.append(tm.group(1))
        elif event == "tier_b.output":
            ft = re.search(r"first_text='(.*)$", msg)
            if ft:
                t.final_text = ft.group(1)[:4000]
        elif event.startswith("tier_b.") and (
            "fabricat" in event
            or "triager_bound_tools_unused" in event
            or "grounding" in event
            or "guard" in event
        ):
            t.guard_events.append(event)
        elif "tool_call.finish" in msg:
            name = _TOOL_NAME.search(msg)
            status = _STATUS.search(msg)
            dur = _DUR.search(msg)
            if name:
                t.dispatched.append(
                    (
                        name.group(1),
                        status.group(1) if status else "?",
                        dur.group(1) if dur else "?",
                    )
                )
        elif "_log_b_turn_pass" in m.group("loc") or "agent_turn.b_pass" in msg:
            pm = re.search(r"pass=(\w+).*?status=(\w+)", msg)
            if pm:
                t.b_pass = f"{pm.group(1)}/{pm.group(2)}"
            if sm := _SUCC_TOOLS.search(msg):
                t.succ_tools = sm.group(1)
            if fd := _FAIL_DETAIL.search(msg):
                t.failure_detail = fd.group(1).strip()

    return turns


def resolve(
    turns: dict[str, Turn], *, find: str | None, msg_id: str | None, turn_id: str | None
) -> list[Turn]:
    """Filter parsed turns by turn-id, msg-id fragment, or message substring.

    Args:
        turns (dict[str, Turn]): Output of :func:`parse`.
        find (str | None): Case-insensitive substring of user/assistant text.
        msg_id (str | None): Telegram ``msg=<hex>`` fragment inside turn ids.
        turn_id (str | None): Full or partial turn correlation id.

    Returns:
        list[Turn]: Matching turns (may be empty).

    Examples:
        >>> resolve({"t1": Turn(turn_id="t1", user_message="hello")}, find="HELLO")
        [Turn(turn_id='t1', intent='', triager_tools='', triager_skills='', first_message='', rounds=[], dispatched=[], stripped_events=0, stripped_total=0, b_pass='', succ_tools='', failure_detail='', guard_events=[], final_text='', user_message='hello')]
    """
    if turn_id:
        return [turns[k] for k in turns if k == turn_id or turn_id in k]
    if msg_id:
        return [t for k, t in turns.items() if f"msg={msg_id}" in k]
    if find:
        needle = find.lower()
        hits = [
            t
            for t in turns.values()
            if needle in t.user_message.lower()
            or needle in t.first_message.lower()
            or needle in t.final_text.lower()
        ]
        return hits  # noqa: RET504
    return []


def report(t: Turn) -> str:
    """Render one turn as a multi-line diagnostic report.

    Args:
        t (Turn): Turn to summarize.

    Returns:
        str: Human-readable block including problems when present.

    Examples:
        >>> "TURN" in report(Turn(turn_id="demo"))
        True
    """
    lines = [
        "=" * 88,
        f"TURN  {t.turn_id}",
        f"  user said   : {t.user_message!r}",
        f"  intent      : {t.intent}",
        f"  triager gave: tools=[{t.triager_tools}] skills=[{t.triager_skills}]",
        f"  opener      : {t.first_message!r}",
        f"  rounds      : {len(t.rounds)}  emitted={sorted(t.emitted_tools)}",
        f"  dispatched  : {[f'{n}:{s}({d}ms)' for n, s, d in t.dispatched] or 'NONE'}",
        f"  orphan-strip: {t.stripped_events} log lines, max stripped_count={t.stripped_total}",
        f"  rewrites    : {t.rewritten_tools or 'none'}  (codemode native→run_code recovery)",
        f"  b_pass      : {t.b_pass}  successful_tools=[{t.succ_tools}]",
        f"  failure     : {t.failure_detail or 'None'}",
    ]
    probs = t.problems
    if probs:
        lines.append("  PROBLEMS:")
        lines += [f"    !! {p}" for p in probs]
    else:
        lines.append("  PROBLEMS: none detected")
    if t.final_text:
        lines.append(f"  reply head  : {t.final_text[:200]!r}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI entry: parse log, resolve turns, print reports.

    Args:
        argv (list[str] | None): Override ``sys.argv`` slice for tests.

    Returns:
        int: ``0`` on success, ``1`` when no match, ``2`` when log missing.

    Examples:
        >>> main(["--help"]) == 0
        True
    """
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--log", type=Path, default=DEFAULT_LOG)
    ap.add_argument("--find", help="resolve turn by substring of user/assistant message")
    ap.add_argument("--msg-id", help="resolve by telegram msg=<hex> fragment")
    ap.add_argument("--turn-id", help="resolve by full/partial turn_id")
    ap.add_argument("--all", action="store_true", help="report every turn with problems")
    args = ap.parse_args(argv)

    if not args.log.exists():
        print(f"log not found: {args.log}", file=sys.stderr)
        return 2

    text = args.log.read_text(errors="replace").splitlines()
    turns = parse(text)

    if args.all:
        flagged = [t for t in turns.values() if t.problems]
        print(f"# {len(turns)} turns parsed, {len(flagged)} with problems (log: {args.log})\n")
        for t in sorted(flagged, key=lambda x: x.turn_id):
            print(report(t))
            print()
        # one-line rollup of the dropped-call signature
        dropped = defaultdict(int)
        for t in turns.values():
            for tool in t.dropped_tools:
                dropped[tool] += 1
        if dropped:
            print("=" * 88)
            print("DROPPED-CALL ROLLUP (tool -> # turns it was emitted but never dispatched):")
            for tool, n in sorted(dropped.items(), key=lambda kv: -kv[1]):
                print(f"  {tool:24} {n}")
        return 0

    if not (args.find or args.msg_id or args.turn_id):
        ap.print_help()
        return 1

    matches = resolve(turns, find=args.find, msg_id=args.msg_id, turn_id=args.turn_id)
    if not matches:
        print("no matching turn found", file=sys.stderr)
        return 1
    for t in sorted(matches, key=lambda x: x.turn_id):
        print(report(t))
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
