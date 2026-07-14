<!-- generated: do not edit by hand; run `sevn readme update evolution` -->
# Bot evolution — Issue pipelines, spec-kit stages, approvals, and Mission Control evolution APIs

[![Spec][spec-badge]][spec-link]
[![Source][source-badge]][source-link]
[![Index][index-badge]][index-link]

> **Summary.** Issue pipelines, spec-kit stages, approvals, and Mission Control evolution APIs.

## Level 1 — Overview (non-technical)

**Bot evolution** is a core part of sevn.bot — the personal AI assistant you run on your own machine. Issue pipelines, spec-kit stages, approvals, and Mission Control evolution APIs.

In everyday use, bot evolution helps Sevn do its job reliably: you interact through familiar channels (Telegram, browser, voice), and this layer keeps those interactions safe, consistent, and under your control.

## Level 2 — How it works (technical)

### Components and layout

Implementation lives under `src/sevn/evolution/`. The package contains 21 Python module(s); primary entry points include `src/sevn/evolution/__init__.py`, `src/sevn/evolution/approvals.py`, `src/sevn/evolution/bug_pipeline.py`, `src/sevn/evolution/cursor_poll_scheduler.py`, `src/sevn/evolution/events.py`, `src/sevn/evolution/executors/__init__.py`, and 15 more.

### Data and control flow

Bot evolution is organized around `  init  `, `approvals`, `bug pipeline`, `cursor poll scheduler`, and 2 more under `src/sevn/evolution/` with 21 Python module(s) in the scanned tree. Primary entry points include approvals.py (EvolutionApproval.to_dict), bug_pipeline.py (run_bug_pipeline), cursor_poll_scheduler.py (CursorPollScheduler.start), events.py (EvolutionIssueEventFanoutFn.publish).

### Configuration

Operator settings come from `sevn.json` in the workspace. Related normative specs: `about-sevn.bot/specs/35-bot-evolution.md`. Run `sevn config validate` after edits; use `sevn doctor` to confirm the install sees the expected layout.

### Key modules

- `src/sevn/evolution/approvals.py` — `EvolutionApproval.to_dict`, `EvolutionApproval.from_dict`, `approvals_dir`, `save_approval`
- `src/sevn/evolution/bug_pipeline.py` — `run_bug_pipeline`
- `src/sevn/evolution/cursor_poll_scheduler.py` — `CursorPollScheduler.start`, `CursorPollScheduler.stop`, `CursorPollScheduler.poll_once`
- `src/sevn/evolution/events.py` — `EvolutionIssueEventFanoutFn.publish`, `maybe_publish_issue_event`, `evolution_issue_ws_topic`
- `src/sevn/evolution/executors/local.py` — `dispatch_local_implement`

### Spec context

From about-sevn.bot/specs/35-bot-evolution.md:
Deliver src/sevn/evolution/ and the operator-facing Evolution surface so sevn.bot can evolve its own codebase as a first-class product pillar — not an optional add-on — spanning understand → file work

Deliver src/sevn/evolution/ and the operator-facing Evolution surface so sevn.bot can evolve its own codebase as a first-class product pillar — not an optional add-on — spanning understand → file work

Primary code trees: `src/sevn/evolution/`.

Initial draft for **Purpose** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Purpose — acceptance criteria and edge cases.

## Level 3 — Deep dive (low-level, technical)

Primary source tree: [`src/sevn/evolution`](../../src/sevn/evolution/) (21 Python files). Normative design: `about-sevn.bot/specs/35-bot-evolution.md`.

### Module inventory

Bot evolution pillar (about-sevn.bot/specs/35-bot-evolution.md).

Working with [`__init__.py`](../../src/sevn/evolution/__init__.py): inspect the public entry points below.

Evolution HITL approval queue (about-sevn.bot/specs/35-bot-evolution.md §2.8).

Working with [`approvals.py`](../../src/sevn/evolution/approvals.py): inspect the public entry points below.
Start with [`EvolutionApproval.to_dict`](../../src/sevn/evolution/approvals.py#L53), then [`EvolutionApproval.from_dict`](../../src/sevn/evolution/approvals.py#L74), [`approvals_dir`](../../src/sevn/evolution/approvals.py#L116), [`save_approval`](../../src/sevn/evolution/approvals.py#L149).

Bug evolution pipeline (about-sevn.bot/specs/35-bot-evolution.md §4.2).

Working with [`bug_pipeline.py`](../../src/sevn/evolution/bug_pipeline.py): inspect the public entry points below.
Start with [`run_bug_pipeline`](../../src/sevn/evolution/bug_pipeline.py#L67).

Background 60-second poller for Cursor Cloud evolution issues (about-sevn.bot/specs/35-bot-evolution.md FL-4C.3).

Every 60 s the scheduler scans issues where state=implementing,
executor=cursor_cloud, and cursor_job_id is set, calls
:func:~sevn.evolution.router.poll_cursor_cloud_for_issue for each, then fans
the result to :class:~sevn.gateway.evolution_issue_events.EvolutionIssueEventFanout.

The scheduler runs only when my_sevn.executors.cursor_poll_mode is
"background" (default); in "inline" or "manual" modes it is a no-op.

Working with [`cursor_poll_scheduler.py`](../../src/sevn/evolution/cursor_poll_scheduler.py): inspect the public entry points below.
Start with [`CursorPollScheduler.start`](../../src/sevn/evolution/cursor_poll_scheduler.py#L105), then [`CursorPollScheduler.stop`](../../src/sevn/evolution/cursor_poll_scheduler.py#L127), [`CursorPollScheduler.poll_once`](../../src/sevn/evolution/cursor_poll_scheduler.py#L147).

Evolution issue event envelopes for dashboard WebSocket fan-out (about-sevn.bot/specs/35-bot-evolution.md §2.8).

Working with [`events.py`](../../src/sevn/evolution/events.py): inspect the public entry points below.
Start with [`EvolutionIssueEventFanoutFn.publish`](../../src/sevn/evolution/events.py#L35), then [`maybe_publish_issue_event`](../../src/sevn/evolution/events.py#L51), [`evolution_issue_ws_topic`](../../src/sevn/evolution/events.py#L80).

Evolution executor modules (about-sevn.bot/specs/35-bot-evolution.md FL-4A).

Working with [`__init__.py`](../../src/sevn/evolution/executors/__init__.py): inspect the public entry points below.

Local tier-B worktree executor (about-sevn.bot/specs/35-bot-evolution.md FL-4A).

Assembles the run_b_turn input bundle from evolution primitives, avoiding a
full gateway boot.  All gateway-coupled objects (ToolSet, ToolExecutor,
TriageResult, ToolContext, ResolvedTierBModel) are constructed here
with evolution-specific settings so the executor is self-contained.

Working with [`local.py`](../../src/sevn/evolution/executors/local.py): inspect the public entry points below.
Start with [`dispatch_local_implement`](../../src/sevn/evolution/executors/local.py#L323).

Feature evolution pipeline (about-sevn.bot/specs/35-bot-evolution.md §4.1).

Working with [`feature_pipeline.py`](../../src/sevn/evolution/feature_pipeline.py): inspect the public entry points below.
Start with [`feature_artefacts_dir`](../../src/sevn/evolution/feature_pipeline.py#L51), then [`record_pipeline_approval`](../../src/sevn/evolution/feature_pipeline.py#L154), [`run_feature_pipeline`](../../src/sevn/evolution/feature_pipeline.py#L203).

Inbound GitHub issue ingest into the local evolution registry (about-sevn.bot/specs/35-bot-evolution.md FL-1).

Working with [`github_sync.py`](../../src/sevn/evolution/github_sync.py): inspect the public entry points below.
Start with [`import_github_issue_with_created`](../../src/sevn/evolution/github_sync.py#L181), then [`import_github_issue`](../../src/sevn/evolution/github_sync.py#L238), [`sync_github_issues`](../../src/sevn/evolution/github_sync.py#L292).

Evolution issue registry — local JSON (about-sevn.bot/specs/35-bot-evolution.md §2.7).

Working with [`issues.py`](../../src/sevn/evolution/issues.py): inspect the public entry points below.
Start with [`EvolutionIssue.to_dict`](../../src/sevn/evolution/issues.py#L61), then [`EvolutionIssue.from_dict`](../../src/sevn/evolution/issues.py#L83), [`utc_now_iso`](../../src/sevn/evolution/issues.py#L135), [`issues_dir`](../../src/sevn/evolution/issues.py#L148).

Auto-start evolution pipeline on issue import (the design docs AR-1).

When my_sevn.issues.auto_run_on_import is true and a GitHub issue is **newly**
imported (created=True), this module schedules :func:run_pipeline in the background
via :func:spawn_logged.  Dry-run flags are left None so they resolve from
my_sevn.pipelines config defaults — D3 decision in the wave plan.

PipelineBlockedError` is swallowed: feature issues that require approval stop at the
HITL gate and that is the expected operator experience (D5).

Working with [`pipeline_autostart.py`](../../src/sevn/evolution/pipeline_autostart.py): inspect the public entry points below.
Start with [`maybe_auto_run_pipeline_after_import`](../../src/sevn/evolution/pipeline_autostart.py#L38).

Shared evolution pipeline helpers (about-sevn.bot/specs/35-bot-evolution.md §4).

Working with [`pipeline_common.py`](../../src/sevn/evolution/pipeline_common.py): inspect the public entry points below.
Start with [`publish_transition`](../../src/sevn/evolution/pipeline_common.py#L29), then [`set_issue_stage`](../../src/sevn/evolution/pipeline_common.py#L83).

9 more Python files under [`src/sevn/evolution`](../../src/sevn/evolution/) — including `src/sevn/evolution/pipeline_runner.py`, `src/sevn/evolution/pipelines.py`, `src/sevn/evolution/promotion.py`, `src/sevn/evolution/repo_sync_scheduler.py`.

### Extension and invariants

Follow [`35-bot-evolution.md`](../../about-sevn.bot/specs/35-bot-evolution.md) for merge gates, error semantics, and compatibility constraints. After code changes under [`src/sevn/evolution`](../../src/sevn/evolution/), run `sevn readme update evolution` and `make readme-check`.

## References

- [../../about-sevn.bot/specs/35-bot-evolution.md](../../about-sevn.bot/specs/35-bot-evolution.md)

[spec-badge]: https://img.shields.io/badge/Spec-2a7fc6?style=for-the-badge&logo=readthedocs&logoColor=white
[spec-link]: ../../about-sevn.bot/specs/35-bot-evolution.md
[source-badge]: https://img.shields.io/badge/Source-0c0a09?style=for-the-badge&logo=github&logoColor=white
[source-link]: ../../src/sevn/evolution/
[index-badge]: https://img.shields.io/badge/All_READMEs-5fb1f7?style=for-the-badge&logo=markdown&logoColor=white
[index-link]: INDEX.md
