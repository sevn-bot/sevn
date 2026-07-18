"""Session-scoped ``ToolSet`` snapshots + staged registration helpers (`specs/11-tools-registry.md` §4).

Builds deterministic ``ToolSet`` catalogs alongside a populated ``ToolExecutor``. MCP slices
appear as descriptors independent of sandbox availability so Triager prose blocks stay aligned
with declared servers.

Module: sevn.tools.registry
Depends: sevn.agent.tracing.redacting_sink, sevn.config.defaults, sevn.logging.log_redact,
    sevn.tools.base, sevn.tools.codes, sevn.tools.context, sevn.tools.meta_loaders,
    sevn.tools.runtime_dispatch, importlib.metadata

Exports:
    Classes:
        ToolSet — immutable native vs MCP descriptions + bundled skill manifests.
        McpUnavailableTool — fallback returning ``MCP_UNAVAILABLE`` when no stdio client is wired.
        TracingToolExecutor — ``ToolExecutor`` emitting ``tool.<name>`` spans per dispatch.
    Functions:
        build_session_registry — factory returning ``(executor, tool_set)`` with meta tools.
        register_feature_stubs — register ``integration_call`` / ``sandbox_exec`` (enabled via
            ``runtime_bindings`` or disabled fallback).
        merge_skill_manifests — merge bundled defaults + workspace overlays.
        snapshot_tool_set — freeze the current executor catalog into a ``ToolSet``.
        combine_registry_version — merge tools-base generation with live skills scan state.
        plugin_entrypoint_allowed — honor ``tools.<plugin>.enabled`` toggle defaults.
        load_plugin_tools — enumerate ``Tool`` factories from the ``sevn.tools`` entry-point group.

Examples:
    >>> exe, ts = build_session_registry()
    >>> ts.registry_version >= 1
    True
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from importlib.metadata import EntryPoint, entry_points
from pathlib import Path
from time import time_ns
from typing import TYPE_CHECKING, Any, Final, Literal

from loguru import logger

from sevn.agent.tracing.redacting_sink import TraceRedactionPolicy, redact_attrs
from sevn.agent.tracing.sink import TraceEvent
from sevn.config.defaults import INITIAL_REGISTRY_VERSION, TOOL_DEBUG_RESULT_LOG_HARD_CAP
from sevn.config.workspace_config import WorkspaceConfig
from sevn.logging.log_redact import redact_log_line
from sevn.tools.base import (
    FunctionTool,
    Tool,
    ToolCall,
    ToolDefinition,
    ToolExecutor,
    _json_safe_attrs,
    enveloped_failure,
    enveloped_success,
)
from sevn.tools.codes import ToolResultCode
from sevn.tools.context import ToolContext
from sevn.tools.meta_loaders import attach_meta_loaders
from sevn.tools.paths import rebase_checkout_absolute_path
from sevn.tools.runtime_dispatch import (
    McpStdioTool,
    RuntimeToolBindings,
    make_integration_call_tool,
    make_sandbox_exec_tool,
)

if TYPE_CHECKING:
    from sevn.agent.tracing.sink import TraceSink
    from sevn.skills.manager import SkillsManager
    from sevn.workspace.layout import WorkspaceLayout

_PACKAGED_TOOLS_ENTRY_SKIP: frozenset[str] = frozenset({"sevn_core_reserved_plugin_table"})

DEFAULT_TOOL_MANIFESTS: Final[dict[str, str]] = {
    "load_tool": "Lazy-load JSON schema + capability rows for another registry tool.",
    "load_skill": "Load skill menu (default) or full skill manifest when full=true.",
    "list_registry": "List enabled registry tool names and bundled skill names for this session.",
    "integration_call": "Delegate to configured external integrations (APIs, gh CLI, MCP).",
    "sandbox_exec": "Run code in an isolated sandbox when runtime bindings enable it.",
    "run_skill_script": "Execute a skill script entrypoint from an indexed skill package.",
    "run_skill_runnable": "Invoke a skill runnable surface from an indexed skill package.",
    "skill_create": "Scaffold a new generated skill under workspace/skills/generated/.",
    "promote_generated_skill": "Promote a generated skill into workspace/skills/user/.",
    "openui_render": "Render OpenUI analytical layouts in supported channels.",
    "wiki_search": "Second Brain wiki search (requires second_brain.enabled in sevn.json).",
    "wiki_get": "Fetch a Second Brain wiki page by id or path.",
    "wiki_apply": "Apply structured edits to Second Brain wiki pages.",
    "wiki_lint": "Lint Second Brain wiki structure and links.",
    "second_brain_query": "Query the Second Brain index (requires second_brain.enabled).",
    "second_brain_ingest_stub": "Legacy ingest stub (gated; use second_brain skill ingest).",
    "code_graph_rag_read_export": "Read code-graph RAG export slices (code_understanding.code_graph_rag).",
    "code_graph_rag_cli": "Run code-graph RAG CLI helpers (code_understanding.code_graph_rag).",
    "roam_code": "Roam-style code exploration tool (code_understanding.roam_code).",
    "write_workspace_md": (
        "Write bootstrap narrative markdown (USER/SOUL/IDENTITY/MEMORY.md only; first-session)."
    ),
    "read": "Read a workspace file (line-numbered) or list a directory.",
    "list_dir": "List a workspace directory with file metadata.",
    "glob": "Glob-find files under a workspace directory by pattern.",
    "search_in_file": "Ripgrep-style pattern search across a workspace file tree.",
    "find_file": "Find files by exact or partial filename under a workspace tree.",
    "get_module_docstring": "Return top-of-file Python module docstring with line range.",
    "get_symbol_docstring": "Return top-level class/function docstring with line range.",
    "list_symbols": "List top-level Python classes/functions with line ranges.",
    "file_info": "Return metadata (size, mtime, type, mode) for one workspace path.",
    "write": "Write or overwrite a workspace file; create parent directories.",
    "edit": "Replace exactly one unique occurrence of old_string in a file.",
    "create_folder": "Create a workspace directory (mkdir -p).",
    "move_file": "Move or rename a workspace file or directory.",
    "copy_file": "Copy a workspace file or directory tree to a new path.",
    "delete": "Delete a workspace file or directory tree (requires human approval).",
    "memory_get": "Get the latest SQLite memory snippet for a session key.",
    "memory_store": "Store a short-term memory snippet in workspace SQLite.",
    "memory_search": "Federated search across SQLite memory, daily logs, and MEMORY.md.",
    "file_evolution_issue": "File a bug or feature evolution issue (local JSON; optional GitHub mirror).",
    "serp": "Search the web via DuckDuckGo (ddgs; no API key or proxy).",
    "web_search": "Premium Brave search (proxy + Brave API key; auto-falls back to serp).",
    "get_page_content": "Fetch a URL and return clean markdown (egress proxy).",
    "web_fetch": "Full HTTP via egress proxy (paired with gateway in standard deploy).",
    "message": "Send a proactive text message on the active or specified channel.",
    "send_file": "Send a workspace file to the user on their active channel.",
    "tts": "Convert text to speech and deliver audio on the active channel.",
    "log_query": "Read/tail/filter workspace logs with offset_from_tail, starting_reading_line, or ranges (default gateway.log).",
    "llm_guard_scan": "Manually scan suspect text for prompt injection and policy violations.",
    "semantic_search": "Search workspace memory and conversations by meaning via Witchcraft.",
    "process": "Start, stop, list, or read output from background workspace subprocesses.",
    "terminal_spawn": "Open a persistent interactive shell (pexpect; echo health-probed).",
    "terminal_run": (
        "Run a command in a terminal session; use process for pip install / long jobs."
    ),
    "terminal_close": "Close a persistent terminal session opened with terminal_spawn.",
}

DEFAULT_SKILL_MANIFESTS: Final[dict[str, str]] = {
    "browser-harness": "Thin CDP harness with extendable helpers.py for open-ended browser control.",
    "canvas": "Bundled OpenUI compose helpers for analytical layouts (pairs with openui_render).",
    "code_graph_rag": "CGR export reader + allowlisted cgr CLI scripts.",
    "computer-use": (
        "Drive a computer via trycua/cua: host cua-driver MCP passthrough plus sandbox "
        "providers (docker/cloud/lume) through the cua CLI (opt-in; macOS-only)."
    ),
    "cua-agent": (
        "Autonomous GUI loop via cua-agent toward a goal; requires computer-use enabled "
        "and explicit per-run operator approval (opt-in; macOS-only)."
    ),
    "lume": (
        "Apple-Silicon VM lifecycle via lume CLI (run/stop/ls/pull); opt-in; "
        "also a computer-use sandbox target via cua do switch lume."
    ),
    "conventional_commit": (
        "Draft Conventional Commits 1.0.0 messages before ``git commit``; "
        "the commit-msg hook rejects non-conforming subjects."
    ),
    "email-management": "Multi-account IMAP and Gmail API mail read/search/send scripts.",
    "google-workspace": (
        "Gmail, Calendar, Drive, and Contacts via OAuth2 Google Workspace APIs "
        "(Sheets/Docs planned)."
    ),
    "gh-issues": "GitHub issue lifecycle — list, view, create, comment via integration_call.",
    "gh-pr": "Pull request lifecycle — list, view, create, merge, close via integration_call.",
    "github-manager": "Advanced GitHub — branches, Actions, secrets, envs via integration_call.",
    "graphify": "Knowledge-graph orientation for code (Graphify CLI subprocess or dry-run plan).",
    "job-ops": (
        "Discover jobs across global + Europe boards, AI fit-score against resume, "
        "and optionally tailor a CV summary (JobOps port)."
    ),
    "last30days": "Multi-source social/web research engine (Reddit, X, YouTube, HN, Polymarket).",
    "lcm": "Lossless-context skill menu (grep, describe, expand, fetch, meta, summaries).",
    "media_generation": (
        "MiniMax-backed image/video/music generation via the media_generator level-2 specialist."
    ),
    "mycode": "Deterministic repo scan + MYCODE.md generation (alias mycode_scan).",
    "openwiki": "LLM-generated agent wiki for a codebase (LangChain OpenWiki CLI).",
    "pdf": "PDF generate, read, and load helpers routed through skill runners.",
    "printing-press-library": (
        "Starter-pack Printing Press CLIs — ESPN, flights, movies, recipes (host Go binaries)."
    ),
    "proton-management": (
        "Proton suite CLI (Python port) — Pass vaults/items with E2EE; Mail/Drive/Calendar/Contacts planned."
    ),
    "roam_code": "Lightweight roam-code path Q&A without a persistent graph DB.",
    "scheduling": "Cron/reminder authoring via bundled scripts.",
    "sevn-diagnostics": (
        "Operator repair playbooks for ``sevn doctor --with-agent`` "
        "(gateway, secrets, proxy, models, browser, voice)."
    ),
    "cursor_cloud": "Delegate code+PR work to Cursor Cloud Agent; PR, dashboard, artifacts.",
    "defuddle": "Extract clean markdown from web pages with Defuddle CLI.",
    "discogs-collection": (
        "Discogs user collection — folders, items, value, and collection search; "
        "confirm-gated writes."
    ),
    "discogs-database": (
        "Discogs public catalog — search, artist/release/master/label lookups, "
        "price suggestions, marketplace stats."
    ),
    "discogs-identity": (
        "Discogs authed user profile, lists, contributions, and whoami smoke-test."
    ),
    "discogs-marketplace": (
        "Discogs marketplace — inventory search, listings CRUD, orders, messages, "
        "and fee lookup; confirm-gated writes."
    ),
    "discogs-wantlist": (
        "Discogs user wantlist browse, search, and add/remove/edit; confirm-gated writes."
    ),
    "json-canvas": "Create and edit Obsidian JSON Canvas files.",
    "obsidian-bases": "Create and edit Obsidian Bases files.",
    "obsidian-cli": "Interact with Obsidian vaults using the Obsidian CLI.",
    "obsidian-markdown": "Create and edit Obsidian Flavored Markdown.",
    "second_brain": "Second Brain wiki query, ingest, and lint automation.",
    "sessions_management": "Gateway sessions, history, spawn, yield, and status scripts.",
    "skill_management": "Authoring workflows for manifests and promotions.",
    "social_media_manager": (
        "Monitor and interact with social media via TwexAPI and the sevn CDP "
        "browser tool (unified X ops facade; six-site social recipes)."
    ),
    "telegram": "Telegram inline buttons and forum supergroup helpers.",
    "yt-dlp": "Download video/audio and metadata with yt-dlp (allowlisted hosts).",
}


@dataclass(frozen=True)
class ToolSet:
    """Immutable descriptors powering Triager and adapter scaffolding."""

    registry_version: int
    native: tuple[ToolDefinition, ...]
    mcp: tuple[ToolDefinition, ...]
    skill_descriptions: dict[str, str]
    skill_inventory: dict[str, dict[str, object]] = field(default_factory=dict)


def _truncate_result(raw: str, *, limit: int = 512) -> str:
    """Return ``raw`` truncated for trace attrs when oversized.

    Args:
        raw (str): Tool envelope JSON string.
        limit (int): Maximum stored length.
    Returns:
        str: Original or truncated payload with marker suffix.
    Examples:
        >>> _truncate_result("abc", limit=10)
        'abc'
        >>> len(_truncate_result("x" * 20, limit=10))
        10
    """
    if len(raw) <= limit:
        return raw
    return raw[: limit - 3] + "..."


def _tool_debug_arg_values(arguments: object) -> str:
    """Format redacted tool arguments for ``tool_call.*`` DEBUG lines.

    Args:
        arguments (object): ``ToolCall.arguments`` mapping or other payload.

    Returns:
        str: Compact JSON object string safe for gateway service logs.

    Examples:
        >>> _tool_debug_arg_values({"name": "lcm"})
        '{"name":"lcm"}'
    """
    if not isinstance(arguments, dict):
        return "{}"
    policy = TraceRedactionPolicy.from_defaults()
    safe = redact_attrs(_json_safe_attrs(dict(arguments)), policy)
    text = json.dumps(safe, separators=(",", ":"), ensure_ascii=False)
    return redact_log_line(text)


def _tool_debug_result(raw: str, *, max_chars: int | None) -> str:
    """Format a tool envelope for ``tool_call.finish`` / ``tool_call.cached`` DEBUG lines.

    Bounds the LOG rendering only — the full envelope is still returned to the
    model. ``max_chars`` (``logging.tool_debug_result_max_chars``) caps the
    preview when set; an unconditional :data:`TOOL_DEBUG_RESULT_LOG_HARD_CAP`
    ceiling then guards against megabyte ``read`` / ``log_query`` payloads
    spilling into ``gateway.log`` and feeding recursive ``log_query`` bloat
    (`specs/11-tools-registry.md` §10.13). When elided, a ``...[+N chars]``
    marker records the original size.

    Args:
        raw (str): JSON envelope returned by the tool dispatcher.
        max_chars (int | None): When set, truncate the preview to this many chars;
            ``None`` falls through to the hard ceiling only.

    Returns:
        str: Redacted, size-bounded result text for log inclusion.

    Examples:
        >>> _tool_debug_result('{"ok":true}', max_chars=None)
        '{"ok":true}'
        >>> _tool_debug_result("x" * 100, max_chars=20).startswith("x" * 20)
        True
        >>> _tool_debug_result("x" * 9000, max_chars=None).endswith(" chars]")
        True
    """
    limit = max_chars if max_chars is not None else TOOL_DEBUG_RESULT_LOG_HARD_CAP
    if max_chars is not None:
        limit = min(limit, TOOL_DEBUG_RESULT_LOG_HARD_CAP)
    if len(raw) > limit:
        elided = len(raw) - limit
        text = f"{raw[:limit]}...[+{elided} chars]"
    else:
        text = raw
    return redact_log_line(text)


_CACHEABLE_FAILURE_CODES: Final[frozenset[str]] = frozenset(
    {
        "UNKNOWN_TOOL",
        "VALIDATION_ERROR",
    }
)
"""``ToolResultCode`` values safe to cache in :class:`ToolContext.negative_cache`.

These represent **structural** failures whose verdict won't change within a
turn given the same arguments — missing files, unknown tool/skill names,
malformed arg shapes. Gating codes (``PLAN_HUMAN_GATE``), transport codes
(``MCP_UNAVAILABLE``), and provider timeouts are explicitly **not** cached
because their state can flip mid-turn (e.g. the executor acknowledges
``requires_human`` and the next dispatch should be allowed through).
"""

_NON_CACHEABLE_TOOL_NAMES: Final[frozenset[str]] = frozenset(
    {
        "run_skill_script",
        "run_skill_runnable",
    }
)
"""Skill runners whose failures may change after ``did_you_mean`` or argv fixes.

Execution envelopes (e.g. pdf ``VALIDATION_ERROR`` for path escape) must not
replay from :attr:`ToolContext.negative_cache` within the same turn.
"""


def _is_cacheable_failure(raw: str, *, tool_name: str = "") -> bool:
    """Return ``True`` when this failure envelope is safe to negative-cache.

    Args:
        raw (str): JSON envelope string.
        tool_name (str, optional): Dispatching tool name; skill runners are never
            cached even when the envelope code is structural. Defaults to ``""``.

    Returns:
        bool: ``True`` only when ``code`` is in :data:`_CACHEABLE_FAILURE_CODES`.

    Examples:
        >>> _is_cacheable_failure('{"ok":false,"code":"VALIDATION_ERROR"}')
        True
        >>> _is_cacheable_failure(
        ...     '{"ok":false,"code":"VALIDATION_ERROR"}', tool_name="run_skill_script"
        ... )
        False
        >>> _is_cacheable_failure('{"ok":false,"code":"PLAN_HUMAN_GATE"}')
        False
        >>> _is_cacheable_failure('{"ok":true}')
        False
    """
    if tool_name in _NON_CACHEABLE_TOOL_NAMES:
        return False
    try:
        blob = json.loads(raw)
    except json.JSONDecodeError:
        return False
    if not isinstance(blob, dict) or blob.get("ok") is not False:
        return False
    return str(blob.get("code", "")) in _CACHEABLE_FAILURE_CODES


def _read_range_key(arguments: object) -> tuple[str, int | None, int | None] | None:
    """Compute the ``(path, offset, limit)`` dedupe key for a ``read`` call.

    Args:
        arguments (object): The ``read`` call's ``arguments`` payload.

    Returns:
        tuple[str, int | None, int | None] | None: Key when ``path`` is a non-empty
        string; ``None`` otherwise (no dedupe attempted).

    Examples:
        >>> _read_range_key({"path": "a.py"})
        ('a.py', None, None)
        >>> _read_range_key({"path": "a.py", "offset": 1, "limit": 50})
        ('a.py', 1, 50)
        >>> _read_range_key({}) is None
        True
    """
    if not isinstance(arguments, dict):
        return None
    raw_path = arguments.get("path")
    if not isinstance(raw_path, str) or not raw_path:
        return None

    def _coerce(value: object) -> int | None:
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    return (raw_path, _coerce(arguments.get("offset")), _coerce(arguments.get("limit")))


def _already_read_notice(key: tuple[str, int | None, int | None]) -> str:
    """Build the compact ``read`` short-circuit envelope for a repeat range read.

    Keeps the FIRST read full; identical repeats within the turn get a small
    notice pointing back at the earlier result instead of re-emitting the body
    (`specs/11-tools-registry.md` §10.13).

    Args:
        key (tuple[str, int | None, int | None]): ``(path, offset, limit)`` key.

    Returns:
        str: §3.1 success envelope with ``deduped=True`` and a pointer message.

    Examples:
        >>> import json
        >>> blob = json.loads(_already_read_notice(("a.py", None, None)))
        >>> blob["ok"], blob["data"]["deduped"]
        (True, True)
    """
    path, offset, limit = key
    span = ""
    if offset is not None or limit is not None:
        span = f" (offset={offset}, limit={limit})"
    return enveloped_success(
        {
            "path": path,
            "kind": "file",
            "deduped": True,
            "content": (
                f"already read above (see the earlier result for {path}{span} in this turn)"
            ),
        },
        message="repeat read short-circuited; reuse the earlier full result",
    )


def _message_dedup_key(arguments: object) -> tuple[str, str, str] | None:
    """Compute the ``(channel, user_id, text)`` dedupe key for a ``message`` call.

    Args:
        arguments (object): The ``message`` call's ``arguments`` payload.

    Returns:
        tuple[str, str, str] | None: Key when ``text`` is a non-empty string after
        stripping; ``None`` otherwise (no dedupe attempted). ``channel`` and
        ``user_id`` fall back to ``""`` so the destination defaults resolve to the
        active session, matching :func:`message_tool`.

    Examples:
        >>> _message_dedup_key({"text": "hi"})
        ('', '', 'hi')
        >>> _message_dedup_key({"text": "  hi  ", "channel": "telegram"})
        ('telegram', '', 'hi')
        >>> _message_dedup_key({"text": "   "}) is None
        True
        >>> _message_dedup_key({}) is None
        True
    """
    if not isinstance(arguments, dict):
        return None
    raw_text = arguments.get("text")
    if not isinstance(raw_text, str):
        return None
    body = raw_text.strip()
    if not body:
        return None

    def _coerce(value: object) -> str:
        return value.strip() if isinstance(value, str) else ""

    return (_coerce(arguments.get("channel")), _coerce(arguments.get("user_id")), body)


def _already_sent_notice(key: tuple[str, str, str]) -> str:
    """Build the short-circuit envelope for a repeat outbound ``message`` send.

    Delivers the FIRST send; identical repeats within the turn are NOT re-delivered
    (so a looping model cannot spam the user) and instead get a notice instructing
    the model to stop resending and finish the turn (`specs/11-tools-registry.md`
    §10.13).

    Args:
        key (tuple[str, str, str]): ``(channel, user_id, text)`` key.

    Returns:
        str: §3.1 success envelope with ``deduped=True`` and a stop-resending message.

    Examples:
        >>> import json
        >>> blob = json.loads(_already_sent_notice(("telegram", "u1", "hi")))
        >>> blob["ok"], blob["data"]["deduped"], blob["data"]["delivered"]
        (True, True, False)
    """
    channel, user_id, _text = key
    return enveloped_success(
        {
            "channel": channel,
            "user_id": user_id,
            "deduped": True,
            "delivered": False,
            "content": (
                "this exact message was already delivered earlier in this turn; "
                "it was NOT sent again. Do not resend the same text — finish your "
                "turn now or send new content."
            ),
        },
        message="duplicate outbound message short-circuited; the user already received this line",
    )


def _stable_args_key(arguments: object) -> str:
    """Compute a deterministic JSON key for the per-turn negative cache.

    Args:
        arguments (object): The tool call's ``arguments`` payload (dict or other).

    Returns:
        str: Canonical JSON serialization; falls back to ``repr`` for unhashables.

    Examples:
        >>> _stable_args_key({"path": "a", "limit": 5})
        '{"limit": 5, "path": "a"}'
        >>> _stable_args_key({"path": "a"}) == _stable_args_key({"path": "a"})
        True
    """
    try:
        return json.dumps(arguments, sort_keys=True, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        return repr(arguments)


def _did_you_mean_for_read(ctx: ToolContext, arguments: object, limit: int = 5) -> list[str]:
    """Fuzzy suggestions for a ``read`` tool ``not found`` error.

    Search surface (``PROBLEMS.md`` §Priority 1.h, bounded):

    - stale-prefix correction: a ``workspace/<X>`` (or ``./<X>``) path whose bare
      ``<X>`` actually resolves — workspace/user files are bare paths at the root,
      there is no ``workspace/`` directory.
    - parent directory of the missing path (workspace-relative resolution)
    - ``<workspace>/skills/`` directory entries

    Source code lives in the workspace at ``source_code/`` (full-repo mirror), so
    checkout files are matched through the normal workspace-relative resolution.
    Capped at 5000 entries to keep the matcher fast (~5ms typical).

    Args:
        ctx (ToolContext): Active dispatch context (provides the workspace root).
        arguments (object): ``read`` call arguments — only ``path`` is read.
        limit (int): Max suggestions to return.

    Returns:
        list[str]: Suggested paths the agent could retry. Empty when nothing
        plausible matched.

    Examples:
        >>> from sevn.tools.context import ToolContext
        >>> from pathlib import Path
        >>> ctx = ToolContext(session_id="s", workspace_path=Path("/tmp"),
        ...     workspace_id="w", registry_version=1)
        >>> isinstance(_did_you_mean_for_read(ctx, {}), list)
        True
    """
    import difflib

    if not isinstance(arguments, dict):
        return []
    raw_path = arguments.get("path")
    if not isinstance(raw_path, str) or not raw_path:
        return []

    suggestions: list[str] = []
    workspace = ctx.workspace_path

    # Stale-prefix correction (PROBLEMS.md §P2 path guidance): workspace/user
    # files resolve as BARE paths at the workspace root (there is no `workspace/`
    # directory) and the read-only source mirror lives under `source_code/`. The
    # model often guesses a `workspace/<X>` (or, after a `source_code/` miss, a
    # bare-vs-mirror) prefix. When stripping a known prefix points at a path that
    # actually exists, surface it first so the retry lands immediately.
    for prefix in ("workspace/", "./"):
        if raw_path.startswith(prefix):
            stripped = raw_path[len(prefix) :]
            if stripped and (workspace / stripped).exists():
                suggestions.append(stripped)

    # Absolute checkout path correction (Mode B): the model echoed the absolute sevn
    # checkout path (e.g. `/…/sevn.bot/src/x.py`) instead of the `source_code/` mirror.
    # The resolver rebases these onto `source_code/<rel>` when the mirror has them, but
    # for runtime artefacts that only live in the workspace (e.g. `logs/gateway.log`)
    # the mirror miss surfaces here — suggest the `source_code/<rel>` mirror path and the
    # bare workspace-relative tail, whichever exists.
    rebased = rebase_checkout_absolute_path(raw_path, ctx.checkout_path)
    if rebased is not None:
        if (workspace / rebased).exists():
            suggestions.append(rebased)
        bare_tail = rebased[len("source_code/") :] if rebased.startswith("source_code/") else ""
        if bare_tail and (workspace / bare_tail).exists():
            suggestions.append(bare_tail)

    # Skill source path correction: agents often guess ``skills/<name>/…`` instead
    # of the seeded ``skills/core/<name>/…`` tree (live-session pdf miss).
    parts = Path(raw_path).parts
    if (
        len(parts) >= 2
        and parts[0] == "skills"
        and parts[1]
        not in (
            "core",
            "user",
            "generated",
            "plugins",
        )
    ):
        skill_name = parts[1]
        rest = Path(*parts[2:]).as_posix() if len(parts) > 2 else ""
        for prov in ("core", "user", "generated"):
            candidate = (
                f"skills/{prov}/{skill_name}/{rest}" if rest else f"skills/{prov}/{skill_name}"
            )
            if (workspace / candidate).exists():
                suggestions.append(candidate)

    # Candidate pool: parent dir contents + workspace skills/.
    pool: set[str] = set()
    candidate_parents: list[Path] = []
    parent = (workspace / raw_path).parent
    if parent.is_dir():
        candidate_parents.append(parent)
    ws_skills = workspace / "skills"
    if ws_skills.is_dir():
        candidate_parents.append(ws_skills)

    needle = Path(raw_path).name
    cap = 5000
    for d in candidate_parents:
        try:
            for entry in d.iterdir():
                if len(pool) >= cap:
                    break
                pool.add(entry.name)
        except OSError:
            continue
        if len(pool) >= cap:
            break

    close = difflib.get_close_matches(needle, sorted(pool), n=limit, cutoff=0.6)
    for name in close:
        # Reconstruct a likely full path: parent of the missing file + matched name.
        if (workspace / raw_path).parent.exists():
            suggestions.append(str(Path(raw_path).with_name(name)))
    # De-dupe, preserve order, cap.
    seen: set[str] = set()
    out: list[str] = []
    for s in suggestions:
        if s not in seen:
            seen.add(s)
            out.append(s)
        if len(out) >= limit:
            break
    return out


def _did_you_mean_for_load_tool(ctx: ToolContext, arguments: object, limit: int = 5) -> list[str]:
    """Fuzzy suggestions for ``load_tool`` ``No enabled tool named`` errors.

    Matches against the live registry snapshot in
    :attr:`ToolContext.known_tool_names`. When the snapshot is empty (legacy
    contexts that didn't populate it), returns ``[]`` rather than guessing.

    Args:
        ctx (ToolContext): Active dispatch context (provides the tool name set).
        arguments (object): ``load_tool`` call arguments — only ``name`` is read.
        limit (int): Max suggestions to return.

    Returns:
        list[str]: Registered tool names closest to the requested one.

    Examples:
        >>> from sevn.tools.context import ToolContext
        >>> from pathlib import Path
        >>> ctx = ToolContext(session_id="s", workspace_path=Path("/tmp"),
        ...     workspace_id="w", registry_version=1,
        ...     known_tool_names=frozenset({"search_code", "search_in_file"}))
        >>> _did_you_mean_for_load_tool(ctx, {"name": "search"})
        ['search_code', 'search_in_file']
    """
    import difflib

    if not isinstance(arguments, dict):
        return []
    raw_name = arguments.get("name")
    if not isinstance(raw_name, str) or not raw_name:
        return []
    if not ctx.known_tool_names:
        return []
    return difflib.get_close_matches(raw_name, sorted(ctx.known_tool_names), n=limit, cutoff=0.5)


def _did_you_mean_for_run_skill_script(
    ctx: ToolContext,
    arguments: object,
    *,
    limit: int = 5,
) -> list[str]:
    """Fuzzy-match declared skill script paths — never echo unknown input.

    Args:
        ctx (ToolContext): Active dispatch context (workspace root for scan).
        arguments (object): ``run_skill_script`` call arguments — ``skill`` and
            ``script`` are read.
        limit (int): Max suggestions.

    Returns:
        list[str]: Manifest ``scripts:`` paths closest to the requested script.

    Examples:
        >>> from pathlib import Path
        >>> from sevn.tools.context import ToolContext
        >>> ctx = ToolContext(session_id="s", workspace_path=Path("/tmp"),
        ...     workspace_id="w", registry_version=1)
        >>> isinstance(_did_you_mean_for_run_skill_script(ctx, {}), list)
        True
    """
    if not isinstance(arguments, dict):
        return []
    skill = arguments.get("skill")
    raw = arguments.get("script")
    if not isinstance(skill, str) or not isinstance(raw, str) or not raw:
        return []
    from sevn.skills.manager import did_you_mean_skill_script

    return did_you_mean_skill_script(ctx.workspace_path, skill, raw, limit=limit)


def _did_you_mean_for_load_skill(arguments: object, limit: int = 5) -> list[str]:
    """Fuzzy suggestions for ``load_skill`` ``unknown skill`` errors.

    Matches against the workspace-authoritative ``skills/INDEX.md`` (via
    :func:`sevn.data.skills_index.read_skills_index`). Self-healing for new
    skills — no maintenance burden.

    Args:
        arguments (object): ``load_skill`` call arguments — only ``name`` is read.
        limit (int): Max suggestions to return.

    Returns:
        list[str]: Skill names from the index closest to the requested one.

    Examples:
        >>> isinstance(_did_you_mean_for_load_skill({"name": "graph"}), list)
        True
    """
    import difflib

    from sevn.data.skills_index import read_skills_index

    if not isinstance(arguments, dict):
        return []
    raw_name = arguments.get("name")
    if not isinstance(raw_name, str) or not raw_name:
        return []
    candidates = sorted(read_skills_index().keys())
    return difflib.get_close_matches(raw_name, candidates, n=limit, cutoff=0.5)


_PROCESS_VALID_ACTIONS: Final[tuple[str, ...]] = ("start", "stop", "list", "output")


def _did_you_mean_for_process(arguments: object, limit: int = 4) -> list[str]:
    """Fuzzy suggestions for ``process`` ``unknown action`` errors.

    Args:
        arguments (object): ``process`` call arguments — only ``action`` is read.
        limit (int): Max suggestions to return.

    Returns:
        list[str]: The four valid ``process`` actions (``start``, ``stop``, ``list``,
        ``output``), ordered by similarity to the requested (invalid) action. Never empty,
        so an invalid or absent ``action`` always ships actionable guidance (W5.2,
        `build-plan-from-review/waves/voice-duplex-tts-menu-log-fixes-wave-plan.md`).

    Examples:
        >>> _did_you_mean_for_process({"action": "read"})
        ['start', 'stop', 'output', 'list']
        >>> _did_you_mean_for_process({})
        ['start', 'stop', 'list', 'output']
    """
    import difflib

    raw_action = arguments.get("action") if isinstance(arguments, dict) else None
    if isinstance(raw_action, str) and raw_action in _PROCESS_VALID_ACTIONS:
        # Action was already valid — the failure is about something else (e.g. a
        # missing job_id for action=stop), so an action suggestion would mislead.
        return []
    if not isinstance(raw_action, str) or not raw_action:
        return list(_PROCESS_VALID_ACTIONS[:limit])
    close = difflib.get_close_matches(raw_action, _PROCESS_VALID_ACTIONS, n=limit, cutoff=0.0)
    return close or list(_PROCESS_VALID_ACTIONS[:limit])


def _inject_did_you_mean(ctx: ToolContext, call: ToolCall, raw: str) -> str:
    """Attach a ``did_you_mean`` field to a failure envelope when applicable.

    Bounded fuzzy matchers per tool (``PROBLEMS.md`` §Priority 1.h). Self-
    healing: the matcher targets live state (filesystem, skills index) so new
    errors are auto-covered without maintenance.

    Currently wired:

    - ``read``: parent-dir + workspace ``skills/`` fuzzy match.
    - ``load_skill``: matches against ``skills/INDEX.md`` entries.
    - ``load_tool``: matches against the live registry snapshot.
    - ``run_skill_script``: matches against declared manifest script paths.
    - ``process``: matches an invalid ``action`` against ``start|stop|list|output``
      (`build-plan-from-review/waves/voice-duplex-tts-menu-log-fixes-wave-plan.md` W5.2).

    Other tools fall through unchanged until a matcher is wired for them.

    Args:
        ctx (ToolContext): Active dispatch context.
        call (ToolCall): Tool call identifier + arguments.
        raw (str): Raw JSON envelope returned by the tool.

    Returns:
        str: Possibly rewritten envelope with a ``did_you_mean`` list field.

    Examples:
        >>> from sevn.tools.base import ToolCall
        >>> from sevn.tools.context import ToolContext
        >>> from pathlib import Path
        >>> ctx = ToolContext(session_id="s", workspace_path=Path("/tmp"),
        ...     workspace_id="w", registry_version=1)
        >>> call = ToolCall(name="read", arguments={"path": "x"})
        >>> _inject_did_you_mean(ctx, call, '{"ok":true,"data":{}}')
        '{"ok":true,"data":{}}'
    """
    try:
        blob = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    if not isinstance(blob, dict) or blob.get("ok") is not False:
        return raw
    if "did_you_mean" in blob:
        return raw  # respect tool-provided suggestions
    suggestions: list[str]
    if call.name == "read":
        suggestions = _did_you_mean_for_read(ctx, call.arguments)
    elif call.name == "load_skill":
        suggestions = _did_you_mean_for_load_skill(call.arguments)
    elif call.name == "load_tool":
        suggestions = _did_you_mean_for_load_tool(ctx, call.arguments)
    elif call.name == "run_skill_script":
        suggestions = _did_you_mean_for_run_skill_script(ctx, call.arguments)
    elif call.name == "process":
        suggestions = _did_you_mean_for_process(call.arguments)
    else:
        suggestions = []
    if not suggestions:
        return raw
    blob["did_you_mean"] = suggestions
    return json.dumps(blob, separators=(",", ":"), ensure_ascii=False)


_UPSTREAM_PROXY_STATUS_RE = re.compile(r"\bproxy status (\d{3})\b", re.IGNORECASE)
_RETYPABLE_UPSTREAM_CODES: Final[frozenset[str]] = frozenset(
    {ToolResultCode.INTERNAL_ERROR.value, ToolResultCode.SKILL_SCRIPT_NONZERO.value}
)


def _maybe_retype_upstream_proxy_error(raw: str) -> str:
    """Retype a bare ``proxy status NNN`` failure as :attr:`ToolResultCode.UPSTREAM_ERROR`.

    Covers dispatch paths that never route through :func:`make_integration_call_tool`'s
    own typed handling — e.g. a ``run_skill_script`` github branch-list wrapper whose
    subprocess surfaces the egress proxy's raw ``RuntimeError(f"proxy status {status}")``
    text as a ``SKILL_SCRIPT_NONZERO``/``INTERNAL_ERROR`` dead end (W5.4,
    `build-plan-from-review/waves/voice-duplex-tts-menu-log-fixes-wave-plan.md`). Leaves
    ``did_you_mean`` untouched — :func:`_inject_did_you_mean` runs immediately after.

    Args:
        raw (str): Raw JSON envelope returned by the tool.

    Returns:
        str: The envelope with ``code`` rewritten to ``UPSTREAM_ERROR`` when the error text
        names a ``proxy status NNN`` failure on a generic/nonzero-exit code; unchanged
        otherwise (including on JSON decode failure, non-dict payloads, or successes).

    Examples:
        >>> _maybe_retype_upstream_proxy_error(
        ...     '{"ok":false,"code":"INTERNAL_ERROR","error":"proxy status 404"}'
        ... )
        '{"ok":false,"code":"UPSTREAM_ERROR","error":"proxy status 404"}'
        >>> _maybe_retype_upstream_proxy_error('{"ok":false,"code":"VALIDATION_ERROR"}')
        '{"ok":false,"code":"VALIDATION_ERROR"}'
    """
    try:
        blob = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    if not isinstance(blob, dict) or blob.get("ok") is not False:
        return raw
    if blob.get("code") not in _RETYPABLE_UPSTREAM_CODES:
        return raw
    if not _UPSTREAM_PROXY_STATUS_RE.search(str(blob.get("error") or "")):
        return raw
    blob["code"] = ToolResultCode.UPSTREAM_ERROR.value
    return json.dumps(blob, separators=(",", ":"), ensure_ascii=False)


class TracingToolExecutor(ToolExecutor):
    """Wrap :class:`ToolExecutor.dispatch` with ``tool.<name>`` lifecycle spans."""

    async def dispatch(
        self,
        ctx: ToolContext,
        call: ToolCall,
        *,
        timeout_seconds: float | None | Literal["default"] = "default",
    ) -> str:
        """Dispatch ``call`` and emit ``tool.<name>`` start / finish trace rows.

        Args:
            ctx (ToolContext): Runtime frame (session/workspace/trace).
            call (ToolCall): Invoked tool identifier + kwargs dict.
            timeout_seconds (float | None | "default"): Per-call deadline passthrough.
        Returns:
            str: JSON envelope string from the inner executor.
        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(TracingToolExecutor.dispatch)
            True
        """
        name = call.name
        sink = ctx.trace
        span_id = str(uuid.uuid4())
        parent_span_id = ctx.turn_span_id
        start_ns = time_ns()
        try:
            _arg_keys = sorted(call.arguments.keys()) if isinstance(call.arguments, dict) else None
        except Exception:
            _arg_keys = None
        _arg_values = _tool_debug_arg_values(call.arguments)
        _result_log_max = ctx.tool_debug_result_max_chars
        cache_key = (name, _stable_args_key(call.arguments))
        if name == "load_tool" and isinstance(call.arguments, dict):
            load_name = str(call.arguments.get("name", "")).strip()
            if load_name:
                cached_load = ctx.loaded_tools.get(load_name)
                if cached_load is not None:
                    logger.debug(
                        "tool_call.cached name={} tier={} arg_keys={} arg_values={} "
                        "result={} span_id={}",
                        name,
                        ctx.executor_tier,
                        _arg_keys,
                        _arg_values,
                        _tool_debug_result(cached_load, max_chars=_result_log_max),
                        span_id,
                    )
                    if sink is not None:
                        cached_ns = time_ns()
                        await sink.emit(
                            TraceEvent(
                                kind=f"tool.{name}",
                                span_id=span_id,
                                parent_span_id=parent_span_id,
                                session_id=ctx.session_id,
                                turn_id=ctx.turn_id,
                                tier=ctx.executor_tier,
                                ts_start_ns=start_ns,
                                ts_end_ns=cached_ns,
                                status="cached",
                                attrs={
                                    "args": _json_safe_attrs(dict(call.arguments)),
                                    "result": _truncate_result(cached_load),
                                },
                            ),
                        )
                    return cached_load
        cached = ctx.negative_cache.get(cache_key)
        if cached is not None:
            logger.debug(
                "tool_call.cached name={} tier={} arg_keys={} arg_values={} result={} span_id={} turn_id={}",
                name,
                ctx.executor_tier,
                _arg_keys,
                _arg_values,
                _tool_debug_result(cached, max_chars=_result_log_max),
                span_id,
                ctx.turn_id,
            )
            if sink is not None:
                cached_ns = time_ns()
                await sink.emit(
                    TraceEvent(
                        kind=f"tool.{name}",
                        span_id=span_id,
                        parent_span_id=parent_span_id,
                        session_id=ctx.session_id,
                        turn_id=ctx.turn_id,
                        tier=ctx.executor_tier,
                        ts_start_ns=start_ns,
                        ts_end_ns=cached_ns,
                        status="cached_error",
                        attrs={
                            "args": _json_safe_attrs(dict(call.arguments)),
                            "result": _truncate_result(cached),
                        },
                    ),
                )
            return cached
        read_key = _read_range_key(call.arguments) if name == "read" else None
        message_key = _message_dedup_key(call.arguments) if name == "message" else None
        if message_key is not None and message_key in ctx.seen_messages:
            notice = _already_sent_notice(message_key)
            ctx.seen_messages[message_key] += 1
            logger.debug(
                "tool_call.deduped name={} tier={} arg_keys={} arg_values={} result={} "
                "span_id={} turn_id={}",
                name,
                ctx.executor_tier,
                _arg_keys,
                _arg_values,
                _tool_debug_result(notice, max_chars=_result_log_max),
                span_id,
                ctx.turn_id,
            )
            if sink is not None:
                deduped_ns = time_ns()
                await sink.emit(
                    TraceEvent(
                        kind=f"tool.{name}",
                        span_id=span_id,
                        parent_span_id=parent_span_id,
                        session_id=ctx.session_id,
                        turn_id=ctx.turn_id,
                        tier=ctx.executor_tier,
                        ts_start_ns=start_ns,
                        ts_end_ns=deduped_ns,
                        status="deduped",
                        attrs={
                            "args": _json_safe_attrs(dict(call.arguments)),
                            "result": _truncate_result(notice),
                        },
                    ),
                )
            return notice
        if read_key is not None and read_key in ctx.seen_reads:
            notice = _already_read_notice(read_key)
            logger.debug(
                "tool_call.deduped name={} tier={} arg_keys={} arg_values={} result={} "
                "span_id={} turn_id={}",
                name,
                ctx.executor_tier,
                _arg_keys,
                _arg_values,
                _tool_debug_result(notice, max_chars=_result_log_max),
                span_id,
                ctx.turn_id,
            )
            if sink is not None:
                deduped_ns = time_ns()
                await sink.emit(
                    TraceEvent(
                        kind=f"tool.{name}",
                        span_id=span_id,
                        parent_span_id=parent_span_id,
                        session_id=ctx.session_id,
                        turn_id=ctx.turn_id,
                        tier=ctx.executor_tier,
                        ts_start_ns=start_ns,
                        ts_end_ns=deduped_ns,
                        status="deduped",
                        attrs={
                            "args": _json_safe_attrs(dict(call.arguments)),
                            "result": _truncate_result(notice),
                        },
                    ),
                )
            return notice
        logger.debug(
            "tool_call.start name={} tier={} arg_keys={} arg_values={} span_id={}",
            name,
            ctx.executor_tier,
            _arg_keys,
            _arg_values,
            span_id,
        )
        if sink is not None:
            await sink.emit(
                TraceEvent(
                    kind=f"tool.{name}",
                    span_id=span_id,
                    parent_span_id=parent_span_id,
                    session_id=ctx.session_id,
                    turn_id=ctx.turn_id,
                    tier=ctx.executor_tier,
                    ts_start_ns=start_ns,
                    ts_end_ns=None,
                    status="started",
                    attrs={"args": _json_safe_attrs(dict(call.arguments))},
                ),
            )
        try:
            raw = await super().dispatch(ctx, call, timeout_seconds=timeout_seconds)
        except Exception as exc:
            err_ns = time_ns()
            logger.debug(
                "tool_call.finish name={} status=error dur_ms={:.1f} error={} span_id={} turn_id={}",
                name,
                (err_ns - start_ns) / 1_000_000,
                type(exc).__name__,
                span_id,
                ctx.turn_id,
            )
            if sink is not None:
                await sink.emit(
                    TraceEvent(
                        kind=f"tool.{name}",
                        span_id=span_id,
                        parent_span_id=parent_span_id,
                        session_id=ctx.session_id,
                        turn_id=ctx.turn_id,
                        tier=ctx.executor_tier,
                        ts_start_ns=start_ns,
                        ts_end_ns=err_ns,
                        status="error",
                        attrs={"error": type(exc).__name__},
                    ),
                )
            raise
        end_ns = time_ns()
        status = "ok"
        error: str | None = None
        try:
            blob = json.loads(raw)
            if isinstance(blob, dict) and not blob.get("ok"):
                status = "error"
                err_val = blob.get("error")
                error = str(err_val) if err_val is not None else None
        except json.JSONDecodeError:
            status = "error"
            error = "invalid_json"
        if status == "error":
            raw = _maybe_retype_upstream_proxy_error(raw)
            raw = _inject_did_you_mean(ctx, call, raw)
            if _is_cacheable_failure(raw, tool_name=name):
                ctx.negative_cache[cache_key] = raw
        elif name == "load_tool" and status == "ok" and isinstance(call.arguments, dict):
            load_name = str(call.arguments.get("name", "")).strip()
            if load_name:
                ctx.loaded_tools[load_name] = raw
        elif name == "read" and status == "ok" and read_key is not None:
            # Remember this path+range so an identical repeat read this turn
            # short-circuits to the compact notice (`specs/11-tools-registry.md` §10.13).
            ctx.seen_reads.setdefault(read_key, raw)
        elif name == "message" and status == "ok" and message_key is not None:
            # Remember this destination+body so an identical repeat send this turn
            # short-circuits without re-delivering, stopping outbound spam loops
            # (`specs/11-tools-registry.md` §10.13).
            ctx.seen_messages.setdefault(message_key, 0)
        logger.debug(
            "tool_call.finish name={} status={} dur_ms={:.1f} result={}{} span_id={} turn_id={}",
            name,
            status,
            (end_ns - start_ns) / 1_000_000,
            _tool_debug_result(raw, max_chars=_result_log_max),
            f" error={error}" if error else "",
            span_id,
            ctx.turn_id,
        )
        if sink is not None:
            finish_attrs: dict[str, object] = {
                "result": _truncate_result(raw),
                "status": status,
            }
            if error:
                finish_attrs["error"] = error
            await sink.emit(
                TraceEvent(
                    kind=f"tool.{name}",
                    span_id=span_id,
                    parent_span_id=parent_span_id,
                    session_id=ctx.session_id,
                    turn_id=ctx.turn_id,
                    tier=ctx.executor_tier,
                    ts_start_ns=start_ns,
                    ts_end_ns=end_ns,
                    status=status,
                    attrs=finish_attrs,
                ),
            )
        return raw


def _skill_descriptions_from_index_lines(lines: dict[str, str]) -> dict[str, str]:
    """Parse ``name — description`` index rows into a name → description map.

    Args:
        lines (dict[str, str]): ``SkillsIndex.lines`` snapshot.

    Returns:
        dict[str, str]: Skill id → description text for Triager / ``load_skill`` stubs.

    Examples:
        >>> _skill_descriptions_from_index_lines({"canvas": "canvas — rich layouts"})
        {'canvas': 'rich layouts'}
    """
    out: dict[str, str] = {}
    for name, line in lines.items():
        if " — " in line:
            out[name] = line.split(" — ", 1)[1]
        else:
            out[name] = line
    return out


def combine_registry_version(base: int, skills_manager: SkillsManager) -> int:
    """Combine tools-base ``registry_version`` with live skills generation state.

    Incorporates the ``SkillsManager`` sequence counter (bumps when the content
    fingerprint changes) and the current digest so ``ToolSet.registry_version``,
    Triager caches, and ``LoadedBodyCache`` invalidate when the skills tree changes
    (`specs/11-tools-registry.md` §5, `specs/12-skills-system.md` §3.4).

    Args:
        base (int): Tools/plugins/MCP baseline generation (e.g. ``INITIAL_REGISTRY_VERSION``).
        skills_manager (SkillsManager): Session-scoped skills scan singleton.

    Returns:
        int: Monotonic combined generation counter.

    Examples:
        >>> from pathlib import Path
        >>> from sevn.skills.manager import SkillsManager
        >>> SkillsManager.reset_singletons_for_tests()
        >>> root = Path("/tmp/sevn-combine-rv-doctest")
        >>> root.mkdir(parents=True, exist_ok=True)
        >>> (root / "skills").mkdir(exist_ok=True)
        >>> mgr = SkillsManager.shared(root, (root / "skills",))
        >>> combine_registry_version(1, mgr) >= 1
        True
        >>> SkillsManager.reset_singletons_for_tests()
    """
    seq = int(skills_manager.registry_version)
    digest = getattr(skills_manager, "_last_digest", "") or ""
    digest_part = int(digest[:8], 16) if len(digest) >= 8 else 0
    return base * 10_000_000 + seq * 10_000 + (digest_part % 10_000)


def merge_skill_manifests(extra: dict[str, str] | None) -> dict[str, str]:
    """Combine packaged defaults with workspace-provided overlays.

    Args:
        extra (dict[str, str] | None): Workspace summary dictionary.

    Returns:
        dict[str, str]: Merged map for ``attach_meta_loaders``.

    Examples:
        >>> merge_skill_manifests({"custom": "extra"})["custom"]
        'extra'
    """

    merged = dict(DEFAULT_SKILL_MANIFESTS)
    if extra:
        merged.update(extra)
    return merged


def snapshot_tool_set(
    executor: ToolExecutor,
    *,
    registry_version: int,
    skill_descriptions: dict[str, str],
    skill_inventory: dict[str, dict[str, object]] | None,
    mcp_definitions: tuple[ToolDefinition, ...],
    mcp_names: frozenset[str],
) -> ToolSet:
    """Produce a ``ToolSet`` using executor rows + declared MCP overlays.

    Args:
        executor (ToolExecutor): Registry after plugins/MCP stubs + meta loaders.
        registry_version (int): Monotonic generation counter (`specs/11-tools-registry.md` §5).
        skill_descriptions (dict[str, str]): Skill summaries (Triager/skills prompts).
        skill_inventory (dict[str, dict[str, object]] | None): Per-skill script/runnable
            inventory for triager prompt surfacing.
        mcp_definitions (tuple[ToolDefinition, ...]): Session-declared MCP surface.
        mcp_names (frozenset[str]): Names categorized as MCP for native tuple filtering.

    Returns:
        ToolSet: Frozen tuples for adapters.

    Examples:
        >>> exe, ts = build_session_registry()
        >>> snapshot_tool_set(
        ...     exe,
        ...     registry_version=1,
        ...     skill_descriptions={},
        ...     skill_inventory={},
        ...     mcp_definitions=(),
        ...     mcp_names=frozenset(),
        ... ).registry_version
        1
    """

    native = tuple(
        sorted(
            (d for d in executor.definitions() if d.name not in mcp_names),
            key=lambda item: item.name,
        ),
    )
    mcp_sorted = tuple(sorted(mcp_definitions, key=lambda item: item.name))
    return ToolSet(
        registry_version=registry_version,
        native=native,
        mcp=mcp_sorted,
        skill_descriptions=dict(skill_descriptions),
        skill_inventory=dict(skill_inventory or {}),
    )


async def _disabled_gated_tool_executor(ctx: ToolContext, **_kwargs: Any) -> str:
    """Fail closed for explicitly disabled gated tools (v1 by design).

    Used when ``integration_call`` or ``sandbox_exec`` register as
    ``enabled=False`` scaffolding rows because ``RuntimeToolBindings`` lacks
    live runtime hooks.

    Args:
        ctx (ToolContext): Runtime envelope (unused; retained for ABI parity).
        _kwargs (Any): Tool arguments (ignored).

    Returns:
        str: §3.1 JSON failure envelope coded ``INTERNAL_ERROR``.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(_disabled_gated_tool_executor)
        True
    """
    _ = ctx
    return enveloped_failure(
        "Tool disabled until runtime bindings are configured",
        code=ToolResultCode.INTERNAL_ERROR,
    )


def register_feature_stubs(
    executor: ToolExecutor,
    *,
    runtime_bindings: RuntimeToolBindings | None = None,
) -> None:
    """Attach ``integration_call`` / ``sandbox_exec`` scaffolding or live runtime rows.

    ``integration_call`` flows only through the egress-paired proxy with session tokens
    (`specs/06-secrets.md`), never with raw provider keys inside the tool host
    (`specs/11-tools-registry.md` §8). GitHub REST access uses the same surface — legacy
    ``gh_repo_*`` names map via
    :func:`sevn.tools.integration_gh_repo.legacy_gh_repo_integration_kwargs`; standalone
    ``gh_repo_*`` tools are not registered.

    When ``runtime_bindings`` supplies live hooks (Wave Q sandbox runtime + egress-paired
    proxy), ``integration_call`` and ``sandbox_exec`` register as **enabled** Tools that
    delegate to those hooks; otherwise they register as **disabled** scaffolding rows
    (`specs/11-tools-registry.md` §10.1).

    Args:
        executor (ToolExecutor): Registry being constructed.
        runtime_bindings (RuntimeToolBindings | None): Optional Wave T runtime hooks.

    Returns:
        None

    Examples:
        >>> executor = ToolExecutor(default_timeout_seconds=None)
        >>> register_feature_stubs(executor)
        >>> hasattr(executor, "get")
        True
    """

    bindings = runtime_bindings or RuntimeToolBindings()

    if bindings.integration is not None:
        executor.register(make_integration_call_tool(bindings))
    else:
        disabled_integration = ToolDefinition(
            name="integration_call",
            category="integrations",
            description="Third-party egress proxy dispatcher (explicitly gated).",
            parameters={
                "type": "object",
                "properties": {
                    "service": {"type": "string"},
                    "method": {"type": "string"},
                    "args": {"type": "object"},
                },
                "required": ["service", "method", "args"],
            },
            enabled=False,
            abortable=False,
        )
        executor.register(FunctionTool(disabled_integration, _disabled_gated_tool_executor))

    if bindings.sandbox is not None:
        executor.register(make_sandbox_exec_tool(bindings))
    else:
        disabled_sandbox = ToolDefinition(
            name="sandbox_exec",
            category="sandbox",
            description="Single v1 sandbox entrypoint (explicitly gated).",
            parameters={
                "type": "object",
                "properties": {
                    "language": {"type": "string"},
                    "code": {"type": "string"},
                },
                "required": ["language", "code"],
            },
            enabled=False,
            sandbox_mode="subprocess",
        )
        executor.register(FunctionTool(disabled_sandbox, _disabled_gated_tool_executor))


class McpUnavailableTool(FunctionTool):
    """MCP façade returning deterministic ``MCP_UNAVAILABLE`` failures."""

    def __init__(self, definition_obj: ToolDefinition) -> None:
        """Wire descriptor-backed placeholder execution.

                Args:
        definition_obj (ToolDefinition): Workspace-declared MCP tool row.

                Returns:
                    None

                Examples:
                    >>> d = ToolDefinition(
                    ...     name="srv.tool",
                    ...     category="mcp",
                    ...     description="demo",
                    ...     parameters={"type": "object", "properties": {}},
                    ... )
                    >>> isinstance(McpUnavailableTool(d), McpUnavailableTool)
                    True
        """

        async def _invoke(ctx: ToolContext, **_kwargs: Any) -> str:
            _ = ctx
            return enveloped_failure(
                "MCP server transport unavailable",
                code=ToolResultCode.MCP_UNAVAILABLE,
                data={"tool": definition_obj.name},
            )

        super().__init__(definition_obj, _invoke)


def _flatten_factory_output(candidate: object) -> list[Tool]:
    """Normalize plugin factories to flat ``Tool`` lists.

    Args:
        candidate (object): Either a single ``Tool`` or a sequence (non-string)
            of ``Tool`` instances produced by an entry-point factory.

    Returns:
        list[Tool]: Always a list, even when ``candidate`` is a singleton.

    Raises:
        TypeError: When ``candidate`` is neither a ``Tool`` nor a sequence of
            ``Tool`` instances.

    Examples:
        >>> import pytest
        >>> with pytest.raises(TypeError):
        ...     _flatten_factory_output(object())
        >>> _flatten_factory_output([])
        []
    """
    if isinstance(candidate, Tool):
        return [candidate]
    if isinstance(candidate, Sequence) and not isinstance(candidate, str | bytes | bytearray):
        out: list[Tool] = []
        for element in candidate:
            if isinstance(element, Tool):
                out.append(element)
                continue
            msg = "plugin entry point emitted non-Tool value"
            raise TypeError(msg)
        return out
    msg = "plugin entry point must return Tool or sequence of Tools"
    raise TypeError(msg)


def plugin_entrypoint_allowed(ep_name: str, toggles: dict[str, bool]) -> bool:
    """Honor ``tools.<plugin>.enabled`` defaults (implicit True when unspecified).

    Args:
    ep_name (str): Entry-point name (typically ``namespaced.tool``).
    toggles (dict[str, bool]): Workspace gate dictionary.

            Returns:
                bool: Whether plugin registration should proceed.

            Examples:
                >>> plugin_entrypoint_allowed("magic.demo", {})
                True
                >>> plugin_entrypoint_allowed("magic.demo", {"magic": False})
                False
    """

    prefix = ep_name.split(".", maxsplit=1)[0]
    if prefix not in toggles:
        return True
    return bool(toggles[prefix])


def load_plugin_tools(plugins_enabled: dict[str, bool] | None = None) -> list[Tool]:
    """Enumerate ``Tool`` factories registered under setuptools group ``sevn.tools``.

            Args:
    plugins_enabled (dict[str, bool] | None): Optional coarse enablement overrides.

            Returns:
                list[Tool]: Imported tools respecting toggles.

            Examples:
                >>> isinstance(load_plugin_tools(), list)
                True
    """

    toggles = dict(plugins_enabled or [])
    artifacts: list[Tool] = []
    try:
        eps = entry_points(group="sevn.tools")
    except TypeError:
        eps = entry_points().select(group="sevn.tools")
    iterable: Iterable[EntryPoint]
    iterable = eps
    iterable = iterable if iterable is not None else ()
    for ep in iterable:
        if ep.name in _PACKAGED_TOOLS_ENTRY_SKIP:
            continue
        if not plugin_entrypoint_allowed(ep.name, toggles):
            continue
        factory_raw = ep.load()
        candidate = factory_raw() if callable(factory_raw) else factory_raw
        artifacts.extend(_flatten_factory_output(candidate))
    return artifacts


def build_session_registry(
    *,
    registry_version: int | None = None,
    skill_overrides: dict[str, str] | None = None,
    extra_mcp: tuple[ToolDefinition, ...] = (),
    plugins_enabled: dict[str, bool] | None = None,
    default_timeout_seconds: float | None = 30.0,
    workspace_config: WorkspaceConfig | None = None,
    runtime_bindings: RuntimeToolBindings | None = None,
    skills_manager: SkillsManager | None = None,
    workspace_root: Path | None = None,
    layout: WorkspaceLayout | None = None,
    trace_sink: TraceSink | None = None,
    include_bootstrap_tools: bool = False,
) -> tuple[ToolExecutor, ToolSet]:
    """Factory bundling scaffolding tools, MCP placeholders, plugins, then meta loaders.

    Args:
        registry_version (int | None): Defaults to ``INITIAL_REGISTRY_VERSION``.
        skill_overrides (dict[str, str] | None): Overlay skill summaries.
        extra_mcp (tuple[ToolDefinition, ...]): Declared MCP tool descriptors for session snapshot.
        plugins_enabled (dict[str, bool] | None): Entry-point coarse gates.
        default_timeout_seconds (float | None): ``ToolExecutor.dispatch`` deadline default.
        workspace_config (WorkspaceConfig | None): When ``second_brain.enabled``, registers
            Second Brain tools (`specs/27-second-brain.md` §2.1).
        runtime_bindings (RuntimeToolBindings | None): Wave T live hooks for
            ``integration_call`` / ``sandbox_exec`` / MCP stdio dispatch. When ``mcp``
            is set and ``mcp_servers`` contains the descriptor's ``server_id``,
            :class:`sevn.tools.runtime_dispatch.McpStdioTool` replaces
            :class:`McpUnavailableTool` for that row.
        skills_manager (SkillsManager | None): When set, registers live
            ``run_skill_script`` / ``run_skill_runnable`` via
            :func:`sevn.tools.skills_register.register_skill_tools`; otherwise
            enabled unconfigured rows remain for validation and ``load_tool`` metadata.
        workspace_root (Path | None): When set, constructs ``SkillsManager.shared`` for
            the workspace (unless ``skills_manager`` is already provided).
        layout (WorkspaceLayout | None): Optional layout forwarded to ``SkillsManager.shared``.
        trace_sink (TraceSink | None): Optional trace sink for skills scan spans.
        include_bootstrap_tools (bool): When True, register ``write_workspace_md`` for tier-B
            bootstrap turns.

    Returns:
        tuple[ToolExecutor, ToolSet]: Live registry plus frozen ``ToolSet``.

    Examples:
        >>> exe, ts = build_session_registry()
        >>> "load_skill" in {d.name for d in exe.definitions()}
        True
    """

    from sevn.code_understanding.tools_register import register_code_understanding_tools
    from sevn.second_brain import register_second_brain_tools
    from sevn.skills.manager import SkillsManager as SkillsManagerCls
    from sevn.tools.skills_register import register_skill_tools, register_skill_tools_unconfigured
    from sevn.ui.openui.tools_register import register_openui_tools

    mgr = skills_manager
    if mgr is None and workspace_root is not None:
        mgr = SkillsManagerCls.shared(
            workspace_root,
            layout=layout,
            config=workspace_config,
            trace_sink=trace_sink,
        )

    bindings = runtime_bindings or RuntimeToolBindings()
    exe = TracingToolExecutor(default_timeout_seconds=default_timeout_seconds)
    register_feature_stubs(exe, runtime_bindings=bindings)
    from sevn.tools.file_ops import register_file_ops_tools

    register_file_ops_tools(exe)
    from sevn.tools.memory_tools import register_memory_tools

    register_memory_tools(exe, workspace_config)
    from sevn.tools.web import register_web_tools

    register_web_tools(exe)
    from sevn.tools.outbound import register_outbound_tools

    register_outbound_tools(exe)
    from sevn.tools.llm_guard_tool import register_llm_guard_tool
    from sevn.tools.log_query import register_log_query_tool
    from sevn.tools.semantic_search import register_semantic_search_tool

    register_log_query_tool(exe)
    register_llm_guard_tool(exe, workspace_config)
    register_semantic_search_tool(exe, workspace_config)
    from sevn.tools.process import register_process_tools
    from sevn.tools.terminal import register_terminal_tools

    register_process_tools(exe)
    register_terminal_tools(exe)
    if mgr is not None:
        register_skill_tools(exe, mgr)
    else:
        register_skill_tools_unconfigured(exe)
    register_second_brain_tools(exe, workspace_config)
    register_code_understanding_tools(exe, workspace_config)
    register_openui_tools(exe)
    from sevn.tools.evolution_issues import register_evolution_issue_tools

    register_evolution_issue_tools(exe, workspace_config)
    from sevn.tools.browser import register_browser_tool

    register_browser_tool(exe, workspace_config)
    from sevn.tools.subagent_spawn import register_subagent_spawn_tools

    register_subagent_spawn_tools(exe, workspace_config)
    if include_bootstrap_tools:
        from sevn.tools.workspace_files import register_write_workspace_md

        register_write_workspace_md(exe)
    if mgr is not None:
        # D14: advertise only loadable (non-quarantined) skills from the live scan —
        # never merge DEFAULT_SKILL_MANIFESTS stubs that ``load_skill`` cannot resolve.
        merged_skills = mgr.advertised_skill_descriptions()
        if skill_overrides:
            for key, value in skill_overrides.items():
                if key in merged_skills:
                    merged_skills[key] = value
    else:
        merged_skills = merge_skill_manifests(skill_overrides)
    toggles = dict(plugins_enabled or {})
    if workspace_config is not None and workspace_config.tools is not None:
        for plugin_id, entry in workspace_config.tools.items():
            if not isinstance(plugin_id, str) or not isinstance(entry, dict):
                continue
            if "enabled" in entry:
                toggles[plugin_id] = bool(entry["enabled"])

    mcp_client = bindings.mcp
    known_servers = set(bindings.mcp_servers.keys()) if bindings.mcp_servers else set()
    for defn in extra_mcp:
        if not defn.enabled:
            continue
        server_id, sep, _tail = defn.name.partition(".")
        server_id = server_id if sep else defn.name
        if mcp_client is not None and (not known_servers or server_id in known_servers):
            exe.register(McpStdioTool(defn, client=mcp_client, server_id=server_id))
        else:
            exe.register(McpUnavailableTool(defn))

    for plugin_tool in load_plugin_tools(toggles):
        exe.register(plugin_tool)

    mcp_names = frozenset({definition.name for definition in extra_mcp})
    executor_native_only = {
        definition.name: definition
        for definition in exe.definitions()
        if definition.name not in mcp_names
    }
    executor_mcp_map = {definition.name: definition for definition in extra_mcp}

    attach_meta_loaders(
        exe,
        native_definitions=dict(executor_native_only),
        mcp_definitions=dict(executor_mcp_map),
        skill_descriptions=merged_skills,
        mcp_tool_names=mcp_names,
        skills_manager=mgr,
    )

    base_rv = INITIAL_REGISTRY_VERSION if registry_version is None else registry_version
    rv = combine_registry_version(base_rv, mgr) if mgr is not None else base_rv
    ts = snapshot_tool_set(
        exe,
        registry_version=rv,
        skill_descriptions=merged_skills,
        skill_inventory=mgr.inventory_for_triager() if mgr is not None else {},
        mcp_definitions=extra_mcp,
        mcp_names=mcp_names,
    )
    return exe, ts


__all__ = [
    "DEFAULT_SKILL_MANIFESTS",
    "DEFAULT_TOOL_MANIFESTS",
    "McpUnavailableTool",
    "ToolSet",
    "build_session_registry",
    "combine_registry_version",
    "load_plugin_tools",
    "merge_skill_manifests",
    "plugin_entrypoint_allowed",
    "register_feature_stubs",
    "snapshot_tool_set",
]
