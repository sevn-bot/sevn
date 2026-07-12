"""Tier-B zero-tool grounding guard (`specs/14-executor-tier-b.md`; live-session W4/W2).

Exports:
    asserts_ungrounded_claims — detect code-path or tool-provenance claims in text.
    apply_zero_tool_grounding_guard — prefix unverified when claims lack tool backing.
    apply_file_delivery_grounding_guard — block fabricated file-send / write claims (Wave 2 P5).
    apply_audit_evidence_guard — block false audit claims and unattempted tool failures (W4/W5).
    asserts_false_fabrication — detect audit confession / replay-stub blindness phrasing.
    steer_for_audit_evidence — steer-inject when audit guard fires mid-turn.
    steer_for_false_tool_failure_claim — steer when tool failure claimed without dispatch.
    claims_bound_tool_unavailable — detect "I can't call `<tool>`" when tool is bound.
    claims_file_delivery_success — detect sent/wrote/attached file claims without tool backing.
    claims_live_factual_content — detect score/schedule/weather claims in outbound text.
    claims_list_dir_embellishment — detect embellished list_dir tables/metadata (W4).
    claims_unattempted_tool_failure — detect tool failure claims without dispatch (W4).
    apply_live_factual_grounding_guard — block live-factual claims without web retrieval.
    claims_success_after_tool_failure — detect success-framed text after tool errors.
    steer_for_dropped_tool_call — steer-inject when an out-of-allowlist tool call is dropped.
    steer_for_direct_tool_call — steer-inject text for a misrouted tool name.
    steer_for_fallback_tool — steer-inject when a failed tool names a working fallback.
    steer_for_meta_tool_call — steer-inject when load_tool was used on a meta tool.
    steer_for_promised_action — steer-inject when a turn promised motion but ran no tool (P4).
    steer_for_opener_only — steer-inject when a turn finalized with only an opener/ack (P2).
    steer_for_triager_bound_tools_unused — steer-inject when triager-bound tools unused (G0).
    triager_bound_tools_satisfied — whether any bound tool/skill succeeded (G0 / D0b).
    tools_attempted_from_call_counts — derive attempted tool names from call-count keys.
    steer_for_summarize_after_fetch — steer-inject when tools succeeded but no user answer (W8).
    steer_for_playwright_cdp_probe_failure — steer when CDP probe fails before browser spawn (W6).
    steer_for_codemode_loaded_tool — steer-inject after ``load_tool`` under CodeMode (W7).
    is_self_architecture_query — best-effort self-architecture intent from user text.
    is_routing_footer_query — best-effort Telegram routing-footer intent from user text.
    tier_b_self_architecture_inject — hard executor inject for architecture turns.
    tier_b_routing_footer_inject — hard inject for show_routing / routing footer questions.
    append_output_truncation_notice — suffix when provider cut output at max_tokens.
    last_model_stop_reason — read stop_reason from pydantic-ai turn messages.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Sequence

from pydantic_ai.messages import ModelRequest, ModelResponse

from sevn.agent.openers import GROUNDING_CANNED_OPENERS

GROUNDING_TOOL_NAMES: Final[frozenset[str]] = frozenset(
    {
        "read",
        "glob",
        "search_in_file",
        "serp",
        "web_search",
        "web_fetch",
        "get_page_content",
    }
)

FILE_DELIVERY_TOOL_NAMES: Final[frozenset[str]] = frozenset(
    {"send_file", "write", "write_workspace_md"},
)

LIVE_FACTUAL_WEB_TOOLS: Final[frozenset[str]] = frozenset(
    {"serp", "get_page_content", "web_fetch", "web_search", "run_skill_script"},
)

_LIVE_FACTUAL_CLAIM_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\bseries\s+(?:is\s+)?tied\b", re.I),
    re.compile(r"\bGame\s+\d+\b", re.I),
    re.compile(r"\b\d+\s*-\s*\d+\b"),
    re.compile(r"\b(?:forecast|temperature)\b.+\b\d", re.I),
    re.compile(r"\bstock\s+price\b", re.I),
)

EVIDENCE_TOOLS: Final[frozenset[str]] = frozenset(
    {"log_query", "read_transcript", "history", "read"},
)

_AUDIT_CORRECTION_PREFIX: Final[str] = (
    "**Correction:** tool evidence exists this turn; summarize findings. "
)

_FALSE_TOOL_FAILURE_PREFIX: Final[str] = (
    "**Correction:** no dispatch record for that tool this turn — verify with "
    "`read_transcript` and `log_query` before claiming failure. "
)

_FABRICATION_PHRASES: tuple[str, ...] = (
    "fabricated",
    "no tools",
    "replay stub",
    "no data was returned",
)

_LIST_DIR_META_TOOLS: Final[frozenset[str]] = frozenset(
    {"load_tool", "load_skill", "list_registry"},
)

_FILE_METADATA_MARKERS: tuple[str, ...] = (
    "mtime",
    "modified",
    "size",
    "bytes",
    "permissions",
    "file type",
    "filetype",
)

_LIST_DIR_TABLE_ROW: Final[re.Pattern[str]] = re.compile(r"^\s*\|", re.MULTILINE)

_UNATTEMPTED_TOOL_FAILURE_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(
        r"load_tool\s*\(\s*['\"]?(?P<tool>\w+)['\"]?\s*\).{0,60}"
        r"(?:fail|error|issue|broken|not\s+work)",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r"(?P<tool>\w+)\s*(?:is\s+)?(?:not provisioned|TOOL_NOT_PROVISIONED)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:load_tool|schema\s+load).{0,40}(?:fail|issue|error|broken)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?P<tool>\w+)\s*(?:failed to load|could not load|couldn't load|did not load)",
        re.IGNORECASE,
    ),
)

_FILE_DELIVERY_CLAIM_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bsend(ing|t)?\s+(the\s+)?(file|pdf|document|attachment|report)\b", re.IGNORECASE),
    re.compile(
        r"\b(attached|delivered)\s+(the\s+|your\s+|my\s+)?(file|pdf|document|attachment|report)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(wrote|written|saved)\s+.+\s+(to\s+)?(workspace|disk|file|pdf)\b", re.IGNORECASE
    ),
    re.compile(r"\b(pdf|file|report)\s+(written|saved|created|ready|delivered)\b", re.IGNORECASE),
    re.compile(r"\bsending\s+it\s+now\b", re.IGNORECASE),
    re.compile(r"\bsending\s+(the\s+)?(file|pdf)\s+now\b", re.IGNORECASE),
    re.compile(r"\bprofile\s+saved\b", re.IGNORECASE),
    re.compile(r"\buser\.md\s+(saved|updated|written)\b", re.IGNORECASE),
    # "The report has been delivered to you" — require a file-like noun in the claim.
    re.compile(
        r"\b(file|pdf|document|attachment|report)\b.{0,30}(has\s+been\s+)?delivered\s+to\s+you\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(has\s+been\s+)?delivered\s+(the\s+|your\s+)?(file|pdf|document|attachment|report)\s+to\s+you\b",
        re.IGNORECASE,
    ),
)

_SUCCESS_FRAMED_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(done|finished|complete[d]?)\s*[.!—-]?\s*(sending|delivering)\b", re.IGNORECASE),
    re.compile(r"\b(written|saved)\s+to\s+workspace\b", re.IGNORECASE),
)

_UNVERIFIED_PREFIX: Final[str] = "**Unverified** (no read/glob/search/web tool ran this turn): "

_CODE_PATH_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bsrc/sevn/\S+", re.IGNORECASE),
    re.compile(r"\bsource_code/\S+", re.IGNORECASE),
    re.compile(r"\b[\w/]+\.py\b"),
    re.compile(r"\btools/cron/\S*", re.IGNORECASE),
)

_TOOL_PROVENANCE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bserp\b.{0,40}\breturned\b", re.IGNORECASE | re.DOTALL),
    re.compile(r"\bweb[_ ]search\b.{0,40}\breturned\b", re.IGNORECASE | re.DOTALL),
    re.compile(r"\bI fetched\b", re.IGNORECASE),
    re.compile(r"\bget_page_content\b.{0,40}\breturned\b", re.IGNORECASE | re.DOTALL),
    re.compile(r"\bweb_fetch\b.{0,40}\breturned\b", re.IGNORECASE | re.DOTALL),
    re.compile(r"\b\d+\s+sources?\b", re.IGNORECASE),
    re.compile(r"\bsources?\s*:\s*\|", re.IGNORECASE),
    re.compile(r"\|\s*source\s*\|", re.IGNORECASE),
)

_TOOL_UNAVAILABLE_PHRASES: tuple[str, ...] = (
    "isn't in my",
    "not in my callable",
    "callable function list",
    "can't call",
    "cannot call",
    "can not call",
    "isn't callable",
    "not callable",
    "is not callable",
    "is not available",
    "isn't available",
    "not in my tool list",
    "not in my tools",
)

_OUTPUT_TRUNCATION_SUFFIX: Final[str] = (
    "\n\n_(Answer may be incomplete — the model hit its output token limit. "
    "Ask me to continue where I left off.)_"
)

_ROUTING_FOOTER_MARKERS: tuple[str, ...] = (
    "show_routing",
    "show routing",
    "routing footer",
    "intent=tier",
    "intent= tier",
    "why isn't routing",
    "why is routing",
    "why routing",
    "routing shown",
    "routing display",
    "routing line",
    "footer on",
    "footer shown",
)


def is_routing_footer_query(message: str) -> bool:
    """Return whether user text asks about Telegram routing footer / show_routing.

    Args:
        message (str): Current user turn text.

    Returns:
        bool: ``True`` when the message likely targets routing footer display.

    Examples:
        >>> is_routing_footer_query("why isn't the routing footer shown?")
        True
        >>> is_routing_footer_query("hello")
        False
    """
    text = message.strip().lower()
    if not text:
        return False
    return any(marker in text for marker in _ROUTING_FOOTER_MARKERS)


def is_self_architecture_query(message: str) -> bool:
    """Return whether user text asks about the bot's own codebase or architecture.

    Delegates to :func:`sevn.agent.triager.routing_policy.is_repo_code_intent_message`
    so one classifier owns repo/self-architecture intent (W4.2).

    Args:
        message (str): Current user turn text.

    Returns:
        bool: ``True`` when the message likely targets self-architecture.

    Examples:
        >>> is_self_architecture_query("where is the code for cron?")
        True
        >>> is_self_architecture_query("hello")
        False
    """
    from sevn.agent.triager.routing_policy import is_repo_code_intent_message

    return is_repo_code_intent_message(message)


def asserts_ungrounded_claims(text: str) -> bool:
    """Detect code-path or tool-provenance claims that need grounding tool output.

    Args:
        text (str): Candidate tier-B outbound text.

    Returns:
        bool: ``True`` when the text asserts paths, classes, or tool results.

    Examples:
        >>> asserts_ungrounded_claims("Cron lives in src/sevn/tools/cron/runner.py")
        True
        >>> asserts_ungrounded_claims("I'll check that for you.")
        False
        >>> asserts_ungrounded_claims("serp returned 3 sources about Pugliese")
        True
    """
    body = (text or "").strip()
    if not body:
        return False
    for pattern in _CODE_PATH_PATTERNS:
        if pattern.search(body):
            return True
    for pattern in _TOOL_PROVENANCE_PATTERNS:
        if pattern.search(body):
            return True
    lowered = body.lower()
    return any(lowered.startswith(opener) for opener in GROUNDING_CANNED_OPENERS)


def _already_marked_unverified(text: str) -> bool:
    """Return whether ``text`` already carries an unverified disclaimer.

    Args:
        text (str): Outbound tier-B text.

    Returns:
        bool: True when an unverified marker is present near the start.

    Examples:
        >>> _already_marked_unverified("**Unverified** (no read): foo")
        True
        >>> _already_marked_unverified("Cron lives in src/sevn/foo.py")
        False
    """
    lowered = text.strip().lower()
    return lowered.startswith("**unverified**") or "unverified" in lowered[:120]


def _strip_canned_opener(text: str) -> str:
    """Remove a leading canned opener before prefixing unverified.

    Args:
        text (str): Outbound tier-B text.

    Returns:
        str: Text with a known opener removed when present.

    Examples:
        >>> _strip_canned_opener("Found it. src/sevn/foo.py")
        'src/sevn/foo.py'
    """
    body = text.lstrip()
    lowered = body.lower()
    for opener in sorted(GROUNDING_CANNED_OPENERS, key=len, reverse=True):
        if lowered.startswith(opener):
            remainder = body[len(opener) :].lstrip(" \t—-:.\n")
            return remainder or body
    return body


def claims_bound_tool_unavailable(
    text: str,
    bound_tools: frozenset[str],
) -> str | None:
    """Detect when tier-B text claims a bound tool is unavailable or not callable.

    Args:
        text (str): Candidate tier-B outbound text.
        bound_tools (frozenset[str]): Tool names the triager bound for this turn.

    Returns:
        str | None: The first bound tool name the text falsely claims is unavailable.

    Examples:
        >>> tools = frozenset({"serp", "read"})
        >>> claims_bound_tool_unavailable(
        ...     "serp isn't in my current callable function list.", tools
        ... )
        'serp'
        >>> claims_bound_tool_unavailable("I'll run serp now.", tools) is None
        True
        >>> claims_bound_tool_unavailable("glob is missing.", frozenset({"read"})) is None
        True
    """
    body = (text or "").strip()
    if not body or not bound_tools:
        return None
    lowered = body.lower()
    if not any(phrase in lowered for phrase in _TOOL_UNAVAILABLE_PHRASES):
        return None
    for tool_name in sorted(bound_tools, key=len, reverse=True):
        if not re.search(rf"\b{re.escape(tool_name.lower())}\b", lowered):
            continue
        return tool_name
    return None


def claims_live_factual_content(text: str) -> bool:
    """Detect when tier-B text states live scores, schedules, or similar facts.

    Args:
        text (str): Candidate tier-B outbound text.

    Returns:
        bool: ``True`` when the text looks like a live factual claim.

    Examples:
        >>> claims_live_factual_content("The NBA Finals series is tied 1-1.")
        True
        >>> claims_live_factual_content("I'll check the score now.")
        False
    """
    body = (text or "").strip()
    if not body:
        return False
    return any(pattern.search(body) for pattern in _LIVE_FACTUAL_CLAIM_PATTERNS)


def _list_dir_only_substantive_turn(successful_tools_called: frozenset[str]) -> bool:
    """Return whether the only substantive successful tool this turn was ``list_dir``.

    Args:
        successful_tools_called (frozenset[str]): Tools that returned ``ok=true`` this turn.

    Returns:
        bool: ``True`` when ``list_dir`` alone succeeded (meta tools excluded).

    Examples:
        >>> _list_dir_only_substantive_turn(frozenset({"list_dir"}))
        True
        >>> _list_dir_only_substantive_turn(frozenset({"list_dir", "read"}))
        False
    """
    substantive = successful_tools_called - _LIST_DIR_META_TOOLS
    return substantive == frozenset({"list_dir"})


def claims_list_dir_embellishment(text: str) -> bool:
    """Detect free-form directory tables or metadata beyond ``list_dir`` ``names``.

    Flags markdown pipe tables and size/mtime/type columns typical of ``msg=3d3160``
    embellishment when only ``list_dir`` succeeded.

    Args:
        text (str): Candidate tier-B outbound text.

    Returns:
        bool: ``True`` when the answer adds ungrounded directory metadata.

    Examples:
        >>> table = "| Name | Size | Modified |\\n| --- | --- | --- |\\n| foo.md | 1k | today |"
        >>> claims_list_dir_embellishment(table)
        True
        >>> claims_list_dir_embellishment("- MEMORY.md\\n- skills/")
        False
    """
    body = (text or "").strip()
    if not body:
        return False
    lowered = body.lower()
    if _LIST_DIR_TABLE_ROW.search(body):
        return True
    return ("|" in body and any(marker in lowered for marker in _FILE_METADATA_MARKERS)) or (
        any(marker in lowered for marker in _FILE_METADATA_MARKERS)
        and re.search(r"(?:size|mtime|modified|bytes)\s*[:|]", body, re.IGNORECASE) is not None
    )


def claims_unattempted_tool_failure(
    text: str,
    *,
    tools_attempted: frozenset[str],
) -> str | None:
    """Detect audit text claiming a tool failed when no dispatch record exists.

    Covers ``bc75f9``-style narratives that cite ``load_tool(search_in_file)`` failure
    without any ``load_tool`` or target-tool attempt in the turn history.

    Args:
        text (str): Candidate tier-B outbound text.
        tools_attempted (frozenset[str]): Tool names dispatched this turn (including
            ``load_tool`` targets parsed from call signatures).

    Returns:
        str | None: The first tool name falsely claimed as failed, or ``None``.

    Examples:
        >>> claimed = claims_unattempted_tool_failure(
        ...     "load_tool(search_in_file) failed — tool not provisioned.",
        ...     tools_attempted=frozenset(),
        ... )
        >>> claimed
        'search_in_file'
        >>> claims_unattempted_tool_failure(
        ...     "search_in_file returned ok=false path invalid.",
        ...     tools_attempted=frozenset({"search_in_file"}),
        ... ) is None
        True
    """
    body = (text or "").strip()
    if not body:
        return None
    for pattern in _UNATTEMPTED_TOOL_FAILURE_PATTERNS:
        match = pattern.search(body)
        if match is None:
            continue
        tool = (match.groupdict().get("tool") or "").strip().lower()
        if tool and tool not in tools_attempted:
            return tool
        if not tool and "load_tool" not in tools_attempted:
            return "load_tool"
    return None


def tools_attempted_from_call_counts(tool_call_counts: dict[str, int]) -> frozenset[str]:
    """Derive attempted tool names from tier-B ``BTierDeps.tool_call_counts`` keys.

    Parses ``load_tool`` payloads so hydration targets count as attempted.

    Args:
        tool_call_counts (dict[str, int]): ``tool_name:json_args`` repeat counters.

    Returns:
        frozenset[str]: Tool names attempted this turn.

    Examples:
        >>> attempted = tools_attempted_from_call_counts(
        ...     {'list_dir:{"path": "."}': 1},
        ... )
        >>> "list_dir" in attempted
        True
    """
    attempted: set[str] = set()
    for key in tool_call_counts:
        name, sep, args_json = key.partition(":")
        if not sep:
            attempted.add(name)
            continue
        attempted.add(name)
        if name != "load_tool":
            continue
        try:
            payload = json.loads(args_json)
        except json.JSONDecodeError:
            continue
        target = payload.get("name") or payload.get("tool")
        if target:
            attempted.add(str(target).strip())
    return frozenset(attempted)


def apply_live_factual_grounding_guard(
    text: str,
    *,
    successful_tools_called: frozenset[str],
) -> tuple[str, bool]:
    """Block live-factual claims that lack a successful web retrieval tool this turn.

    For ``list_dir``-only turns (``msg=3d3160``), allows verbatim ``names``/bullet
    listings but blocks embellished tables with size/mtime columns unless ``read`` or
    ``file_info`` also succeeded.

    Args:
        text (str): Tier-B outbound text after preamble stripping.
        successful_tools_called (frozenset[str]): Tools that returned ``ok=true`` this turn.

    Returns:
        tuple[str, bool]: ``(text, blocked)`` — ``blocked`` when the claim must not ship.

    Examples:
        >>> claim = "NBA Finals series is tied 1-1 after Game 2."
        >>> _out, blocked = apply_live_factual_grounding_guard(
        ...     claim, successful_tools_called=frozenset()
        ... )
        >>> blocked
        True
        >>> plain, blocked2 = apply_live_factual_grounding_guard(
        ...     "- MEMORY.md\\n- skills/",
        ...     successful_tools_called=frozenset({"list_dir"}),
        ... )
        >>> blocked2
        False
        >>> plain == "- MEMORY.md\\n- skills/"
        True
    """
    body = (text or "").strip()
    if not body:
        return text, False
    if _list_dir_only_substantive_turn(successful_tools_called):
        if claims_list_dir_embellishment(body):
            return "", True
        return text, False
    if not claims_live_factual_content(body):
        return text, False
    if LIVE_FACTUAL_WEB_TOOLS & successful_tools_called:
        return text, False
    if EVIDENCE_TOOLS & successful_tools_called:
        return text, False
    return "", True


def claims_file_delivery_success(text: str) -> bool:
    """Detect when tier-B text claims a file was sent, written, or attached.

    Args:
        text (str): Candidate tier-B outbound text.

    Returns:
        bool: ``True`` when the text asserts file delivery or workspace write success.

    Examples:
        >>> claims_file_delivery_success("PDF written to workspace. Sending it now.")
        True
        >>> claims_file_delivery_success("I'll try rendering the PDF next.")
        False
    """
    body = (text or "").strip()
    if not body:
        return False
    return any(pattern.search(body) for pattern in _FILE_DELIVERY_CLAIM_PATTERNS)


def claims_success_after_tool_failure(text: str, *, had_tool_failures: bool) -> bool:
    """Detect success-framed outbound text after an unrecovered tool error.

    Args:
        text (str): Candidate tier-B outbound text.
        had_tool_failures (bool): Whether any tool returned ``ok=false`` this turn.

    Returns:
        bool: ``True`` when failures occurred and the text still frames success.

    Examples:
        >>> claims_success_after_tool_failure(
        ...     "PDF written to workspace. Sending it now.", had_tool_failures=True
        ... )
        True
        >>> claims_success_after_tool_failure("PDF written.", had_tool_failures=False)
        False
    """
    if not had_tool_failures:
        return False
    body = (text or "").strip()
    if not body:
        return False
    if claims_file_delivery_success(body):
        return True
    return any(pattern.search(body) for pattern in _SUCCESS_FRAMED_PATTERNS)


def apply_file_delivery_grounding_guard(
    text: str,
    *,
    successful_tools_called: frozenset[str],
    had_tool_failures: bool = False,
) -> tuple[str, bool]:
    """Block or rewrite fabricated file-delivery claims lacking tool backing.

    Args:
        text (str): Tier-B outbound text after preamble stripping.
        successful_tools_called (frozenset[str]): Tools that returned ``ok=true`` this turn.
        had_tool_failures (bool, optional): Whether any tool failed this turn. Defaults to ``False``.

    Returns:
        tuple[str, bool]: ``(text, blocked)`` — ``blocked`` when delivery must not ship.

    Examples:
        >>> claim = "PDF written to workspace. Sending it now."
        >>> _out, blocked = apply_file_delivery_grounding_guard(
        ...     claim, successful_tools_called=frozenset()
        ... )
        >>> blocked
        True
        >>> out2, blocked2 = apply_file_delivery_grounding_guard(
        ...     claim, successful_tools_called=frozenset({"send_file"})
        ... )
        >>> blocked2
        False
    """
    body = (text or "").strip()
    if not body:
        return text, False
    backed = bool(FILE_DELIVERY_TOOL_NAMES & successful_tools_called)
    if claims_file_delivery_success(body) and not backed:
        return "", True
    if claims_success_after_tool_failure(body, had_tool_failures=had_tool_failures) and not backed:
        return "", True
    return text, False


def steer_for_dropped_tool_call(tool_name: str, *, available_tools: frozenset[str]) -> str:
    """Build steer-inject text when an out-of-allowlist tool call was dropped.

    Used for tools that are **not** in the registry (``TOOL_NOT_PROVISIONED``). Registry-valid
    tools are auto-granted by :func:`sevn.agent.adapters.tool_part_filter.filter_tool_call_parts`
    instead of reaching this steer path.

    Args:
        tool_name (str): Tool the model attempted to call.
        available_tools (frozenset[str]): Names exposed on this turn.

    Returns:
        str: One-line steer text for the next LLM boundary.

    Examples:
        >>> msg = steer_for_dropped_tool_call("terminal_run", available_tools=frozenset({"read"}))
        >>> "TOOL_NOT_PROVISIONED" in msg and "read" in msg
        True
    """
    sample = ", ".join(sorted(available_tools)[:12])
    suffix = "…" if len(available_tools) > 12 else ""
    return (
        f"TOOL_NOT_PROVISIONED: `{tool_name}` is not in the registry and cannot be called. "
        f"Available tools this turn: {sample}{suffix}. Re-plan using only available tools."
    )


def steer_for_direct_tool_call(tool_name: str) -> str:
    """Build a steer-inject line telling the model to call a registry tool directly.

    Args:
        tool_name (str): Registry tool the model misrouted or claimed unavailable.

    Returns:
        str: One-line steer text for the next LLM boundary.

    Examples:
        >>> steer_for_direct_tool_call("serp")
        '`serp` is a registered tool on this turn — call `serp` directly with the correct arguments now. Do not use run_skill_script or run_skill_runnable for it, and do not claim it is unavailable.'
    """
    return (
        f"`{tool_name}` is a registered tool on this turn — call `{tool_name}` directly "
        f"with the correct arguments now. Do not use run_skill_script or "
        f"run_skill_runnable for it, and do not claim it is unavailable."
    )


def steer_for_fallback_tool(failed_tool: str, fallback_tool: str) -> str:
    """Build steer text when a tool failed and its envelope names a working fallback.

    Args:
        failed_tool (str): Tool whose result reported it is unavailable.
        fallback_tool (str): Fallback tool named in the failure envelope's
            ``data.fallback_tool`` (granted for the turn by the dispatcher).

    Returns:
        str: One-line steer text for the next LLM boundary.

    Examples:
        >>> msg = steer_for_fallback_tool("web_search", "serp")
        >>> "web_search" in msg and "serp" in msg and "memory" in msg
        True
    """
    return (
        f"`{failed_tool}` is unavailable in this environment — its result named "
        f"`{fallback_tool}` as the working fallback, and `{fallback_tool}` is granted "
        f"for this turn. Call `{fallback_tool}` now with the same intent/arguments. "
        f"Do not retry `{failed_tool}`, and do not answer from model memory unless "
        f"you clearly label the answer as unsourced."
    )


def steer_for_meta_tool_call(tool_name: str) -> str:
    """Build steer text when ``load_tool`` was wrongly used on a meta tool.

    Args:
        tool_name (str): Meta tool name (e.g. ``list_registry``).

    Returns:
        str: One-line steer text for the next LLM boundary.

    Examples:
        >>> msg = steer_for_meta_tool_call("list_registry")
        >>> "list_registry" in msg and "load_tool" in msg
        True
    """
    return (
        f"`{tool_name}` is a meta tool — call `{tool_name}` directly with the correct "
        f"arguments now. Do not use `load_tool` on meta tools (`list_registry`, "
        f"`load_tool`, `load_skill`, `request_escalation`); `load_tool` only hydrates "
        f"native/MCP tools."
    )


def steer_for_codemode_loaded_tool(tool_name: str) -> str:
    """Build steer text after ``load_tool`` grants a web tool under CodeMode (W7 / D11).

    Args:
        tool_name (str): Registry tool name hydrated by ``load_tool``.

    Returns:
        str: One-line steer text directing ``run_code`` usage.

    Examples:
        >>> msg = steer_for_codemode_loaded_tool("get_page_content")
        >>> "run_code" in msg and "get_page_content" in msg
        True
    """
    return (
        f"Schema attached for `{tool_name}` — call it via `run_code` with "
        f"`await {tool_name}(...)` inside the sandbox. Do not issue a native top-level "
        f"`{tool_name}` call under CodeMode; compose web fetches inside `run_code`."
    )


def asserts_false_fabrication(text: str) -> bool:
    """Detect audit answers that falsely claim fabrication or tool blindness.

    Args:
        text (str): Candidate tier-B outbound text.

    Returns:
        bool: ``True`` when the text confesses fabrication or denies tool evidence.

    Examples:
        >>> asserts_false_fabrication("I fabricated the DutchNews summary.")
        True
        >>> asserts_false_fabrication("replay stub means I can't see the data.")
        True
        >>> asserts_false_fabrication("Here is what log_query returned.")
        False
    """
    body = (text or "").strip().lower()
    if not body:
        return False
    return any(phrase in body for phrase in _FABRICATION_PHRASES)


def apply_audit_evidence_guard(
    text: str,
    *,
    successful_tools: frozenset[str],
    codemode_bound_tools_called: frozenset[str] | None = None,
    tools_attempted: frozenset[str] | None = None,
) -> tuple[str, bool]:
    """Prefix or flag false audit claims when evidence exists or dispatch did not run.

    Handles (a) fabrication confessions when ``log_query``/``read_transcript`` succeeded,
    and (b) ``bc75f9``-style claims that ``load_tool`` or a registry tool failed when no
    dispatch record exists this turn.

    Args:
        text (str): Tier-B outbound text after preamble stripping.
        successful_tools (frozenset[str]): Tools that returned ``ok=true`` this turn.
        codemode_bound_tools_called (frozenset[str] | None): Bound registry tools detected
            inside successful ``run_code`` scripts (lenient CodeMode trace).
        tools_attempted (frozenset[str] | None): Tool names dispatched this turn; when
            omitted, unattempted-failure detection is skipped.

    Returns:
        tuple[str, bool]: ``(text, guard_applied)`` — text gains a correction prefix when
        the guard fires.

    Examples:
        >>> claim = "I fabricated that answer — no tools returned data."
        >>> out, applied = apply_audit_evidence_guard(
        ...     claim, successful_tools=frozenset({"log_query"})
        ... )
        >>> applied
        True
        >>> out.startswith("**Correction:**")
        True
        >>> _out2, applied2 = apply_audit_evidence_guard(
        ...     claim, successful_tools=frozenset()
        ... )
        >>> applied2
        False
        >>> _out3, applied3 = apply_audit_evidence_guard(
        ...     claim,
        ...     successful_tools=frozenset({"run_code"}),
        ...     codemode_bound_tools_called=frozenset({"log_query"}),
        ... )
        >>> applied3
        True
        >>> false_fail = "load_tool(search_in_file) failed — not provisioned."
        >>> out4, applied4 = apply_audit_evidence_guard(
        ...     false_fail,
        ...     successful_tools=frozenset(),
        ...     tools_attempted=frozenset(),
        ... )
        >>> applied4
        True
    """
    body = (text or "").strip()
    if not body:
        return text, False
    if body.lower().startswith("**correction:**"):
        return text, False
    attempted = tools_attempted if tools_attempted is not None else frozenset()
    false_tool = claims_unattempted_tool_failure(body, tools_attempted=attempted)
    if false_tool is not None:
        return f"{_FALSE_TOOL_FAILURE_PREFIX}{body}", True
    effective_tools = successful_tools
    if codemode_bound_tools_called:
        effective_tools = successful_tools | codemode_bound_tools_called
    if not (effective_tools & EVIDENCE_TOOLS):
        return text, False
    if not asserts_false_fabrication(body):
        return text, False
    return f"{_AUDIT_CORRECTION_PREFIX}{body}", True


def steer_for_audit_evidence() -> str:
    """Build steer text when evidence tools succeeded but the model confesses fabrication.

    Returns:
        str: One-line steer text for the next LLM boundary.

    Examples:
        >>> msg = steer_for_audit_evidence()
        >>> "log_query" in msg and "fabrication" in msg.lower()
        True
    """
    return (
        "You received OK results from log_query/read_transcript/history/read this turn. "
        "Summarize the evidence for the user. Do not claim fabrication, that no tools "
        "ran, or that replay_stub means you cannot see data."
    )


def steer_for_false_tool_failure_claim() -> str:
    """Build steer text when the model claims tool failure without dispatch evidence.

    Returns:
        str: One-line steer text for the next LLM boundary.

    Examples:
        >>> msg = steer_for_false_tool_failure_claim()
        >>> "log_query" in msg and "read_transcript" in msg
        True
    """
    return (
        "Do not claim a tool or load_tool failed unless a tool_result envelope appears "
        "in this turn's history. Use read_transcript and log_query to verify dispatch "
        "before stating failure."
    )


def steer_for_playwright_cdp_probe_failure() -> str:
    """Build steer when a CDP probe fails before any browser spawn (W6 / ``62803d``).

    ``cdp_probe.py`` and ``session_status.py`` report ``CDP_UNREACHABLE`` on the
    default port until ``capture.py`` or ``goto.py`` spawns Chrome — not a skill outage.

    Returns:
        str: One-line steer directing capture/goto instead of claiming Playwright broken.

    Examples:
        >>> msg = steer_for_playwright_cdp_probe_failure()
        >>> "capture.py" in msg and "CDP_UNREACHABLE" in msg
        True
    """
    return (
        "CDP_UNREACHABLE on the default port is **expected** before the first "
        "`capture.py` or `goto.py` run — those scripts spawn Chrome. Do not report "
        "Playwright as broken; call `run_skill_script` with "
        "`scripts/capture.py` and the target URL in `argv`."
    )


def steer_for_summarize_after_fetch(successful_tools: frozenset[str]) -> str:
    """Build steer text when registry tools ran OK but no user-facing answer shipped.

    Args:
        successful_tools (frozenset[str]): Tool names that returned ``ok=true`` this turn.

    Returns:
        str: Steer text forcing read/summarize instead of another fetch loop.

    Examples:
        >>> msg = steer_for_summarize_after_fetch(frozenset({"get_page_content"}))
        >>> "Do NOT re-fetch" in msg
        True
        >>> "replay_stub" in msg
        True
    """
    sample = ", ".join(sorted(successful_tools)[:8])
    suffix = "…" if len(successful_tools) > 8 else ""
    return (
        f"You already succeeded calling: {sample}{suffix}. Do NOT re-fetch the same URL "
        "or re-run the same log query. Summarize for the user now: if `get_page_content` "
        "spilled, `read` the `spill_path` once; if `save_to` wrote a file, `read` that path; "
        "if you need logs, use `run_code` with `await log_query(...)` fresh. Ignore any "
        "prior tool_result containing `replay_stub` — those are transport placeholders, "
        "not real failures."
    )


# Meta registry loaders that satisfy the triager-bound-tools mandate when called successfully.
_TRIAGER_BOUND_META_MANDATE_TOOLS: frozenset[str] = frozenset(
    {"list_registry", "load_tool", "load_skill"},
)


def _bound_meta_tool_mandate_satisfied(
    bound_tools: Sequence[str],
    successful_tools_called: frozenset[str],
) -> bool:
    """Return True when a bound meta registry tool succeeded this turn.

    Args:
        bound_tools (Sequence[str]): ``TriageResult.tools`` for this turn.
        successful_tools_called (frozenset[str]): Tools that returned ``ok=true`` this turn.

    Returns:
        bool: ``True`` when an explicitly bound meta tool succeeded.

    Examples:
        >>> _bound_meta_tool_mandate_satisfied(
        ...     ("list_registry", "read"),
        ...     frozenset({"list_registry"}),
        ... )
        True
        >>> _bound_meta_tool_mandate_satisfied(
        ...     ("read",),
        ...     frozenset({"list_registry"}),
        ... )
        False
    """
    bound = frozenset(bound_tools)
    return bool(bound & _TRIAGER_BOUND_META_MANDATE_TOOLS & successful_tools_called)


def triager_bound_tools_satisfied(
    *,
    bound_tools: Sequence[str],
    bound_skills: Sequence[str],
    successful_tools_called: frozenset[str],
    successful_skills_called: frozenset[str],
    codemode_bound_tools_called: frozenset[str],
) -> bool:
    """Whether at least one triager-bound tool or skill succeeded this turn (G0 / D0b).

    A bound **skill** counts when ``load_skill(name)`` or ``run_skill_script(skill=name)``
    returned ``ok=true``. A bound **registry tool** counts on a direct successful call, or
    when CodeMode is active and the tool name appears as an identifier inside a successful
    ``run_code`` script (**lenient** trace — substring match on the sandbox source, not a
    full Monty execution trace).

    Meta-tools ``list_registry`` / ``load_tool`` / ``load_skill`` satisfy the mandate when
    explicitly listed in ``triage.tools`` and called successfully (even when other bound
    registry tools such as ``read`` were not used).

    Args:
        bound_tools (Sequence[str]): ``TriageResult.tools`` for this turn.
        bound_skills (Sequence[str]): ``TriageResult.skills`` for this turn.
        successful_tools_called (frozenset[str]): Tools that returned ``ok=true`` this turn.
        successful_skills_called (frozenset[str]): Skill ids satisfied via
            ``load_skill`` / ``run_skill_script`` / ``run_skill_runnable``.
        codemode_bound_tools_called (frozenset[str]): Bound registry tools detected inside
            successful ``run_code`` scripts (lenient CodeMode trace).

    Returns:
        bool: ``True`` when at least one bound tool or skill was used successfully.

    Examples:
        >>> triager_bound_tools_satisfied(
        ...     bound_tools=("serp",),
        ...     bound_skills=(),
        ...     successful_tools_called=frozenset({"serp"}),
        ...     successful_skills_called=frozenset(),
        ...     codemode_bound_tools_called=frozenset(),
        ... )
        True
        >>> triager_bound_tools_satisfied(
        ...     bound_tools=("serp",),
        ...     bound_skills=(),
        ...     successful_tools_called=frozenset(),
        ...     successful_skills_called=frozenset(),
        ...     codemode_bound_tools_called=frozenset(),
        ... )
        False
        >>> triager_bound_tools_satisfied(
        ...     bound_tools=(),
        ...     bound_skills=("pdf",),
        ...     successful_tools_called=frozenset(),
        ...     successful_skills_called=frozenset({"pdf"}),
        ...     codemode_bound_tools_called=frozenset(),
        ... )
        True
    """
    skills = frozenset(bound_skills)
    if skills and successful_skills_called & skills:
        return True
    tools = frozenset(bound_tools)
    if not tools:
        return False
    if _bound_meta_tool_mandate_satisfied(bound_tools, successful_tools_called):
        return True
    if successful_tools_called & tools:
        return True
    return bool(codemode_bound_tools_called & tools)


def steer_for_triager_bound_tools_unused(
    bound_tools: Sequence[str],
    bound_skills: Sequence[str],
) -> str:
    """Build a steer line when triager-bound tools/skills ran nothing (G0).

    Used when tier-B finalizes with ``rounds_used == 0`` while the triager bound
    one or more tools/skills and none succeeded — the model wrote an answer (or ack)
    without invoking the mandated toolkit. Forces the next attempt to call the
    bound tools/skills or state what blocks them.

    Args:
        bound_tools (Sequence[str]): ``TriageResult.tools`` for this turn.
        bound_skills (Sequence[str]): ``TriageResult.skills`` for this turn.

    Returns:
        str: One-line steer text for the next LLM boundary.

    Examples:
        >>> steer = steer_for_triager_bound_tools_unused(["serp"], [])
        >>> "serp" in steer
        True
        >>> "do not" in steer.lower()
        True
    """
    parts: list[str] = []
    if bound_tools:
        parts.append("tools: " + ", ".join(sorted(bound_tools)))
    if bound_skills:
        parts.append("skills: " + ", ".join(sorted(bound_skills)))
    bound_summary = "; ".join(parts) if parts else "the triager-selected toolkit"
    steer = (
        f"The triager bound {bound_summary} for this turn but you called none of them "
        "and produced no tool-backed result. Do not answer from memory or fabricate "
        "tool output. Call the bound tool(s) or skill script(s) now — or, if you "
        "genuinely cannot, reply with one honest, specific line saying exactly what "
        "is blocking you."
    )
    if "playwright-browser" in bound_skills:
        steer += (
            " For playwright-browser: call load_skill then run_skill_script with "
            "scripts/goto.py and argv containing the full https URL before stating "
            "any page content."
        )
    return steer


def steer_for_promised_action() -> str:
    """Build a steer line telling the model to act instead of re-acking (P4).

    Used when a tier-B turn finalizes with ``rounds_used == 0`` and the only
    output is a motion-promise ("On it…", "Executing now.", "Rendering the PDF
    now.") with no tool call behind it — the "all talk, no walk" failure. The
    steer forces the next attempt to either run the needed tool(s) or, if it
    genuinely cannot, say *why* it is blocked rather than promise motion again.

    Returns:
        str: One-line steer text for the next LLM boundary.

    Examples:
        >>> "do not" in steer_for_promised_action().lower()
        True
        >>> "tool" in steer_for_promised_action().lower()
        True
    """
    return (
        "Your last reply only PROMISED to act ('on it', 'doing', 'executing', "
        "'rendering now') but called no tool and produced no result. Do not send "
        "another acknowledgement. Either call the tool(s) needed to actually do "
        "the work now, or — if you genuinely cannot — reply with one honest, "
        "specific line saying exactly what is blocking you. Never promise motion "
        "without acting."
    )


def steer_for_opener_only(
    bound_tools: Sequence[str],
    bound_skills: Sequence[str],
) -> str:
    """Build a steer line for an opener-only finalize (Mode A; ``PROBLEMS.md`` P2).

    Used when a tier-B turn finalizes with only a bare opener / ack ("On it — pulling
    the answer now.", "Reading now.") and no substantive body — the opener-only guard
    that previously reclassified the turn failed with **no** corrective steer, so the
    widened retry got no guidance and the model repeated the opener. The steer forces the
    next attempt to call the bound tool(s)/skill(s) and give the answer, or state what
    blocks it.

    Args:
        bound_tools (Sequence[str]): ``TriageResult.tools`` for this turn (may be empty).
        bound_skills (Sequence[str]): ``TriageResult.skills`` for this turn (may be empty).

    Returns:
        str: One-line steer text for the next LLM boundary.

    Examples:
        >>> "opener" in steer_for_opener_only((), ()).lower()
        True
        >>> "read" in steer_for_opener_only(("read",), ()).lower()
        True
    """
    parts: list[str] = []
    if bound_tools:
        parts.append("tools: " + ", ".join(sorted(bound_tools)))
    if bound_skills:
        parts.append("skills: " + ", ".join(sorted(bound_skills)))
    if parts:
        toolkit = "; ".join(parts)
        action = f"Call the bound {toolkit} now and give the answer"
    else:
        action = "Call the tool(s) needed and give the answer"
    return (
        "Your last reply was only an opener/ack with no substantive answer and no tool "
        f"call. Do not send another opener. {action} — or, if you genuinely cannot, "
        "reply with one honest, specific line saying exactly what is blocking you."
    )


def apply_zero_tool_grounding_guard(
    text: str,
    *,
    grounding_tools_called: frozenset[str],
) -> tuple[str, bool]:
    """Prefix unverified when claims lack grounding tools this turn.

    When the final text asserts code paths or tool provenance but no
    ``read``/``glob``/``search_in_file``/web tool ran, block canned phrasing and
    force an explicit unverified prefix instead of shipping fabricated detail.

    Args:
        text (str): Tier-B outbound text after preamble stripping.
        grounding_tools_called (frozenset[str]): Grounding tools invoked this turn.

    Returns:
        tuple[str, bool]: ``(text, guard_applied)`` — text may gain an unverified prefix.

    Examples:
        >>> claim = "Found it. Cron is in src/sevn/tools/cron/runner.py"
        >>> out, applied = apply_zero_tool_grounding_guard(
        ...     claim, grounding_tools_called=frozenset()
        ... )
        >>> applied
        True
        >>> out.startswith("**Unverified**")
        True
        >>> out2, applied2 = apply_zero_tool_grounding_guard(
        ...     claim, grounding_tools_called=frozenset({"glob"})
        ... )
        >>> applied2
        False
    """
    body = (text or "").strip()
    if not body:
        return text, False
    if grounding_tools_called:
        return text, False
    if not asserts_ungrounded_claims(body):
        return text, False
    if _already_marked_unverified(body):
        return text, False
    trimmed = _strip_canned_opener(body)
    return f"{_UNVERIFIED_PREFIX}{trimmed}", True


def tier_b_routing_footer_inject() -> str:
    """Hard executor inject when the user asks about Telegram routing footer display.

    Returns:
        str: Markdown block appended to tier-B ``extra_instructions``.

    Examples:
        >>> "SEVN-ARCHITECTURE.md" in tier_b_routing_footer_inject()
        True
        >>> "routing_footer.py" not in tier_b_routing_footer_inject()
        True
    """
    return (
        "## Telegram routing footer (show_routing) — mandatory ground truth\n"
        "When asked why the intent/tier routing footer is or is not visible:\n"
        "1. Read the **routing footer / show_routing** section in `SEVN-ARCHITECTURE.md` "
        "(in your system prompt or via `read` this turn) for feature location, when the "
        "footer appears, and the operator toggle.\n"
        "2. Answer **only** from `SEVN-ARCHITECTURE.md` or tool output obtained **this turn**.\n"
        "3. **Do not name** files, functions, or config keys you have not read this turn.\n"
        "If you have not read `SEVN-ARCHITECTURE.md` this turn, say so and read it first.\n"
    )


def last_model_stop_reason(
    messages: list[ModelRequest | ModelResponse],
) -> str | None:
    """Return the most recent provider ``stop_reason`` from pydantic-ai messages.

    Args:
        messages (list[ModelRequest | ModelResponse]): New messages from one agent run.

    Returns:
        str | None: Normalized stop reason when present on the last model response.

    Examples:
        >>> from pydantic_ai.messages import ModelResponse, TextPart
        >>> msgs = [ModelResponse(parts=[TextPart(content="hi")], metadata={"stop_reason": "end_turn"})]
        >>> last_model_stop_reason(msgs)
        'end_turn'
    """
    for msg in reversed(messages):
        if not isinstance(msg, ModelResponse):
            continue
        metadata = getattr(msg, "metadata", None)
        if not isinstance(metadata, dict):
            continue
        stop = metadata.get("stop_reason")
        if stop is None:
            continue
        return str(stop).strip().lower() or None
    return None


def append_output_truncation_notice(text: str, stop_reason: str | None) -> str:
    """Append a user-visible notice when the provider stopped at ``max_tokens``.

    Args:
        text (str): Tier-B outbound text.
        stop_reason (str | None): Provider stop reason from the final model response.

    Returns:
        str: ``text`` unchanged unless ``stop_reason`` indicates output truncation.

    Examples:
        >>> append_output_truncation_notice("partial", "max_tokens").endswith("left off.)_")
        True
        >>> append_output_truncation_notice("ok", "end_turn")
        'ok'
    """
    body = (text or "").strip()
    if not body:
        return text
    reason = (stop_reason or "").strip().lower()
    if reason not in {"max_tokens", "length"}:
        return text
    if body.endswith(_OUTPUT_TRUNCATION_SUFFIX.strip()):
        return text
    return f"{text.rstrip()}{_OUTPUT_TRUNCATION_SUFFIX}"


def tier_b_self_architecture_inject() -> str:
    """Hard executor inject when the user asks about sevn.bot architecture.

    Returns:
        str: Markdown block appended to tier-B ``extra_instructions``.

    Examples:
        >>> "SEVN-ARCHITECTURE.md" in tier_b_self_architecture_inject()
        True
        >>> "sevn.triggers.cron" not in tier_b_self_architecture_inject()
        True
    """
    return (
        "## Self-architecture turn (mandatory)\n"
        "The user is asking about **your own** codebase or architecture. Answer **only** from:\n"
        "1. The `SEVN-ARCHITECTURE.md` block in your system prompt, or\n"
        "2. Actual tool output from **this turn** (`read`, `glob`, `search_in_file`, web tools).\n"
        "If you have made zero grounding tool calls, you have read nothing — **do not name "
        "files, classes, or config keys**. Read `SEVN-ARCHITECTURE.md` or `glob`/`read` under "
        "`source_code/` **before** answering.\n"
        "Never fabricate paths or module trees from training data — verify everything against "
        "`SEVN-ARCHITECTURE.md` or this-turn tool output.\n"
    )


__all__ = [
    "EVIDENCE_TOOLS",
    "FILE_DELIVERY_TOOL_NAMES",
    "GROUNDING_TOOL_NAMES",
    "LIVE_FACTUAL_WEB_TOOLS",
    "append_output_truncation_notice",
    "apply_audit_evidence_guard",
    "apply_file_delivery_grounding_guard",
    "apply_live_factual_grounding_guard",
    "apply_zero_tool_grounding_guard",
    "asserts_false_fabrication",
    "asserts_ungrounded_claims",
    "claims_bound_tool_unavailable",
    "claims_file_delivery_success",
    "claims_list_dir_embellishment",
    "claims_live_factual_content",
    "claims_success_after_tool_failure",
    "claims_unattempted_tool_failure",
    "is_routing_footer_query",
    "is_self_architecture_query",
    "last_model_stop_reason",
    "steer_for_audit_evidence",
    "steer_for_codemode_loaded_tool",
    "steer_for_direct_tool_call",
    "steer_for_dropped_tool_call",
    "steer_for_fallback_tool",
    "steer_for_false_tool_failure_claim",
    "steer_for_meta_tool_call",
    "steer_for_opener_only",
    "steer_for_playwright_cdp_probe_failure",
    "steer_for_promised_action",
    "steer_for_summarize_after_fetch",
    "steer_for_triager_bound_tools_unused",
    "tier_b_routing_footer_inject",
    "tier_b_self_architecture_inject",
    "tools_attempted_from_call_counts",
    "triager_bound_tools_satisfied",
]
