"""Async improve-job worker loop (`specs/33-self-improvement.md` §4.1).

Module: sevn.self_improve.jobs.worker
Depends: asyncio, json, sqlite3, sevn.config.defaults, sevn.config.workspace_config,
    sevn.self_improve.eval, sevn.self_improve.jobs.store, sevn.self_improve.paths,
    sevn.self_improve.sampler, sevn.workspace.layout

Exports:
    EvalGraphRunner — injectable eval graph callable for tests.
    ImproveJobWorker — queued → running → shortlist → awaiting_eval → review/blocked.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from typing import TYPE_CHECKING, Protocol

from loguru import logger

from sevn.config.defaults import (
    DEFAULT_SELF_IMPROVE_EXPLICIT_FEEDBACK_FLOOR_PCT,
    DEFAULT_SELF_IMPROVE_PER_CHANNEL_PCT_MAX,
    DEFAULT_SELF_IMPROVE_PER_CHANNEL_PCT_MIN_VOICE,
    DEFAULT_SELF_IMPROVE_PER_INTENT_PCT_MAX,
    DEFAULT_SELF_IMPROVE_PER_TIER_PCT_MAX,
    DEFAULT_SELF_IMPROVE_SAMPLER_MAX_CANDIDATES,
)
from sevn.config.my_sevn import effective_my_sevn
from sevn.evolution.issues import create_issue
from sevn.self_improve.eval import ImproveJobResult, run_docker_eval_graph
from sevn.self_improve.jobs.events import ImproveJobEventFanoutFn, maybe_publish_job_event
from sevn.self_improve.jobs.store import (
    ImproveJobRow,
    claim_next_queued_job,
    update_job_state,
)
from sevn.self_improve.paths import job_bundle_dir
from sevn.self_improve.proposer.context_loader import write_context_pack
from sevn.self_improve.proposer.patch_author import (
    author_patch_from_shortlist,
    preset_requires_proposer,
    proposer_budget_exhausted,
    write_patch_artefacts,
)
from sevn.self_improve.sampler import ShortlistCandidate, allocate_shortlist
from sevn.self_improve.sampler.sources import load_sampler_candidates
from sevn.self_improve.spec_kit_stage import (
    improve_spec_kit_dir,
    plan_hitl_blocks_patch,
    run_improve_spec_kit_plan,
    spec_kit_plan_stage_enabled,
)
from sevn.self_improve.trace_events import emit_self_improve_trace
from sevn.self_improve.trajectories.runner import run_trajectory_ingest
from sevn.self_improve.types import ImproveJobId
from sevn.storage.paths import traces_sqlite_path

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from sevn.agent.tracing.sink import TraceSink
    from sevn.config.workspace_config import WorkspaceConfig
    from sevn.workspace.layout import WorkspaceLayout


class EvalGraphRunner(Protocol):
    """Callable surface for the improve evaluation graph."""

    def __call__(
        self,
        *,
        workspace: WorkspaceConfig,
        job_bundle: Path,
        repo_root: Path | None = None,
    ) -> ImproveJobResult:
        """Run eval segments and write ``eval_report.json`` under ``job_bundle``.

        Args:
            workspace (WorkspaceConfig): Active workspace configuration.
            job_bundle (Path): On-disk artefact directory for the job.
            repo_root (Path | None): Optional repository checkout root.

        Returns:
            ImproveJobResult: Aggregate segment outcomes for store wiring.

        Examples:
            >>> EvalGraphRunner.__name__
            'EvalGraphRunner'
        """
        ...


def _default_eval_runner(
    *,
    workspace: WorkspaceConfig,
    job_bundle: Path,
    repo_root: Path | None = None,
) -> ImproveJobResult:
    """Run the docker-aware eval graph on a worker thread.

    Args:
        workspace (WorkspaceConfig): Active workspace configuration.
        job_bundle (Path): On-disk artefact directory for the job.
        repo_root (Path | None): Optional repository checkout root.

    Returns:
        ImproveJobResult: Aggregate segment outcomes for store wiring.

    Examples:
        >>> _default_eval_runner.__name__
        '_default_eval_runner'
    """
    return run_docker_eval_graph(
        workspace=workspace,
        job_bundle=job_bundle,
        repo_root=repo_root,
    )


class ImproveJobWorker:
    """Process queued improve jobs through shortlist and eval stages."""

    def __init__(
        self,
        *,
        sqlite_conn: sqlite3.Connection,
        workspace_config: WorkspaceConfig,
        layout: WorkspaceLayout,
        workspace_id: str,
        job_event_fanout: ImproveJobEventFanoutFn | None = None,
        eval_runner: EvalGraphRunner | None = None,
        poll_interval_s: float = 2.0,
        repo_root: Path | None = None,
        trace_sink: TraceSink | None = None,
    ) -> None:
        """Bind runtime dependencies for the async worker loop.

        Args:
            sqlite_conn (sqlite3.Connection): Shared gateway database handle.
            workspace_config (WorkspaceConfig): Parsed ``sevn.json``.
            layout (WorkspaceLayout): Resolved filesystem layout.
            workspace_id (str): Scope key stored on ``self_improve_jobs`` rows.
            job_event_fanout (ImproveJobEventFanoutFn | None): Optional lifecycle publisher.
            eval_runner (EvalGraphRunner | None): Injectable eval graph for tests.
            poll_interval_s (float): Idle poll interval when no jobs are queued.
            repo_root (Path | None): Optional checkout root for golden corpus resolution.
            trace_sink (TraceSink | None): Optional gateway trace sink for §7 spans.

        Examples:
            >>> import sqlite3
            >>> from pathlib import Path
            >>> from sevn.config.workspace_config import WorkspaceConfig
            >>> from sevn.storage.migrate import apply_migrations
            >>> from sevn.workspace.layout import WorkspaceLayout
            >>> conn = sqlite3.connect(":memory:")
            >>> apply_migrations(conn)
            >>> ly = WorkspaceLayout(Path("/tmp/x/sevn.json"), Path("/tmp/x"))
            >>> ws = WorkspaceConfig.minimal(
            ...     self_improve={"enabled": True, "preset": "A"},
            ... )
            >>> worker = ImproveJobWorker(
            ...     sqlite_conn=conn,
            ...     workspace_config=ws,
            ...     layout=ly,
            ...     workspace_id="w",
            ... )
            >>> worker._poll_interval_s
            2.0
            >>> conn.close()
        """
        self._sqlite_conn = sqlite_conn
        self._workspace_config = workspace_config
        self._layout = layout
        self._workspace_id = workspace_id
        self._job_event_fanout = job_event_fanout
        self._eval_runner = eval_runner
        self._poll_interval_s = poll_interval_s
        self._repo_root = repo_root
        self._trace_sink = trace_sink
        self._wake = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    def schedule(self) -> None:
        """Wake the background loop to drain queued jobs soon.

        Returns:
            None: Side-effect only.

        Examples:
            >>> import inspect
            >>> inspect.isfunction(ImproveJobWorker.schedule)
            True
        """
        self._wake.set()

    async def start(self) -> None:
        """Start the background polling loop.

        Returns:
            None: Side-effect only.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(ImproveJobWorker.start)
            True
        """
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        """Cancel and join the background loop.

        Returns:
            None: Side-effect only.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(ImproveJobWorker.stop)
            True
        """
        task = self._task
        if task is None:
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        self._task = None

    async def process_once(self) -> bool:
        """Claim and process one queued job when present.

        Returns:
            bool: ``True`` when a job was claimed and driven through eval.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(ImproveJobWorker.process_once)
            True
        """
        row = claim_next_queued_job(
            self._sqlite_conn,
            workspace_id=self._workspace_id,
        )
        if row is None:
            return False
        await self._process_job(row)
        return True

    async def _loop(self) -> None:
        """Poll for queued jobs until cancelled.

        Returns:
            None: Runs until the background task is cancelled.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(ImproveJobWorker._loop)
            True
        """
        while True:
            try:
                processed = await self.process_once()
                if processed:
                    continue
                with suppress(TimeoutError):
                    await asyncio.wait_for(self._wake.wait(), timeout=self._poll_interval_s)
                self._wake.clear()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("improve_job_worker_loop_failed")

    async def _process_job(self, row: ImproveJobRow) -> None:
        """Drive one claimed job through shortlist, eval, and terminal state.

        Args:
            row (ImproveJobRow): Claimed job row in ``running`` state.

        Returns:
            None: Side-effect only.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(ImproveJobWorker._process_job)
            True
        """
        job_id = ImproveJobId(row.job_id)
        preset = row.preset
        correlation_id = row.correlation_id
        bundle = job_bundle_dir(self._layout, row.job_id)
        bundle.mkdir(parents=True, exist_ok=True)
        shortlist_path = bundle / "shortlist.json"
        patch_path = bundle / "patch" / "diff.patch"

        if shortlist_path.is_file():
            shortlist_payload = json.loads(shortlist_path.read_text(encoding="utf-8"))
            selected: list[ShortlistCandidate] = []
        else:
            self._ingest_trajectory_facts()
            selected, diagnostics = self._build_shortlist(sampler_seed=row.sampler_seed)
            shortlist_payload = {
                "schema_version": 1,
                "sampler_seed": row.sampler_seed,
                "candidates": [
                    {
                        "turn_id": c.turn_id,
                        "bucket": c.bucket,
                        "channel": c.channel,
                        "intent": c.intent,
                        "complexity_tier": c.complexity_tier,
                        "score": c.score,
                    }
                    for c in selected
                ],
                "diagnostics": diagnostics,
            }
            await asyncio.to_thread(
                shortlist_path.write_text,
                json.dumps(shortlist_payload, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            await asyncio.to_thread(
                write_context_pack,
                bundle,
                job_id=row.job_id,
                shortlist=shortlist_payload,
                layout=self._layout,
            )

        plan_md: str | None = None
        if preset_requires_proposer(preset) and spec_kit_plan_stage_enabled(self._workspace_config):
            plan_file = await asyncio.to_thread(
                run_improve_spec_kit_plan,
                job_id=row.job_id,
                job_bundle=bundle,
                ws=self._workspace_config,
                layout=self._layout,
                dry_run=True,
            )
            plan_md = str(plan_file)
            if await asyncio.to_thread(
                plan_hitl_blocks_patch,
                bundle,
                self._workspace_config,
            ):
                update_job_state(
                    self._sqlite_conn,
                    job_id=job_id,
                    state="awaiting_plan_review",
                    shortlist_path=str(shortlist_path),
                    blocked_reason="plan_hitl_required",
                )
                await maybe_publish_job_event(
                    self._job_event_fanout,
                    payload={
                        "job_id": row.job_id,
                        "state": "awaiting_plan_review",
                        "event": "transition",
                        "preset": preset,
                        "correlation_id": correlation_id,
                        "blocked_reason": "plan_hitl_required",
                    },
                )
                return

        if preset_requires_proposer(preset) and not patch_path.is_file():
            si = self._workspace_config.self_improve
            if (
                spec_kit_plan_stage_enabled(self._workspace_config)
                and not (improve_spec_kit_dir(bundle) / "plan.md").is_file()
            ):
                reason = "spec_kit_plan_missing"
                update_job_state(
                    self._sqlite_conn,
                    job_id=job_id,
                    state="blocked",
                    shortlist_path=str(shortlist_path),
                    blocked_reason=reason,
                )
                await maybe_publish_job_event(
                    self._job_event_fanout,
                    payload={
                        "job_id": row.job_id,
                        "state": "blocked",
                        "event": "transition",
                        "preset": preset,
                        "correlation_id": correlation_id,
                        "blocked_reason": reason,
                    },
                )
                return
            plan_path = (
                str(improve_spec_kit_dir(bundle) / "plan.md")
                if (improve_spec_kit_dir(bundle) / "plan.md").is_file()
                else plan_md
            )
            if proposer_budget_exhausted(self._workspace_config, self._layout):
                reason = "budget_exhausted"
                update_job_state(
                    self._sqlite_conn,
                    job_id=job_id,
                    state="blocked",
                    shortlist_path=str(shortlist_path),
                    blocked_reason=reason,
                )
                await maybe_publish_job_event(
                    self._job_event_fanout,
                    payload={
                        "job_id": row.job_id,
                        "state": "blocked",
                        "event": "transition",
                        "preset": preset,
                        "correlation_id": correlation_id,
                        "blocked_reason": reason,
                    },
                )
                await emit_self_improve_trace(
                    self._trace_sink,
                    job_id=row.job_id,
                    kind="self_improve.patch_rejected",
                    status="blocked",
                    attrs={"blocked_reason": reason, "preset": preset},
                )
                return
            patch_result = await author_patch_from_shortlist(
                job_id=row.job_id,
                shortlist=shortlist_payload,
                allowed_globs=si.allowed_globs if si else None,
                deny_globs=si.deny_globs if si else None,
                plan_md_path=plan_path,
                workspace=self._workspace_config,
                layout=self._layout,
                job_bundle=bundle,
                trace=self._trace_sink,
            )
            if not patch_result.ok:
                reason = patch_result.rejection or "patch_author_failed"
                update_job_state(
                    self._sqlite_conn,
                    job_id=job_id,
                    state="blocked",
                    shortlist_path=str(shortlist_path),
                    blocked_reason=reason,
                )
                await maybe_publish_job_event(
                    self._job_event_fanout,
                    payload={
                        "job_id": row.job_id,
                        "state": "blocked",
                        "event": "transition",
                        "preset": preset,
                        "correlation_id": correlation_id,
                        "blocked_reason": reason,
                    },
                )
                await emit_self_improve_trace(
                    self._trace_sink,
                    job_id=row.job_id,
                    kind="self_improve.patch_rejected",
                    status="blocked",
                    attrs={"blocked_reason": reason, "preset": preset},
                )
                return
            await asyncio.to_thread(write_patch_artefacts, bundle, patch_result)
            await emit_self_improve_trace(
                self._trace_sink,
                job_id=row.job_id,
                kind="self_improve.patch_ready",
                status="ok",
                attrs={
                    "preset": preset,
                    "target_path": patch_result.target_path or "",
                    "author": patch_result.author or "pydantic_agent",
                },
            )

        update_job_state(
            self._sqlite_conn,
            job_id=job_id,
            state="awaiting_eval",
            shortlist_path=str(shortlist_path),
        )
        await maybe_publish_job_event(
            self._job_event_fanout,
            payload={
                "job_id": row.job_id,
                "state": "awaiting_eval",
                "event": "transition",
                "preset": preset,
                "correlation_id": correlation_id,
                "shortlist_count": len(selected),
            },
        )

        runner = self._eval_runner or _default_eval_runner
        try:
            result = await asyncio.to_thread(
                runner,
                workspace=self._workspace_config,
                job_bundle=bundle,
                repo_root=self._repo_root,
            )
        except Exception:
            logger.exception("improve_job_eval_failed job_id={}", row.job_id)
            update_job_state(
                self._sqlite_conn,
                job_id=job_id,
                state="blocked",
                blocked_reason="eval_failed",
            )
            await maybe_publish_job_event(
                self._job_event_fanout,
                payload={
                    "job_id": row.job_id,
                    "state": "blocked",
                    "event": "transition",
                    "preset": preset,
                    "correlation_id": correlation_id,
                    "blocked_reason": "eval_failed",
                },
            )
            return

        eval_path = str(result.eval_report_path)
        if result.passed:
            update_job_state(
                self._sqlite_conn,
                job_id=job_id,
                state="awaiting_review",
                eval_report_path=eval_path,
            )
            await maybe_publish_job_event(
                self._job_event_fanout,
                payload={
                    "job_id": row.job_id,
                    "state": "awaiting_review",
                    "event": "transition",
                    "preset": preset,
                    "correlation_id": correlation_id,
                    "shortlist_count": len(selected),
                },
            )
            return

        update_job_state(
            self._sqlite_conn,
            job_id=job_id,
            state="blocked",
            eval_report_path=eval_path,
            blocked_reason="eval_failed",
        )
        await maybe_publish_job_event(
            self._job_event_fanout,
            payload={
                "job_id": row.job_id,
                "state": "blocked",
                "event": "transition",
                "preset": preset,
                "correlation_id": correlation_id,
                "blocked_reason": "eval_failed",
            },
        )
        await asyncio.to_thread(
            self._maybe_auto_file_issue,
            job_id=row.job_id,
            eval_report_path=eval_path,
        )

    def _ingest_trajectory_facts(self) -> None:
        """Best-effort ``trajectory_fact`` ingest from ``traces.db`` when present.

        Returns:
            None: Side-effect only.

        Examples:
            >>> ImproveJobWorker._ingest_trajectory_facts.__name__
            '_ingest_trajectory_facts'
        """
        traces_path = traces_sqlite_path(self._layout.dot_sevn)
        if not traces_path.is_file():
            return
        with suppress(Exception):
            run_trajectory_ingest(self._sqlite_conn, self._layout)

    def _maybe_auto_file_issue(self, *, job_id: str, eval_report_path: str) -> None:
        """Create a bug issue when ``my_sevn.issues.auto_file_on_failure`` is enabled.

        Args:
            job_id (str): Improve job id.
            eval_report_path (str): Path to the failed eval report.

        Returns:
            None: Side-effect only.

        Examples:
            >>> ImproveJobWorker._maybe_auto_file_issue.__name__
            '_maybe_auto_file_issue'
        """
        my = effective_my_sevn(self._workspace_config)
        issues_cfg = my.issues
        if issues_cfg is None or not issues_cfg.auto_file_on_failure:
            return
        title = f"Self-improve eval failed ({job_id})"
        body = f"Improve job `{job_id}` blocked after eval.\n\nReport: `{eval_report_path}`"
        with suppress(Exception):
            create_issue(
                self._layout,
                kind="bug",
                title=title,
                body=body,
                source="self_improve",
                ws=self._workspace_config,
            )

    def _build_shortlist(self, *, sampler_seed: int) -> tuple[list[ShortlistCandidate], list[str]]:
        """Allocate a shortlist from trajectory facts and feedback events.

        Args:
            sampler_seed (int): Deterministic seed persisted on the job row.

        Returns:
            tuple[list[ShortlistCandidate], list[str]]: Selected rows and diagnostics.

        Examples:
            >>> import sqlite3
            >>> from pathlib import Path
            >>> from sevn.config.workspace_config import WorkspaceConfig
            >>> from sevn.storage.migrate import apply_migrations
            >>> from sevn.workspace.layout import WorkspaceLayout
            >>> conn = sqlite3.connect(":memory:")
            >>> apply_migrations(conn)
            >>> ly = WorkspaceLayout(Path("/tmp/x/sevn.json"), Path("/tmp/x"))
            >>> ws = WorkspaceConfig.minimal(
            ...     self_improve={"enabled": True, "preset": "A"},
            ... )
            >>> worker = ImproveJobWorker(
            ...     sqlite_conn=conn,
            ...     workspace_config=ws,
            ...     layout=ly,
            ...     workspace_id="w",
            ... )
            >>> worker._build_shortlist(sampler_seed=1)[0] == []
            True
            >>> conn.close()
        """
        si = self._workspace_config.self_improve
        if si is None:
            return [], ["self_improve config missing"]
        sampler = si.sampler
        coverage = sampler.coverage if sampler and sampler.coverage else None
        max_candidates = (
            sampler.max_candidates if sampler else DEFAULT_SELF_IMPROVE_SAMPLER_MAX_CANDIDATES
        )
        explicit_floor = (
            sampler.explicit_feedback_floor_pct
            if sampler
            else DEFAULT_SELF_IMPROVE_EXPLICIT_FEEDBACK_FLOOR_PCT
        )
        per_channel_max = (
            coverage.per_channel_pct_max if coverage else DEFAULT_SELF_IMPROVE_PER_CHANNEL_PCT_MAX
        )
        per_intent_max = (
            coverage.per_intent_pct_max if coverage else DEFAULT_SELF_IMPROVE_PER_INTENT_PCT_MAX
        )
        per_tier_max = (
            coverage.per_tier_pct_max if coverage else DEFAULT_SELF_IMPROVE_PER_TIER_PCT_MAX
        )
        per_channel_min = (
            dict(coverage.per_channel_pct_min)
            if coverage
            else {"voice": DEFAULT_SELF_IMPROVE_PER_CHANNEL_PCT_MIN_VOICE}
        )
        pool = load_sampler_candidates(self._sqlite_conn, sampler_seed=sampler_seed)
        return allocate_shortlist(
            candidates=pool,
            max_candidates=max_candidates,
            explicit_feedback_floor_pct=explicit_floor,
            per_channel_pct_max=per_channel_max,
            per_intent_pct_max=per_intent_max,
            per_tier_pct_max=per_tier_max,
            per_channel_pct_min=per_channel_min,
        )


__all__ = ["EvalGraphRunner", "ImproveJobWorker"]
