"""Dashboard SQL query helpers.

Module: sevn.ui.dashboard.query
Depends: sevn.ui.dashboard.query.pagination, sevn.ui.dashboard.query.storage, sevn.ui.dashboard.query.traces

Exports:
    PageParams — normalized pagination pair.
    clamp_limit — page-size clamp helper.
    ensure_trace_connection — open/migrate traces DB through spec 04.
    list_active_run_snapshots — ``active_run_snapshots`` summaries.
    list_gateway_sessions — gateway session summaries.
    list_provider_calls — per-session provider trace rows.
    list_trace_events — trace browse rows.
    get_span_with_children — nested span tree for detail view.
    search_trace_events — FTS5 global search.
    budget_summary_from_traces — budget rollups + subscription windows.
    audit_timeline_from_traces — mission audit timeline page.
    tool_frequency_from_traces — tool frequency aggregates.
    daily_volume_from_traces — daily volume from rollups.
    approval_timeline_from_traces — approval audit rows.
"""

from __future__ import annotations

from sevn.ui.dashboard.query.audit_analytics import (
    approval_timeline_from_traces,
    audit_timeline_from_traces,
    daily_volume_from_traces,
    tool_frequency_from_traces,
)
from sevn.ui.dashboard.query.budget import budget_summary_from_traces
from sevn.ui.dashboard.query.pagination import PageParams, clamp_limit
from sevn.ui.dashboard.query.search import search_trace_events
from sevn.ui.dashboard.query.storage import list_active_run_snapshots, list_gateway_sessions
from sevn.ui.dashboard.query.traces import (
    ensure_trace_connection,
    get_span_with_children,
    list_provider_calls,
    list_trace_events,
)

__all__ = [
    "PageParams",
    "approval_timeline_from_traces",
    "audit_timeline_from_traces",
    "budget_summary_from_traces",
    "clamp_limit",
    "daily_volume_from_traces",
    "ensure_trace_connection",
    "get_span_with_children",
    "list_active_run_snapshots",
    "list_gateway_sessions",
    "list_provider_calls",
    "list_trace_events",
    "search_trace_events",
    "tool_frequency_from_traces",
]
