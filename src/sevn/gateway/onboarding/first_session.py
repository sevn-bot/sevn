"""First-session BOOTSTRAP intro state (`specs/17-gateway.md` §2.6).

Module: sevn.gateway.onboarding.first_session
Depends: json, re, sqlite3, sevn.config.workspace_config, sevn.onboarding.seed, sevn.workspace.layout

Exports:
    first_session_intro_enabled — read ``gateway.first_session_intro.enabled``.
    first_session_intro_max_output_tokens — intro tier-B ``max_tokens`` cap.
    intro_state_for_session — ``done`` | ``skipped`` | ``in_flight`` | ``pending`` from metadata.
    intro_state_for_scope — scope-level intro lifecycle state for ``(channel, user_id)``.
    count_user_messages — count user ``message`` rows across a chat scope.
    count_user_messages_in_session — count user ``message`` rows for one ``session_id``.
    bootstrap_completion_state — ``complete`` | ``incomplete`` | ``missing`` from ``USER.md``.
    bootstrap_capture_active — True while bootstrap files need capture (not skipped).
    missing_user_md_bootstrap_fields — USER.md field labels still holding placeholders.
    user_md_bootstrap_profile_incomplete — True when USER.md profile capture is open.
    bootstrap_capture_instructions — tier-B follow-up when answers arrive after intro.
    maybe_mark_intro_done_if_bootstrap_complete — persist ``intro_state=done`` when USER.md ready.
    is_first_session_turn — True when intro should run for this turn.
    mark_intro_state — persist ``intro_state`` on all sessions in scope.
    clear_intro_state_cache — drop cached ``intro_state`` on all sessions.
    maybe_reseed_bootstrap_at_boot — re-seed templates when bootstrap incomplete.
    tier_b_intro_instructions — extra executor instructions for BOOTSTRAP intro.
    load_bootstrap_markdown — read ``BOOTSTRAP.md`` from content root.
    load_bootstrap_markdown_cached — mtime-keyed cache wrapper for ``BOOTSTRAP.md``.
    clear_bootstrap_markdown_cache — test helper to reset the bootstrap cache.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Literal

from sevn.config.llm_params import resolve_effective_max_output_tokens
from sevn.config.workspace_config import GatewayFirstSessionIntroConfig, WorkspaceConfig

if TYPE_CHECKING:
    from sevn.workspace.layout import WorkspaceLayout

_INTRO_SUPPRESS = frozenset({"done", "skipped", "in_flight"})
_INTRO_DONE = frozenset({"done", "skipped"})
_BOOTSTRAP_USER_INCOMPLETE_MARKER = "<!-- sevn-bootstrap:user-incomplete -->"
_NAME_PLACEHOLDER_VALUE = re.compile(r"^_\(.*\)_$")
_USER_MD_BOOTSTRAP_FIELDS: Final[tuple[str, ...]] = (
    "Name",
    "Role",
    "Timezone",
    "Style",
    "Language",
)
BootstrapCompletionState = Literal["complete", "incomplete", "missing"]


def _gateway_intro_cfg(workspace: WorkspaceConfig) -> GatewayFirstSessionIntroConfig:
    """Resolve ``gateway.first_session_intro`` with defaults.

    Args:
        workspace (WorkspaceConfig): Parsed workspace.

    Returns:
        GatewayFirstSessionIntroConfig: Intro subtree or default instance.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> _gateway_intro_cfg(WorkspaceConfig.minimal()).enabled
        True
    """
    gw = workspace.gateway
    if gw is not None and gw.first_session_intro is not None:
        return gw.first_session_intro
    return GatewayFirstSessionIntroConfig()


def first_session_intro_enabled(workspace: WorkspaceConfig) -> bool:
    """Return whether BOOTSTRAP first-session intro is enabled.

    Args:
        workspace (WorkspaceConfig): Parsed workspace.

    Returns:
        bool: False when ``gateway.first_session_intro.enabled`` is false.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> first_session_intro_enabled(WorkspaceConfig.minimal())
        True
    """
    return _gateway_intro_cfg(workspace).enabled


def first_session_intro_max_output_tokens(
    workspace: WorkspaceConfig,
    *,
    model_id: str,
    content_root: Path | None = None,
) -> int:
    """Return effective ``max_tokens`` for the first-session tier-B intro turn.

    Uses ``gateway.first_session_intro.max_output_tokens`` (default 4096) and applies
    ``min(intro cap, resolve_effective_max_output_tokens(tier_b, model_id))``.

    Args:
        workspace (WorkspaceConfig): Parsed workspace.
        model_id (str): Resolved tier-B catalog model id for the intro turn.
        content_root (Path | None): Workspace content root for ``LLM_params_config.json``.

    Returns:
        int: Provider max output tokens for the intro turn only.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> first_session_intro_max_output_tokens(
        ...     WorkspaceConfig.minimal(), model_id="openai:gpt-4o"
        ... )
        4096
    """
    cfg = _gateway_intro_cfg(workspace)
    intro_cap = int(cfg.max_output_tokens)
    tier_resolved = resolve_effective_max_output_tokens(
        "tier_b",
        model_id,
        workspace,
        content_root=content_root,
    )
    return min(intro_cap, tier_resolved)


def _load_session_metadata(conn: sqlite3.Connection, session_id: str) -> dict[str, Any]:
    """Parse ``gateway_sessions.metadata_json`` for ``session_id``.

    Args:
        conn (sqlite3.Connection): Gateway SQLite handle.
        session_id (str): Session id.

    Returns:
        dict[str, Any]: Decoded metadata or empty dict.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> _load_session_metadata(c, "missing")
        {}
    """
    row = conn.execute(
        "SELECT metadata_json FROM gateway_sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    if row is None or not row[0]:
        return {}
    try:
        parsed = json.loads(str(row[0]))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _session_scope(conn: sqlite3.Connection, session_id: str) -> tuple[str, str] | None:
    """Return ``(channel, user_id)`` for ``session_id`` when the row exists.

    Args:
        conn (sqlite3.Connection): Gateway SQLite handle.
        session_id (str): Session id.

    Returns:
        tuple[str, str] | None: Scope key parts or ``None`` when missing.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> _session_scope(c, "missing") is None
        True
    """
    row = conn.execute(
        "SELECT channel, user_id FROM gateway_sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    if row is None:
        return None
    return str(row[0]), str(row[1])


def intro_state_for_scope(conn: sqlite3.Connection, channel: str, user_id: str) -> str:
    """Return intro lifecycle state for ``(channel, user_id)`` across sessions.

    Args:
        conn (sqlite3.Connection): Gateway SQLite handle.
        channel (str): Session channel key.
        user_id (str): Session user id.

    Returns:
        str: ``pending``, ``done``, ``skipped``, or ``in_flight``.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> intro_state_for_scope(c, "telegram", "1")
        'pending'
    """
    rows = conn.execute(
        """
        SELECT metadata_json FROM gateway_sessions
        WHERE channel = ? AND user_id = ?
        """,
        (channel, user_id),
    ).fetchall()
    saw_in_flight = False
    for row in rows:
        if not row[0]:
            continue
        try:
            parsed = json.loads(str(row[0]))
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict):
            continue
        raw = parsed.get("intro_state")
        if raw in _INTRO_DONE:
            return str(raw)
        if raw == "in_flight":
            saw_in_flight = True
    return "in_flight" if saw_in_flight else "pending"


def intro_state_for_session(conn: sqlite3.Connection, session_id: str) -> str:
    """Return intro lifecycle state for the session's ``(channel, user_id)`` scope.

    Args:
        conn (sqlite3.Connection): Gateway SQLite handle.
        session_id (str): Session id.

    Returns:
        str: ``pending``, ``done``, ``skipped``, or ``in_flight``.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> intro_state_for_session(c, "missing")
        'pending'
    """
    scope = _session_scope(conn, session_id)
    if scope is None:
        return "pending"
    channel, user_id = scope
    return intro_state_for_scope(conn, channel, user_id)


def count_user_messages(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    channel: str | None = None,
    user_id: str | None = None,
) -> int:
    """Count visible user message rows for a ``(channel, user_id)`` scope.

    Args:
        conn (sqlite3.Connection): Gateway SQLite handle.
        session_id (str): Session id used to resolve scope when ``channel`` /
            ``user_id`` are omitted.
        channel (str | None): Optional channel override.
        user_id (str | None): Optional user id override.

    Returns:
        int: Number of user ``message`` rows across all sessions in scope.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> count_user_messages(c, "s")
        0
    """
    ch = channel
    uid = user_id
    if ch is None or uid is None:
        scope = _session_scope(conn, session_id)
        if scope is None:
            return 0
        ch, uid = scope
    row = conn.execute(
        """
        SELECT COUNT(*) FROM gateway_messages m
        JOIN gateway_sessions s ON s.session_id = m.session_id
        WHERE s.channel = ? AND s.user_id = ?
          AND m.role = 'user' AND m.kind = 'message'
        """,
        (ch, uid),
    ).fetchone()
    return int(row[0]) if row else 0


def count_user_messages_in_session(conn: sqlite3.Connection, session_id: str) -> int:
    """Count user ``message`` rows for a single gateway session.

    Used when ``USER.md`` bootstrap is unfinished so ``/new`` can re-open the
    BOOTSTRAP intro without counting archived sessions in the same scope.

    Args:
        conn (sqlite3.Connection): Gateway SQLite handle.
        session_id (str): Live session id (e.g. after ``rotate_session``).

    Returns:
        int: Number of user ``message`` rows for ``session_id``.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> count_user_messages_in_session(c, "missing")
        0
    """
    row = conn.execute(
        """
        SELECT COUNT(*) FROM gateway_messages
        WHERE session_id = ? AND role = 'user' AND kind = 'message'
        """,
        (session_id,),
    ).fetchone()
    return int(row[0]) if row else 0


def _user_md_name_value(text: str) -> str | None:
    """Return the ``Name:`` field value from ``USER.md`` body text.

    Args:
        text (str): Full ``USER.md`` contents.

    Returns:
        str | None: Trimmed name value, or ``None`` when no ``Name:`` line exists.

    Examples:
        >>> _user_md_name_value("- **Name:** _(you)_\\n")
        '_(you)_'
    """
    return _user_md_field_value(text, "Name")


def _user_md_field_value(text: str, field_label: str) -> str | None:
    """Return one ``- **Field:**`` value from ``USER.md`` body text.

    Args:
        text (str): Full ``USER.md`` contents.
        field_label (str): Label between ``**`` markers (e.g. ``Role``).

    Returns:
        str | None: Trimmed value, or ``None`` when the field line is absent.

    Examples:
        >>> _user_md_field_value("- **Role:** _(what you do)_", "Role")
        '_(what you do)_'
    """
    needle = f"**{field_label}:**"
    for line in text.splitlines():
        if needle not in line:
            continue
        _, _, tail = line.partition(needle)
        return tail.strip()
    return None


def _is_user_md_placeholder_value(value: str | None) -> bool:
    """True when a field value is still the italicised template placeholder.

    Args:
        value (str | None): Field value from ``USER.md``.

    Returns:
        bool: True when ``value`` matches ``_(...)_``.

    Examples:
        >>> _is_user_md_placeholder_value("_(your preferred name)_")
        True
        >>> _is_user_md_placeholder_value("Alex")
        False
    """
    if value is None:
        return True
    stripped = value.strip()
    if _NAME_PLACEHOLDER_VALUE.fullmatch(stripped):
        return True
    # Agent-chosen deferred placeholders (bootstrap capture must not overwrite).
    low = stripped.strip("_").lower()
    return "ask in next turn" in low


def _user_md_preferences_placeholder(text: str) -> bool:
    """True when the first bullet under ``## Preferences`` is still a placeholder.

    Args:
        text (str): Full ``USER.md`` contents.

    Returns:
        bool: True when preferences are unset.

    Examples:
        >>> body = "## Preferences\\n\\n- _(tools you prefer)_\\n"
        >>> _user_md_preferences_placeholder(body)
        True
    """
    pref_heading = next(
        (i for i, line in enumerate(text.splitlines()) if line.strip() == "## Preferences"),
        None,
    )
    if pref_heading is None:
        return True
    lines = text.splitlines()
    for line in lines[pref_heading + 1 :]:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("- "):
            value = stripped[2:].strip()
            return bool(_NAME_PLACEHOLDER_VALUE.fullmatch(value))
        break
    return True


def missing_user_md_bootstrap_fields(content_root: Path) -> list[str]:
    """Return ``USER.md`` bootstrap field labels that still hold placeholders.

    Args:
        content_root (Path): Resolved workspace content root.

    Returns:
        list[str]: Missing field labels (empty when ``USER.md`` absent or complete).

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> from sevn.onboarding.seed import load_template, render_template
        >>> with tempfile.TemporaryDirectory() as td:
        ...     root = Path(td)
        ...     _ = (root / "USER.md").write_text(
        ...         render_template(load_template("USER.md"), "Sevn"),
        ...         encoding="utf-8",
        ...     )
        ...     "Name" in missing_user_md_bootstrap_fields(root)
        True
    """
    path = content_root / "USER.md"
    if not path.is_file():
        return [*list(_USER_MD_BOOTSTRAP_FIELDS), "Preferences"]
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return [*list(_USER_MD_BOOTSTRAP_FIELDS), "Preferences"]
    missing = [
        label
        for label in _USER_MD_BOOTSTRAP_FIELDS
        if _is_user_md_placeholder_value(_user_md_field_value(text, label))
    ]
    if _user_md_preferences_placeholder(text):
        missing.append("Preferences")
    return missing


def user_md_bootstrap_profile_incomplete(content_root: Path) -> bool:
    """True when ``USER.md`` bootstrap profile fields still need capture.

    Args:
        content_root (Path): Resolved workspace content root.

    Returns:
        bool: True when the marker or any profile placeholder remains.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> with tempfile.TemporaryDirectory() as td:
        ...     root = Path(td)
        ...     _ = (root / "USER.md").write_text(
        ...         "- **Name:** Alex\\n- **Role:** _(what you do)_\\n",
        ...         encoding="utf-8",
        ...     )
        ...     user_md_bootstrap_profile_incomplete(root)
        True
    """
    path = content_root / "USER.md"
    if not path.is_file():
        return True
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return True
    if _BOOTSTRAP_USER_INCOMPLETE_MARKER in text:
        return True
    return bool(missing_user_md_bootstrap_fields(content_root))


def bootstrap_completion_state(
    content_root: Path,
    *,
    agent_name: str,
) -> BootstrapCompletionState:
    """Classify bootstrap completion from ``USER.md`` (authoritative over DB cache).

    Args:
        content_root (Path): Resolved workspace content root.
        agent_name (str): Bot display name (reserved for template parity checks).

    Returns:
        BootstrapCompletionState: ``missing`` when ``USER.md`` absent;
            ``incomplete`` when the structural marker or placeholder ``Name:`` remains;
            else ``complete``.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> with tempfile.TemporaryDirectory() as td:
        ...     root = Path(td)
        ...     bootstrap_completion_state(root, agent_name="Sevn")
        'missing'
    """
    _ = agent_name
    path = content_root / "USER.md"
    if not path.is_file():
        return "missing"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return "missing"
    if _BOOTSTRAP_USER_INCOMPLETE_MARKER in text:
        return "incomplete"
    name_val = _user_md_name_value(text)
    if name_val is not None and _NAME_PLACEHOLDER_VALUE.fullmatch(name_val):
        return "incomplete"
    return "complete"


def bootstrap_capture_active(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    workspace: WorkspaceConfig,
    content_root: Path | None = None,
    agent_name: str = "Sevn",
    channel: str | None = None,
    user_id: str | None = None,
) -> bool:
    """True when bootstrap markdown still needs capture for this scope.

    Unlike ``is_first_session_turn`` (first user message only), this stays true on
    follow-up turns until ``USER.md`` profile fields are filled or the operator skips intro.

    Args:
        conn (sqlite3.Connection): Gateway SQLite handle.
        session_id (str): Session id.
        workspace (WorkspaceConfig): Workspace config.
        content_root (Path | None): Workspace content root for ``USER.md`` signal.
        agent_name (str): Bot display name for bootstrap classification.
        channel (str | None): Optional channel override.
        user_id (str | None): Optional user id override.

    Returns:
        bool: True when ``write_workspace_md`` and capture fallback should run.

    Examples:
        >>> import sqlite3
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> ws = WorkspaceConfig.minimal()
        >>> bootstrap_capture_active(c, "s", workspace=ws)
        False
    """
    if not first_session_intro_enabled(workspace):
        return False
    if content_root is None:
        return False
    ch = channel
    uid = user_id
    if ch is None or uid is None:
        scope = _session_scope(conn, session_id)
        if scope is None:
            return False
        ch, uid = scope
    if intro_state_for_scope(conn, ch, uid) == "skipped":
        return False
    return user_md_bootstrap_profile_incomplete(content_root)


def maybe_mark_intro_done_if_bootstrap_complete(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    content_root: Path,
    agent_name: str = "Sevn",
) -> bool:
    """Mark intro ``done`` when ``USER.md`` shows bootstrap is complete.

    Args:
        conn (sqlite3.Connection): Gateway SQLite handle.
        session_id (str): Session id.
        content_root (Path): Workspace content root.
        agent_name (str): Bot display name for bootstrap classification.

    Returns:
        bool: True when ``intro_state`` was updated to ``done``.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(maybe_mark_intro_done_if_bootstrap_complete)
        True
    """
    if bootstrap_completion_state(content_root, agent_name=agent_name) != "complete":
        return False
    mark_intro_state(conn, session_id, "done")
    return True


def is_first_session_turn(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    workspace: WorkspaceConfig,
    channel: str | None = None,
    user_id: str | None = None,
    content_root: Path | None = None,
    agent_name: str = "Sevn",
) -> bool:
    """True when this turn should run the BOOTSTRAP introduction.

    When ``content_root`` is set, ``USER.md`` is authoritative: a complete profile
    suppresses intro even when DB ``intro_state`` is stale; missing or incomplete
    ``USER.md`` re-opens intro on the first user message in the **current session**
    (not across archived rows after ``/new``).

    Args:
        conn (sqlite3.Connection): Gateway SQLite handle.
        session_id (str): Session id.
        workspace (WorkspaceConfig): Workspace config.
        channel (str | None): Optional channel override for scope resolution.
        user_id (str | None): Optional user id override for scope resolution.
        content_root (Path | None): Workspace content root for ``USER.md`` signal.
        agent_name (str): Bot display name for bootstrap classification.

    Returns:
        bool: True for the first user message before intro completes in scope.

    Examples:
        >>> import sqlite3
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> ws = WorkspaceConfig.minimal()
        >>> is_first_session_turn(c, "s", workspace=ws)
        False
    """
    if not first_session_intro_enabled(workspace):
        return False
    ch = channel
    uid = user_id
    if ch is None or uid is None:
        scope = _session_scope(conn, session_id)
        if scope is None:
            return False
        ch, uid = scope
    msg_count = count_user_messages(conn, session_id, channel=ch, user_id=uid)
    if content_root is not None:
        bootstrap = bootstrap_completion_state(content_root, agent_name=agent_name)
        intro_open = intro_state_for_scope(conn, ch, uid) not in _INTRO_SUPPRESS
        if bootstrap == "complete":
            return False
        bootstrap_unfinished = bootstrap in ("missing", "incomplete")
        if bootstrap_unfinished:
            return count_user_messages_in_session(conn, session_id) <= 1
        if intro_open:
            return msg_count <= 1
        return False
    if intro_state_for_scope(conn, ch, uid) in _INTRO_SUPPRESS:
        return False
    return msg_count <= 1


def mark_intro_state(
    conn: sqlite3.Connection,
    session_id: str,
    state: str,
) -> None:
    """Persist ``intro_state`` on every ``gateway_sessions`` row in scope.

    Args:
        conn (sqlite3.Connection): Gateway SQLite handle.
        session_id (str): Session id whose ``(channel, user_id)`` defines scope.
        state (str): ``done``, ``skipped``, or ``in_flight``.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> mark_intro_state(c, "missing", "done")
    """
    if state not in _INTRO_SUPPRESS:
        return
    scope = _session_scope(conn, session_id)
    if scope is None:
        return
    channel, user_id = scope
    rows = conn.execute(
        """
        SELECT session_id, metadata_json FROM gateway_sessions
        WHERE channel = ? AND user_id = ?
        """,
        (channel, user_id),
    ).fetchall()
    for sid, meta_raw in rows:
        meta: dict[str, Any]
        if meta_raw:
            try:
                parsed = json.loads(str(meta_raw))
            except json.JSONDecodeError:
                parsed = {}
            meta = parsed if isinstance(parsed, dict) else {}
        else:
            meta = {}
        meta["intro_state"] = state
        conn.execute(
            """
            UPDATE gateway_sessions
            SET metadata_json = ?, updated_at = datetime('now')
            WHERE session_id = ?
            """,
            (json.dumps(meta, sort_keys=True), sid),
        )
    conn.commit()


def clear_intro_state_cache(conn: sqlite3.Connection) -> None:
    """Remove cached ``intro_state`` from every ``gateway_sessions`` row.

    Args:
        conn (sqlite3.Connection): Gateway SQLite handle.

    Examples:
        >>> import sqlite3
        >>> from sevn.storage.migrate import apply_migrations
        >>> c = sqlite3.connect(":memory:")
        >>> apply_migrations(c)
        >>> clear_intro_state_cache(c)
    """
    rows = conn.execute(
        "SELECT session_id, metadata_json FROM gateway_sessions",
    ).fetchall()
    for sid, meta_raw in rows:
        if not meta_raw:
            continue
        try:
            parsed = json.loads(str(meta_raw))
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict) or "intro_state" not in parsed:
            continue
        meta = dict(parsed)
        meta.pop("intro_state", None)
        conn.execute(
            """
            UPDATE gateway_sessions
            SET metadata_json = ?, updated_at = datetime('now')
            WHERE session_id = ?
            """,
            (json.dumps(meta, sort_keys=True), sid),
        )
    conn.commit()


def maybe_reseed_bootstrap_at_boot(
    conn: sqlite3.Connection,
    *,
    workspace: WorkspaceConfig,
    layout: WorkspaceLayout,
) -> list[Path]:
    """Re-seed missing narrative templates and reset intro cache when bootstrap is open.

    Args:
        conn (sqlite3.Connection): Gateway SQLite handle.
        workspace (WorkspaceConfig): Parsed workspace configuration.
        layout (WorkspaceLayout): Resolved workspace layout.

    Returns:
        list[Path]: Template paths written by ``seed_narrative_templates`` (may be empty).

    Examples:
        >>> import inspect
        >>> inspect.isfunction(maybe_reseed_bootstrap_at_boot)
        True
    """
    from sevn.onboarding.seed import (
        resolve_agent_display_name,
        seed_llm_params,
        seed_narrative_templates,
    )

    # Per-agent LLM sampling params (D2/W7.2): seed copy-if-absent on every boot,
    # independent of bootstrap completion, so already-onboarded workspaces pick it
    # up on (re)start. Never overwrites an existing operator-edited copy.
    seed_llm_params(layout)

    merged = workspace.model_dump(mode="json")
    agent_name = resolve_agent_display_name(merged)
    if bootstrap_completion_state(layout.content_root, agent_name=agent_name) == "complete":
        return []
    written = seed_narrative_templates(
        layout.sevn_json_path,
        merged,
        overwrite=False,
    )
    clear_intro_state_cache(conn)
    return written


_bootstrap_markdown_cache: dict[tuple[str, int], str | None] = {}


def clear_bootstrap_markdown_cache() -> None:
    """Clear the module-level ``BOOTSTRAP.md`` mtime cache (tests only).

    Returns:
        None

    Examples:
        >>> clear_bootstrap_markdown_cache() is None
        True
    """
    _bootstrap_markdown_cache.clear()


def load_bootstrap_markdown_cached(content_root: Path) -> str | None:
    """Load ``BOOTSTRAP.md`` with an mtime-keyed in-process cache.

    Reuses the cached body when ``content_root/BOOTSTRAP.md`` exists and its
    modification time is unchanged since the last read.

    Args:
        content_root (Path): Resolved workspace content root.

    Returns:
        str | None: File body or None when missing/empty.

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> clear_bootstrap_markdown_cache()
        >>> with tempfile.TemporaryDirectory() as td:
        ...     root = Path(td)
        ...     _ = (root / "BOOTSTRAP.md").write_text("intro", encoding="utf-8")
        ...     load_bootstrap_markdown_cached(root)
        'intro'
    """
    path = content_root / "BOOTSTRAP.md"
    if not path.is_file():
        return None
    try:
        mtime_ns = path.stat().st_mtime_ns
    except OSError:
        return load_bootstrap_markdown(content_root)
    key = (str(content_root.resolve()), mtime_ns)
    if key in _bootstrap_markdown_cache:
        return _bootstrap_markdown_cache[key]
    body = load_bootstrap_markdown(content_root)
    _bootstrap_markdown_cache[key] = body
    return body


def load_bootstrap_markdown(content_root: Path) -> str | None:
    """Load ``BOOTSTRAP.md`` when present under the workspace content root.

    Args:
        content_root (Path): Resolved workspace content root.

    Returns:
        str | None: File body or None when missing/empty.

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> with tempfile.TemporaryDirectory() as td:
        ...     root = Path(td)
        ...     _ = (root / "BOOTSTRAP.md").write_text("intro", encoding="utf-8")
        ...     load_bootstrap_markdown(root)
        'intro'
    """
    path = content_root / "BOOTSTRAP.md"
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text or None


def tier_b_intro_instructions(
    *,
    workspace: WorkspaceConfig,
    bootstrap_body: str | None,
    max_questions: int | None = None,
) -> str:
    """Extra tier-B instructions for the first-session introduction turn.

    Args:
        workspace (WorkspaceConfig): Workspace config.
        bootstrap_body (str | None): ``BOOTSTRAP.md`` contents.
        max_questions (int | None): Cap on optional questions (defaults from config).

    Returns:
        str: Instruction block appended to tier-B static instructions.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> "BOOTSTRAP" in tier_b_intro_instructions(
        ...     workspace=WorkspaceConfig.minimal(),
        ...     bootstrap_body="You are Sevn.",
        ... )
        True
    """
    cfg = _gateway_intro_cfg(workspace)
    n = max_questions if max_questions is not None else cfg.max_questions
    user_md_questions = (
        "1. Name — what should I call you?",
        "2. Role — what do you do day to day?",
        "3. Timezone — e.g. America/New_York",
        "4. Style — brief, detailed, bullet lists, etc.",
        "5. Language — primary language for replies",
        "6. Preferences — tools you prefer, topics to avoid, standing priorities",
    )
    lines = [
        "FIRST_SESSION_INTRO: This is the operator's first message in this chat scope.",
        "Deliver a warm self-introduction using BOOTSTRAP.md, SOUL.md, USER.md, and IDENTITY.md",
        "from the workspace personality context. Summarize who you are, what you can help with,",
        "and which tools/skills exist at a high level (from Triager registry descriptions).",
        "BOOTSTRAP WRITES (mandatory): Use the ``write`` tool in this turn to persist",
        'facts from BOOTSTRAP.md "Things to write down" (at minimum USER.md Name, SOUL.md tone,',
        "IDENTITY.md vibe) before claiming you updated memory. Do not say you saved files unless",
        "``write`` returned success in this same turn.",
        f"End by asking up to {n} USER.md profile questions (cover as many as fit naturally):",
        *user_md_questions,
        "Suggest they may reply with a numbered list (1.-6.) or skip fields for later.",
        "Do not echo the user's message verbatim.",
    ]
    if bootstrap_body:
        lines.extend(["", "[BOOTSTRAP.md]", bootstrap_body.strip()])
    return "\n".join(lines)


def bootstrap_capture_instructions(
    *,
    workspace: WorkspaceConfig,
    bootstrap_body: str | None,
    content_root: Path | None = None,
) -> str:
    """Extra tier-B instructions when bootstrap answers arrive after the intro turn.

    Args:
        workspace (WorkspaceConfig): Workspace config.
        bootstrap_body (str | None): ``BOOTSTRAP.md`` contents.
        content_root (Path | None): Workspace root for missing-field hints.

    Returns:
        str: Instruction block appended to tier-B static instructions.

    Examples:
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> "BOOTSTRAP_CAPTURE" in bootstrap_capture_instructions(
        ...     workspace=WorkspaceConfig.minimal(),
        ...     bootstrap_body=None,
        ... )
        True
    """
    _ = workspace
    lines = [
        "BOOTSTRAP_CAPTURE: Bootstrap is not complete. The operator is answering first-run",
        "questions from the prior intro. Use ``write`` in this turn to persist",
        "their answers to USER.md (Name, Role, Timezone, Style, Language, Preferences),",
        "SOUL.md (tone), and IDENTITY.md (vibe) per BOOTSTRAP.md.",
        "Do not claim you saved files unless ``write`` returned success in this turn.",
    ]
    if content_root is not None:
        missing = missing_user_md_bootstrap_fields(content_root)
        if missing:
            lines.append(
                f"USER.md still missing: {', '.join(missing)}. "
                "Ask about any gaps they have not answered yet."
            )
    if bootstrap_body:
        lines.extend(["", "[BOOTSTRAP.md]", bootstrap_body.strip()])
    return "\n".join(lines)
