"""Declarative Mission Control per-tab schema descriptors (W0 inventory seed).

Module: sevn.ui.dashboard.dashboard_schema
Depends: sevn.ui.dashboard.tab_registry

Exports:
    ViewDescriptor — one sub-view within a dashboard tab.
    ActionDescriptor — one SPA action tied to an HTTP endpoint.
    TabDescriptor — full contract for one Mission Control tab.
    descriptor_slugs — sorted slugs declared in the schema source.
    missing_descriptor_slugs — registry slugs absent from descriptors.

Examples:
    >>> len(DASHBOARD_TAB_DESCRIPTORS)
    46
    >>> "overview" in DASHBOARD_TAB_DESCRIPTORS
    True
"""

from __future__ import annotations

from typing import Any, TypedDict

from sevn.ui.dashboard.tab_registry import (
    POST_V1_PLACEHOLDER_SLUGS,
    TAB_SLUGS,
    WIRED_SLUGS,
    tab_slug,
)

__all__ = [
    "DASHBOARD_SHELL",
    "DASHBOARD_TAB_DESCRIPTORS",
    "descriptor_slugs",
    "missing_descriptor_slugs",
]


class ViewDescriptor(TypedDict):
    """One sub-view within a dashboard tab."""

    id: str
    label: str
    selector: str


class ActionDescriptor(TypedDict, total=False):
    """One SPA action (button/form) tied to an HTTP endpoint."""

    id: str
    label: str
    selector: str
    method: str
    endpoint: str
    destructive: bool
    needs_seed: bool


class TabDescriptor(TypedDict):
    """Full contract for one Mission Control tab."""

    group: str
    title: str
    kind: str
    views: list[ViewDescriptor]
    actions: list[ActionDescriptor]
    read_endpoints: list[str]
    key_selectors: dict[str, str]


def _view(view_id: str, label: str, selector: str) -> ViewDescriptor:
    """Build one view descriptor.

    Args:
        view_id (str): Stable view id for E2E snapshots.
        label (str): Human-readable label.
        selector (str): CSS selector for the view container.

    Returns:
        ViewDescriptor: View row for schema emission.

    Examples:
        >>> _view("main", "Overview", "#content > article.card")["id"]
        'main'
    """
    return ViewDescriptor(id=view_id, label=label, selector=selector)


def _action(
    action_id: str,
    label: str,
    selector: str,
    method: str,
    endpoint: str,
    *,
    destructive: bool = False,
    needs_seed: bool = False,
) -> ActionDescriptor:
    """Build one action descriptor.

    Args:
        action_id (str): Stable action id.
        label (str): Button or control label.
        selector (str): CSS selector for the control.
        method (str): HTTP method.
        endpoint (str): ``/api/v1`` path (may include ``{param}`` placeholders).
        destructive (bool): Whether the action deletes or disrupts host state.
        needs_seed (bool): Whether E2E should create a throwaway entity first.

    Returns:
        ActionDescriptor: Action row for schema emission.

    Examples:
        >>> _action("save", "Save", "#save", "PUT", "/api/v1/security")["method"]
        'PUT'
    """
    row: ActionDescriptor = ActionDescriptor(
        id=action_id,
        label=label,
        selector=selector,
        method=method,
        endpoint=endpoint,
    )
    if destructive:
        row["destructive"] = True
    if needs_seed:
        row["needs_seed"] = True
    return row


def _tab(
    *,
    group: str,
    title: str,
    kind: str = "wired",
    views: list[ViewDescriptor] | None = None,
    actions: list[ActionDescriptor] | None = None,
    read_endpoints: list[str] | None = None,
    key_selectors: dict[str, str] | None = None,
) -> TabDescriptor:
    """Build one tab descriptor with sensible defaults.

    Args:
        group (str): Sidebar group slug (``core``, ``ops``, …).
        title (str): Tab display title.
        kind (str): ``wired``, ``post_v1``, or ``stub``.
        views (list[ViewDescriptor] | None): Sub-views; defaults to main panel.
        actions (list[ActionDescriptor] | None): Mutating controls.
        read_endpoints (list[str] | None): Read-only API paths used by the tab.
        key_selectors (dict[str, str] | None): Extra selectors for E2E.

    Returns:
        TabDescriptor: Tab contract row.

    Examples:
        >>> row = _tab(group="core", title="Overview", read_endpoints=["/api/v1/runs/snapshots"])
        >>> row["kind"]
        'wired'
    """
    return TabDescriptor(
        group=group,
        title=title,
        kind=kind,
        views=views or [_view("main", title, "#content > article.card")],
        actions=actions or [],
        read_endpoints=read_endpoints or [],
        key_selectors=key_selectors or {},
    )


DASHBOARD_SHELL: dict[str, Any] = {
    "key_selectors": {
        "sidebar": "#tabs",
        "sidebar_group": ".sidebar__group",
        "sidebar_item": ".sidebar__item",
        "active_tab": '.sidebar__item[aria-current="page"]',
        "panel": "#content > article.card",
        "login_panel": "#login-panel",
        "login_form": "#login-form",
        "login_password": "#login-password",  # nosec B105
        "login_error": "#login-error",
        "auth_badge": "#auth-badge",
        "global_search": "#global-search",
        "system_menu_toggle": "#system-menu-toggle",
        "system_menu_panel": "#system-menu-panel",
        "log_retention_modal": "#log-retention-modal",
        "log_retention_form": "#log-retention-form",
    },
    "system_menu_actions": [
        _action(
            "logging-save",
            "Save logging retention",
            "#log-retention-form",
            "PUT",
            "/api/v1/system/logging",
            needs_seed=True,
        ),
    ],
}

DASHBOARD_TAB_DESCRIPTORS: dict[str, TabDescriptor] = {
    # --- Core ---
    "overview": _tab(
        group="core",
        title="Overview",
        read_endpoints=[
            "/api/v1/runs/snapshots",
            "/api/v1/budget/summary",
            "/api/v1/proxy/status",
            "/api/v1/sessions",
            "/api/v1/providers/health",
        ],
        key_selectors={
            "live_activity": "#live-activity-feed",
            "grid": ".mission-overview-grid",
            "badges": ".mission-overview-badges",
        },
    ),
    "chat": _tab(
        group="core",
        title="Chat",
        key_selectors={
            "status": "#chat-status",
            "log": "#chat-log",
            "input": "#chat-input",
            "composer": "#chat-composer",
            "tool_cards": "#chat-tool-cards",
            "session_id": "#chat-session-id",
        },
        actions=[
            _action(
                "mint-token",
                "Mint webchat token",
                "#chat-composer",
                "POST",
                "/api/v1/chat/token",
            ),
            _action("fork", "Fork session", "#chat-fork-btn", "POST", "/api/v1/chat/fork"),
        ],
    ),
    "canvas-openui": _tab(
        group="core",
        title="Canvas (OpenUI)",
        read_endpoints=["/api/v1/dashboard/canvas"],
        key_selectors={
            "iframe": ".mission-canvas-iframe",
            "frame": ".mission-canvas-frame",
        },
    ),
    "sessions": _tab(
        group="core",
        title="Sessions",
        views=[
            _view("list", "Sessions list", "#content > article.card"),
            _view("api-calls", "Session API calls", "#content > article.card"),
        ],
        read_endpoints=[
            "/api/v1/sessions",
            "/api/v1/sessions/{session_id}/api-calls",
        ],
    ),
    # --- Observability ---
    "traces": _tab(
        group="observability",
        title="Traces",
        views=[
            _view("list", "Trace list", "#trace-filters"),
            _view("detail", "Trace detail", "#trace-detail"),
        ],
        read_endpoints=[
            "/api/v1/traces",
            "/api/v1/traces/{span_id}",
        ],
        key_selectors={
            "filters": "#trace-filters",
            "trace_row": ".trace-row[data-span-id]",
            "detail": "#trace-detail",
            "replay_turn": "#trace-replay-turn",
            "replay_status": "#trace-replay-status",
        },
        actions=[
            _action(
                "replay-turn",
                "Replay turn",
                "#trace-replay-turn",
                "POST",
                "/api/v1/sessions/{session_id}/turns/{turn_id}/replay",
                needs_seed=True,
            ),
        ],
    ),
    "audit-analytics": _tab(
        group="observability",
        title="Audit & Analytics",
        read_endpoints=[
            "/api/v1/audit/timeline",
            "/api/v1/analytics/tool-frequency",
            "/api/v1/analytics/daily-volume",
            "/api/v1/analytics/approvals",
        ],
    ),
    "providers-llms": _tab(
        group="observability",
        title="Providers & LLMs",
        read_endpoints=["/api/v1/providers/health"],
    ),
    "budget-cost": _tab(
        group="observability",
        title="Budget & Cost",
        read_endpoints=["/api/v1/budget/summary"],
    ),
    "channels": _tab(
        group="observability",
        title="Channels",
        read_endpoints=[
            "/api/v1/channels/status",
            "/api/v1/channels/config",
        ],
        key_selectors={"form": "#channels-config-form"},
        actions=[
            _action(
                "save-config",
                "Save channel settings",
                "#channels-config-form",
                "PUT",
                "/api/v1/channels/config",
                needs_seed=True,
            ),
        ],
    ),
    "sub-agents": _tab(
        group="observability",
        title="Sub-agents",
        read_endpoints=["/api/v1/mission/subagents"],
        key_selectors={
            "count_chips": ".subagents-count-chips",
            "running_table": "#subagents-running-table",
            "recent_table": "#subagents-recent-table",
            "limits_panel": "#subagents-limits-panel",
        },
        actions=[
            _action(
                "kill-run",
                "Kill sub-agent",
                ".subagent-kill-btn",
                "POST",
                "/api/v1/mission/subagents/{id}/kill",
                destructive=True,
                needs_seed=True,
            ),
            _action(
                "kill-all-role",
                "Kill all for role",
                ".subagent-kill-all-btn",
                "POST",
                "/api/v1/mission/subagents/kill_all",
                destructive=True,
                needs_seed=True,
            ),
        ],
    ),
    "alerts-logs": _tab(
        group="observability",
        title="Alerts & Logs",
        read_endpoints=[
            "/api/v1/alerts/rollup",
            "/api/v1/proxy/logs",
        ],
        key_selectors={
            "refresh_logs": "#alerts-refresh-logs",
            "log_tail": ".log-tail",
        },
        actions=[
            _action(
                "refresh-logs",
                "Refresh logs",
                "#alerts-refresh-logs",
                "GET",
                "/api/v1/proxy/logs",
            ),
        ],
    ),
    # --- Agent ---
    "agent-config": _tab(
        group="agent",
        title="Agent Config",
        views=[
            _view("main", "Agent config", "#agent-slot-editor"),
        ],
        read_endpoints=["/api/v1/agent/config"],
        key_selectors={
            "unified_model": "#agent-unified-model",
            "slot_editor": "#agent-slot-editor",
            "save_btn": "#agent-config-save-btn",
            "reset_btn": "#agent-reset-suggestions-btn",
            "status": "#agent-config-status",
        },
        actions=[
            _action(
                "save",
                "Save agent config",
                "#agent-config-save-btn",
                "PUT",
                "/api/v1/agent/config",
                needs_seed=True,
            ),
        ],
    ),
    "model-params": _tab(
        group="agent",
        title="Model Params",
        read_endpoints=["/api/v1/agent/llm-params"],
        key_selectors={
            "form": "#model-params-form",
            "save_btn": "#model-params-save-btn",
            "status": "#model-params-status",
        },
        actions=[
            _action(
                "save",
                "Save model params",
                "#model-params-save-btn",
                "PUT",
                "/api/v1/agent/llm-params",
                needs_seed=True,
            ),
        ],
    ),
    "tools-permissions": _tab(
        group="agent",
        title="Tools & Permissions",
        read_endpoints=[
            "/api/v1/agent/tools-health",
            "/api/v1/agent/permissions",
            "/api/v1/agent/approvals/pending",
        ],
        key_selectors={
            "permissions_form": "#permissions-form",
            "permissions_editor": "#permissions-editor",
            "tools_editor": "#tools-editor",
            "approval_btn": ".tool-approval-btn",
        },
        actions=[
            _action(
                "approve",
                "Approve pending tool",
                ".tool-approval-btn",
                "POST",
                "/api/v1/agent/approvals/{decision_id}",
                needs_seed=True,
            ),
            _action(
                "save-permissions",
                "Save permissions",
                "#permissions-form",
                "PUT",
                "/api/v1/agent/permissions",
                needs_seed=True,
            ),
        ],
    ),
    "skills": _tab(
        group="agent",
        title="Skills",
        read_endpoints=[
            "/api/v1/agent/skills",
            "/api/v1/agent/skills/bundled",
        ],
        key_selectors={
            "install_form": "#skill-install-form",
            "install_select": "#skill-install-select",
        },
        actions=[
            _action(
                "install",
                "Install skill",
                "#skill-install-form",
                "POST",
                "/api/v1/agent/skills/install",
                needs_seed=True,
            ),
            _action(
                "promote",
                "Promote skill",
                ".skill-promote-btn",
                "POST",
                "/api/v1/agent/skills/{skill_name}/promote",
                needs_seed=True,
            ),
            _action(
                "toggle",
                "Toggle skill",
                ".skill-toggle-btn",
                "POST",
                "/api/v1/agent/skills/{skill_name}/toggle",
                needs_seed=True,
            ),
            _action(
                "uninstall",
                "Uninstall skill",
                ".skill-uninstall-btn",
                "DELETE",
                "/api/v1/agent/skills/{skill_name}",
                destructive=True,
                needs_seed=True,
            ),
        ],
    ),
    "mcp-servers": _tab(
        group="agent",
        title="MCP Servers",
        read_endpoints=["/api/v1/agent/mcp-servers"],
        key_selectors={"form": "#mcp-servers-form"},
        actions=[
            _action(
                "save",
                "Save MCP servers",
                "#mcp-servers-form",
                "PUT",
                "/api/v1/agent/mcp-servers",
                needs_seed=True,
            ),
        ],
    ),
    "coding-agents": _tab(
        group="agent",
        title="Coding Agents",
        read_endpoints=["/api/v1/coding-agents"],
        key_selectors={
            "panel": "#coding-agents-panel",
            "list": "#coding-agents-list",
            "save": "#coding-agents-save",
        },
        actions=[
            _action(
                "save",
                "Save coding agents",
                "#coding-agents-save",
                "PUT",
                "/api/v1/coding-agents",
                needs_seed=True,
            ),
        ],
    ),
    # --- Knowledge ---
    "memory": _tab(
        group="knowledge",
        title="Memory",
        read_endpoints=[
            "/api/v1/knowledge/memory",
            "/api/v1/files/content",
        ],
        key_selectors={
            "editor_path": "#file-editor-path",
            "editor_content": "#file-editor-content",
            "editor_save": "#file-editor-save",
            "editor_new": "#file-editor-new",
            "editor_delete": "#file-editor-delete",
        },
        actions=[
            _action(
                "save-file",
                "Save file",
                "#file-editor-save",
                "PUT",
                "/api/v1/files/content",
                needs_seed=True,
            ),
            _action(
                "new-file",
                "New file",
                "#file-editor-new",
                "POST",
                "/api/v1/files",
                needs_seed=True,
            ),
            _action(
                "delete-file",
                "Delete file",
                "#file-editor-delete",
                "DELETE",
                "/api/v1/files",
                destructive=True,
                needs_seed=True,
            ),
        ],
    ),
    "second-brain": _tab(
        group="knowledge",
        title="Second Brain",
        read_endpoints=["/api/v1/knowledge/second-brain"],
        key_selectors={
            "editor_path": "#file-editor-path",
            "editor_save": "#file-editor-save",
        },
        actions=[
            _action(
                "save-file",
                "Save file",
                "#file-editor-save",
                "PUT",
                "/api/v1/files/content",
                needs_seed=True,
            ),
        ],
    ),
    "workspace-files": _tab(
        group="knowledge",
        title="Workspace Files",
        read_endpoints=[
            "/api/v1/knowledge/workspace-files",
            "/api/v1/files/tree",
            "/api/v1/files/content",
        ],
        key_selectors={
            "editor_path": "#file-editor-path",
            "editor_save": "#file-editor-save",
        },
        actions=[
            _action(
                "save-file",
                "Save file",
                "#file-editor-save",
                "PUT",
                "/api/v1/files/content",
                needs_seed=True,
            ),
        ],
    ),
    "code-understanding": _tab(
        group="knowledge",
        title="Code Understanding",
        read_endpoints=[
            "/api/v1/knowledge/code-understanding",
            "/api/v1/knowledge/graph",
        ],
    ),
    # --- Self-improve ---
    "jobs": _tab(
        group="self-improve",
        title="Jobs",
        views=[
            _view("list", "Jobs list", "#content > article.card"),
            _view("eval-report", "Eval report", "#content > article.card"),
        ],
        read_endpoints=[
            "/api/v1/self_improve/jobs",
            "/api/v1/self_improve/jobs/{job_id}/eval_report",
        ],
        key_selectors={
            "enqueue": "#si-enqueue-job",
            "cycle": "#si-cycle-btn",
        },
        actions=[
            _action(
                "enqueue",
                "Enqueue job",
                "#si-enqueue-job",
                "POST",
                "/api/v1/self_improve/jobs",
                needs_seed=True,
            ),
            _action(
                "cycle",
                "Run cycle",
                "#si-cycle-btn",
                "POST",
                "/api/v1/self_improve/cycle",
            ),
        ],
    ),
    "trajectories": _tab(
        group="self-improve",
        title="Trajectories",
        read_endpoints=["/api/v1/self_improve/trajectories"],
    ),
    "feedback": _tab(
        group="self-improve",
        title="Feedback",
        read_endpoints=["/api/v1/self_improve/feedback"],
    ),
    "rlm-training": _tab(
        group="self-improve",
        title="RLM Config",
        read_endpoints=["/api/v1/self_improve/rlm-training"],
    ),
    "experiments-metrics": _tab(
        group="self-improve",
        title="Experiments & Metrics",
        read_endpoints=["/api/v1/self_improve/experiments"],
    ),
    # --- Evolution ---
    "issues": _tab(
        group="evolution",
        title="Issues",
        read_endpoints=["/api/v1/evolution/issues"],
        key_selectors={
            "import_number": "#gh-import-number",
            "import_btn": "#gh-import-btn",
            "sync_btn": "#gh-sync-btn",
            "run_form": "#issues-run-form",
            "run_submit": "#run-submit-btn",
        },
        actions=[
            _action(
                "import",
                "Import issue",
                "#gh-import-btn",
                "POST",
                "/api/v1/evolution/issues/import",
                needs_seed=True,
            ),
            _action(
                "sync",
                "Sync issues",
                "#gh-sync-btn",
                "POST",
                "/api/v1/evolution/issues/sync",
            ),
            _action(
                "run-pipeline",
                "Run pipeline",
                "#run-submit-btn",
                "POST",
                "/api/v1/evolution/pipelines/{issue_id}/run",
                needs_seed=True,
            ),
        ],
    ),
    "pipelines": _tab(
        group="evolution",
        title="Pipelines",
        read_endpoints=["/api/v1/evolution/pipelines"],
        actions=[
            _action(
                "run",
                "Run pipeline",
                ".pipeline-run",
                "POST",
                "/api/v1/evolution/pipelines/{issue_id}/run",
                needs_seed=True,
            ),
            _action(
                "poll",
                "Poll pipeline",
                ".pipeline-poll",
                "POST",
                "/api/v1/evolution/pipelines/{issue_id}/poll",
                needs_seed=True,
            ),
            _action(
                "kill",
                "Kill pipeline",
                ".pipeline-kill",
                "POST",
                "/api/v1/evolution/pipelines/{issue_id}/kill",
                destructive=True,
                needs_seed=True,
            ),
        ],
    ),
    "approvals": _tab(
        group="evolution",
        title="Approvals",
        read_endpoints=["/api/v1/evolution/approvals"],
        actions=[
            _action(
                "approve",
                "Approve",
                ".approval-approve",
                "POST",
                "/api/v1/evolution/approvals/{approval_id}/approve",
                needs_seed=True,
            ),
            _action(
                "reject",
                "Reject",
                ".approval-reject",
                "POST",
                "/api/v1/evolution/approvals/{approval_id}/reject",
                needs_seed=True,
            ),
        ],
    ),
    "spec-kit": _tab(
        group="evolution",
        title="Spec-Kit",
        read_endpoints=[
            "/api/v1/spec-kit/constitution",
            "/api/v1/spec-kit/options",
            "/api/v1/spec-kit/runs",
        ],
        key_selectors={
            "constitution": "#spec-kit-constitution",
            "save": "#spec-kit-save",
            "reset": "#spec-kit-reset",
            "options": "#spec-kit-options",
            "options_save": "#spec-kit-options-save",
            "test_plan": "#spec-kit-test-plan",
        },
        actions=[
            _action(
                "save-constitution",
                "Save constitution",
                "#spec-kit-save",
                "PUT",
                "/api/v1/spec-kit/constitution",
                needs_seed=True,
            ),
            _action(
                "reset-template",
                "Reset template",
                "#spec-kit-reset",
                "GET",
                "/api/v1/spec-kit/constitution/template",
            ),
            _action(
                "save-options",
                "Save options",
                "#spec-kit-options-save",
                "PUT",
                "/api/v1/spec-kit/options",
                needs_seed=True,
            ),
            _action(
                "test-invoke",
                "Test invoke",
                "#spec-kit-test-plan",
                "POST",
                "/api/v1/spec-kit/test-invoke",
            ),
        ],
    ),
    "evolution-traces": _tab(
        group="evolution",
        title="Evolution Traces",
        read_endpoints=["/api/v1/evolution/traces"],
    ),
    "stats": _tab(
        group="evolution",
        title="Stats",
        read_endpoints=["/api/v1/evolution/stats"],
    ),
    # --- Ops ---
    "cron": _tab(
        group="ops",
        title="Cron",
        read_endpoints=["/api/v1/cron/jobs"],
        key_selectors={
            "create_form": "#cron-create-form",
            "config_form": "#cron-config-form",
            "new_id": "#cron-new-id",
        },
        actions=[
            _action(
                "create",
                "Create job",
                "#cron-create-form",
                "POST",
                "/api/v1/cron/jobs",
                needs_seed=True,
            ),
            _action(
                "run",
                "Run job",
                ".cron-run-btn",
                "POST",
                "/api/v1/cron/jobs/{job_id}/run",
                needs_seed=True,
            ),
            _action(
                "toggle",
                "Toggle job",
                ".cron-toggle-btn",
                "PUT",
                "/api/v1/cron/jobs/{job_id}",
                needs_seed=True,
            ),
            _action(
                "delete",
                "Delete job",
                ".cron-delete-btn",
                "DELETE",
                "/api/v1/cron/jobs/{job_id}",
                destructive=True,
                needs_seed=True,
            ),
            _action(
                "pause-all",
                "Pause scheduler",
                "#cron-config-form",
                "PUT",
                "/api/v1/cron/config",
                needs_seed=True,
            ),
        ],
    ),
    "security": _tab(
        group="ops",
        title="Security",
        read_endpoints=["/api/v1/security"],
        key_selectors={"form": "#security-toggles-form"},
        actions=[
            _action(
                "save",
                "Save security toggles",
                "#security-toggles-form",
                "PUT",
                "/api/v1/security",
                needs_seed=True,
            ),
        ],
    ),
    "secrets": _tab(
        group="ops",
        title="Secrets",
        read_endpoints=[
            "/api/v1/secrets/aliases",
            "/api/v1/secrets/aliases/{logical_key}/reveal",
            "/api/v1/secrets/store",
            "/api/v1/secrets/store/entries",
        ],
        key_selectors={
            "alias": "#secrets-alias",
            "value": "#secrets-value",
            "show_values": "#secrets-show-values",
            "exposed_banner": "#secrets-exposed-banner",
            "reveal_btn": "#secrets-reveal-btn",
            "save_btn": "#secrets-save-btn",
            "delete_btn": "#secrets-delete-btn",
        },
        actions=[
            _action(
                "reveal",
                "Reveal store entry",
                "#secrets-reveal-btn",
                "GET",
                "/api/v1/secrets/store/entries/{alias}",
                needs_seed=True,
            ),
            _action(
                "save",
                "Save store entry",
                "#secrets-save-btn",
                "PUT",
                "/api/v1/secrets/store/entries/{alias}",
                needs_seed=True,
            ),
            _action(
                "delete",
                "Delete store entry",
                "#secrets-delete-btn",
                "DELETE",
                "/api/v1/secrets/store/entries/{alias}",
                destructive=True,
                needs_seed=True,
            ),
        ],
    ),
    "egress-proxy": _tab(
        group="ops",
        title="Egress proxy",
        read_endpoints=[
            "/api/v1/proxy/status",
            "/api/v1/proxy/logs",
        ],
        key_selectors={
            "restart_btn": "#proxy-restart-btn",
            "refresh_logs_btn": "#proxy-refresh-logs-btn",
            "log_tail": "#proxy-log-tail",
        },
        actions=[
            _action(
                "restart",
                "Restart proxy",
                "#proxy-restart-btn",
                "POST",
                "/api/v1/proxy/restart",
                destructive=True,
            ),
            _action(
                "refresh-logs",
                "Refresh proxy logs",
                "#proxy-refresh-logs-btn",
                "GET",
                "/api/v1/proxy/logs",
            ),
        ],
    ),
    "tunnels-infra": _tab(
        group="ops",
        title="Tunnels & Infra",
        read_endpoints=[
            "/api/v1/tunnels/status",
            "/api/v1/ops/daemons",
        ],
        key_selectors={
            "reload_btn": "#ops-reload-config-btn",
            "dreaming_btn": "#ops-dreaming-run-btn",
            "daemon_action": ".daemon-action-btn",
        },
        actions=[
            _action(
                "reload-config",
                "Reload config",
                "#ops-reload-config-btn",
                "POST",
                "/api/v1/ops/reload-config",
            ),
            _action(
                "dreaming-run",
                "Run dreaming",
                "#ops-dreaming-run-btn",
                "POST",
                "/api/v1/ops/dreaming/run",
            ),
            _action(
                "daemon-action",
                "Daemon action",
                ".daemon-action-btn",
                "POST",
                "/api/v1/ops/daemons/{service}/{action}",
                destructive=True,
            ),
        ],
    ),
    "backup-snapshots": _tab(
        group="ops",
        title="Backup & Snapshots",
        read_endpoints=["/api/v1/backup/manifest"],
        key_selectors={
            "export_btn": "#backup-export-btn",
            "create_btn": "#snapshot-create-btn",
            "import_input": "#backup-import-input",
            "restore_btn": ".snapshot-restore-btn",
        },
        actions=[
            _action(
                "export",
                "Export backup",
                "#backup-export-btn",
                "GET",
                "/api/v1/ops/backup/export",
            ),
            _action(
                "import",
                "Import backup",
                "#backup-import-input",
                "POST",
                "/api/v1/ops/backup/import",
                needs_seed=True,
            ),
            _action(
                "create-snapshot",
                "Create snapshot",
                "#snapshot-create-btn",
                "POST",
                "/api/v1/ops/snapshots",
                needs_seed=True,
            ),
            _action(
                "restore-snapshot",
                "Restore snapshot",
                ".snapshot-restore-btn",
                "POST",
                "/api/v1/ops/snapshots/{snapshot_id}/restore",
                destructive=True,
                needs_seed=True,
            ),
        ],
    ),
    "config": _tab(
        group="ops",
        title="Config",
        views=[
            _view("tree", "Config tree", "#config-tree-panel"),
            _view("text", "Config text", "#config-editor"),
        ],
        read_endpoints=["/api/v1/config/full"],
        key_selectors={
            "mode_tree": "#config-mode-tree",
            "mode_text": "#config-mode-text",
            "validate_btn": "#config-validate-btn",
            "save_btn": "#config-save-btn",
            "error_panel": "#config-error-panel",
            "status": "#config-editor-status",
        },
        actions=[
            _action(
                "validate",
                "Validate config",
                "#config-validate-btn",
                "PUT",
                "/api/v1/config/full",
                needs_seed=True,
            ),
            _action(
                "save",
                "Save config",
                "#config-save-btn",
                "PUT",
                "/api/v1/config/full",
                needs_seed=True,
            ),
        ],
    ),
    "schema-ontology": _tab(
        group="ops",
        title="Schema & Ontology",
        read_endpoints=["/api/v1/schema/ontology"],
    ),
    "sevn-cli": _tab(
        group="ops",
        title="sevn CLI",
        read_endpoints=["/api/v1/cli/shortcuts"],
        key_selectors={
            "args": "#cli-args",
            "run_btn": "#cli-run-btn",
            "output": "#cli-output",
        },
        actions=[
            _action(
                "run",
                "Run CLI command",
                "#cli-run-btn",
                "POST",
                "/api/v1/cli/run",
            ),
        ],
    ),
    "terminal": _tab(
        group="ops",
        title="Terminal",
        key_selectors={
            "status": "#terminal-status",
            "connect_btn": "#terminal-connect-btn",
            "disconnect_btn": "#terminal-disconnect-btn",
            "mount": "#terminal-mount",
        },
        actions=[
            _action(
                "connect",
                "Connect terminal",
                "#terminal-connect-btn",
                "POST",
                "/api/v1/terminal/session",
                destructive=True,
            ),
        ],
    ),
    # --- Surfaces ---
    "telegram-menu": _tab(
        group="surfaces",
        title="Telegram Menu",
        read_endpoints=["/api/v1/surfaces/telegram-menu"],
        key_selectors={"form": "#telegram-menu-form"},
        actions=[
            _action(
                "save",
                "Save telegram menu",
                "#telegram-menu-form",
                "PUT",
                "/api/v1/surfaces/telegram-menu",
                needs_seed=True,
            ),
        ],
    ),
    "web-apps": _tab(
        group="surfaces",
        title="Web Apps",
        read_endpoints=["/api/v1/surfaces/web-apps"],
        key_selectors={"form": "#web-apps-form"},
        actions=[
            _action(
                "save",
                "Save web apps",
                "#web-apps-form",
                "PUT",
                "/api/v1/surfaces/web-apps",
                needs_seed=True,
            ),
        ],
    ),
    "onboarding": _tab(
        group="surfaces",
        title="Onboarding",
        read_endpoints=["/api/v1/surfaces/onboarding"],
    ),
    "users-rbac": _tab(
        group="surfaces",
        title="Users & RBAC",
        read_endpoints=["/api/v1/surfaces/users-rbac"],
    ),
}


def descriptor_slugs() -> list[str]:
    """Return sorted slugs declared in :data:`DASHBOARD_TAB_DESCRIPTORS`.

    Returns:
        list[str]: Sorted descriptor slugs.

    Examples:
        >>> "overview" in descriptor_slugs()
        True
    """
    return sorted(DASHBOARD_TAB_DESCRIPTORS)


def missing_descriptor_slugs() -> list[str]:
    """Return registry slugs that lack a schema descriptor.

    Returns:
        list[str]: Missing slugs (empty when fully covered).

    Examples:
        >>> missing_descriptor_slugs() == []
        True
    """
    return sorted(TAB_SLUGS - set(DASHBOARD_TAB_DESCRIPTORS))


# Sanity: registry coverage at import time (44 wired + 1 post-v1).
assert len(DASHBOARD_TAB_DESCRIPTORS) == 46  # nosec B101
assert not missing_descriptor_slugs()  # nosec B101
assert set(DASHBOARD_TAB_DESCRIPTORS) == WIRED_SLUGS | POST_V1_PLACEHOLDER_SLUGS  # nosec B101
assert tab_slug("Core") == "core"  # nosec B101
