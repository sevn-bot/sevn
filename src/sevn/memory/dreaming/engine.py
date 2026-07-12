"""Dreaming engine façade (`specs/31-memory-dreaming.md` §2.1).

Module: sevn.memory.dreaming.engine
Depends: asyncio, sqlite3, sevn.agent.tracing

Exports:
    DreamingEngine — async cron/CLI promotion pipeline.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
import uuid
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

from sevn.agent.tracing.sink import TraceEvent, TraceSink
from sevn.agent.triager.errors import TriagerUnavailable
from sevn.config.model_resolution import ModelSlot, resolve_model_slot
from sevn.config.workspace_config import WorkspaceConfig
from sevn.memory.dreaming.ack_policy import format_ack_required_trace_attrs
from sevn.memory.dreaming.backfill import iter_backfill_dates
from sevn.memory.dreaming.models import (
    DreamingCandidate,
    DreamingRunResult,
    PromotedBatchManifest,
    PromotionMode,
)
from sevn.memory.dreaming.promoter import (
    append_dreams_diary,
    build_run_result,
    dreams_dir,
    promote_auto_batch,
    write_candidate_snapshot,
    write_pending_files,
)
from sevn.memory.dreaming.review import format_run_summary
from sevn.memory.dreaming.rollback import latest_promoted_manifest
from sevn.memory.dreaming.rollback import rollback_last_auto_batch as rollback_impl
from sevn.memory.dreaming.scheduler import effective_dreaming
from sevn.memory.dreaming.scorer import build_candidates, maybe_llm_rerank
from sevn.memory.dreaming.sources import (
    load_daily_log_signals,
    load_lcm_summary_signals,
    load_memory_signals,
)
from sevn.memory.search_telemetry import load_recall_weights

if TYPE_CHECKING:
    from sevn.agent.providers.transport import Transport


def _lcm_summary_model(ws: WorkspaceConfig) -> str | None:
    """Return resolved LCM summary model id (unified main or ``lcm.summary_model``).

    Args:
        ws (WorkspaceConfig): Workspace root model.

    Returns:
        str | None: Summary model id or ``None`` when main triager is unset.

    Examples:
        >>> _lcm_summary_model(WorkspaceConfig.minimal()) is None
        True
    """
    try:
        return resolve_model_slot(ws, ModelSlot.lcm_summary)
    except TriagerUnavailable:
        return None


class DreamingEngine:
    """Cron-invoked promotion pipeline for one workspace (`specs/31-memory-dreaming.md` §2.1)."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        trace: TraceSink,
        memory_job_lock: asyncio.Lock,
        *,
        transport: Transport | None = None,
    ) -> None:
        """Attach SQLite, trace sink, and mutex shared with other memory jobs.

        Args:
            conn (sqlite3.Connection): Shared ``sevn.db`` handle.
            trace (TraceSink): Active trace sink.
            memory_job_lock (asyncio.Lock): Serialize heavy memory jobs.
            transport (Transport | None): Optional LLM transport for ranker.

        Examples:
            >>> import asyncio
            >>> import sqlite3
            >>> from sevn.agent.tracing.sink import NullTraceSink
            >>> eng = DreamingEngine(sqlite3.connect(":memory:"), NullTraceSink(), asyncio.Lock())
            >>> type(eng).__name__
            'DreamingEngine'
        """
        self._conn = conn
        self._trace = trace
        self._lock = memory_job_lock
        self._transport = transport

    async def run_scheduled(
        self, *, workspace_root: Path, ws: WorkspaceConfig
    ) -> DreamingRunResult | None:
        """Run one scheduled pass — no-op when disabled or mutex busy.

        Args:
            workspace_root (Path): Workspace filesystem root (``MEMORY.md`` host).
            ws (WorkspaceConfig): Parsed ``sevn.json``.

        Returns:
            DreamingRunResult | None: Structured outcome or ``None`` when skipped/disabled.

        Examples:
            >>> import asyncio
            >>> import inspect
            >>> inspect.iscoroutinefunction(DreamingEngine.run_scheduled)
            True
        """
        cfg = effective_dreaming(ws)
        if not cfg.enabled:
            return None
        if self._lock.locked():
            await self._emit_skip("mutex_busy", ws)
            return None
        async with self._lock:
            return await self._run_inner(
                workspace_root=workspace_root,
                ws=ws,
                backfill_days_hint=cfg.backfill_days,
                daily_range=None,
            )

    async def run_backfill(
        self,
        *,
        workspace_root: Path,
        ws: WorkspaceConfig,
        date_from: str | None,
        date_to: str | None,
        unbounded_acknowledged: bool,
    ) -> DreamingRunResult:
        """Replay daily logs through the scorer within bounds.

        Args:
            workspace_root (Path): Workspace filesystem root.
            ws (WorkspaceConfig): Parsed ``sevn.json``.
            date_from (str | None): Optional inclusive ISO date lower bound.
            date_to (str | None): Optional inclusive ISO date upper bound.
            unbounded_acknowledged (bool): Operator cost acknowledgement flag.

        Returns:
            DreamingRunResult: Structured run outcome.

        Raises:
            ValueError: When Dreaming is disabled or the date window is too wide.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(DreamingEngine.run_backfill)
            True
        """
        cfg = effective_dreaming(ws)
        if not cfg.enabled:
            msg = "memory.dreaming.enabled is false — enable Dreaming before backfill"
            raise ValueError(msg)
        start, end = iter_backfill_dates(
            date_from=date_from,
            date_to=date_to,
            default_days=cfg.backfill_days,
            workspace_root=workspace_root,
            unbounded_acknowledged=unbounded_acknowledged,
        )
        async with self._lock:
            return await self._run_inner(
                workspace_root=workspace_root,
                ws=ws,
                backfill_days_hint=cfg.backfill_days,
                daily_range=(start, end),
            )

    async def rollback_last_auto_batch(self, *, workspace_root: Path) -> None:
        """Restore ``MEMORY.md`` from latest auto manifest.

        Args:
            workspace_root (Path): Workspace filesystem root.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(DreamingEngine.rollback_last_auto_batch)
            True
        """
        manifest_path = await asyncio.to_thread(latest_promoted_manifest, workspace_root)
        await asyncio.to_thread(rollback_impl, workspace_root)
        rid = ""
        if manifest_path is not None:
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
                rid = str(data.get("run_id", ""))
            except (OSError, json.JSONDecodeError, ValueError):
                rid = ""
        await self._trace.emit(
            TraceEvent(
                kind="dreaming.rollback",
                span_id=str(uuid.uuid4()),
                parent_span_id=None,
                session_id="dreaming",
                turn_id="rollback",
                tier=None,
                ts_start_ns=time.time_ns(),
                ts_end_ns=time.time_ns(),
                status="ok",
                attrs={"run_id_rolled_back": rid, "rows_removed": 0},
            ),
        )

    async def _emit_skip(self, reason: str, ws: WorkspaceConfig) -> None:
        """Emit ``dreaming.skip`` when the mutex is unavailable.

        Args:
            reason (str): Machine-readable skip label.
            ws (WorkspaceConfig): Workspace for mode attrs.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(DreamingEngine._emit_skip)
            True
        """
        cfg = effective_dreaming(ws)
        await self._trace.emit(
            TraceEvent(
                kind="dreaming.skip",
                span_id=str(uuid.uuid4()),
                parent_span_id=None,
                session_id="dreaming",
                turn_id="scheduled",
                tier=None,
                ts_start_ns=time.time_ns(),
                ts_end_ns=time.time_ns(),
                status="skipped",
                attrs={"reason": reason, "mode": cfg.promotion_mode},
            ),
        )

    async def _run_inner(
        self,
        *,
        workspace_root: Path,
        ws: WorkspaceConfig,
        backfill_days_hint: int,
        daily_range: tuple[date, date] | None,
    ) -> DreamingRunResult:
        """Load signals, score, promote or queue, emit trace spans (`specs/31-memory-dreaming.md` §7).

        Args:
            workspace_root (Path): Workspace filesystem root.
            ws (WorkspaceConfig): Parsed ``sevn.json``.
            backfill_days_hint (int): Default depth for daily-log ingestion.
            daily_range (tuple[date, date] | None): Optional inclusive filter on daily logs.

        Returns:
            DreamingRunResult: Structured outcome (promotions, skips, ``MEMORY.md`` appendix).

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(DreamingEngine._run_inner)
            True
        """
        cfg = effective_dreaming(ws)
        run_id = str(uuid.uuid4())
        start = time.time_ns()
        mem = load_memory_signals(self._conn)
        lcm = load_lcm_summary_signals(self._conn)
        if daily_range is None:
            daily = load_daily_log_signals(workspace_root, max_files=max(1, backfill_days_hint))
        else:
            daily = load_daily_log_signals(
                workspace_root,
                max_files=3650,
                start=daily_range[0],
                end=daily_range[1],
            )
        raws = mem + lcm + daily
        recall_weights = load_recall_weights(self._conn)
        kept, eligible, skipped = build_candidates(raws, cfg, recall_weights=recall_weights)
        write_candidate_snapshot(workspace_root, run_id, kept)

        if cfg.scoring and cfg.scoring.llm_ranker and cfg.scoring.llm_ranker.enabled:
            eligible, ranker_err = await maybe_llm_rerank(
                eligible,
                dreaming=cfg,
                transport=self._transport,
                lcm_summary_model=_lcm_summary_model(ws),
                content_root=workspace_root,
            )
        else:
            ranker_err = False

        max_n = cfg.max_promotions_per_run
        over_cap = eligible[max_n:]
        selected = eligible[:max_n]
        for c in over_cap:
            skipped.append((c, "cap"))

        await self._trace.emit(
            TraceEvent(
                kind="dreaming.run_start",
                span_id=str(uuid.uuid4()),
                parent_span_id=None,
                session_id="dreaming",
                turn_id=run_id,
                tier=None,
                ts_start_ns=start,
                ts_end_ns=None,
                status="started",
                attrs={
                    "run_id": run_id,
                    "mode": cfg.promotion_mode,
                    "candidate_count": len(kept),
                    "backfill_days": backfill_days_hint,
                },
            ),
        )

        for c in selected:
            await self._trace.emit(
                TraceEvent(
                    kind="dreaming.score",
                    span_id=str(uuid.uuid4()),
                    parent_span_id=None,
                    session_id="dreaming",
                    turn_id=run_id,
                    tier=None,
                    ts_start_ns=time.time_ns(),
                    ts_end_ns=time.time_ns(),
                    status="ok",
                    attrs={
                        "candidate_id": c.candidate_id,
                        "topic": c.topic,
                        "score": c.score,
                        "threshold": cfg.threshold,
                        **{f"w_{k}": v for k, v in c.reasons.items()},
                    },
                ),
            )

        mode: PromotionMode = cfg.promotion_mode
        dreams_body: str
        manifest_path: Path
        promoted: list[DreamingCandidate] = []

        if mode == "auto":
            if selected:
                _append_text, manifest_path, manifest = promote_auto_batch(
                    workspace_root,
                    run_id=run_id,
                    mode=mode,
                    candidates=selected,
                )
                for c, row in zip(selected, manifest.rows, strict=True):
                    await self._trace.emit(
                        TraceEvent(
                            kind="dreaming.promote",
                            span_id=str(uuid.uuid4()),
                            parent_span_id=None,
                            session_id="dreaming",
                            turn_id=run_id,
                            tier=None,
                            ts_start_ns=time.time_ns(),
                            ts_end_ns=time.time_ns(),
                            status="ok",
                            attrs={
                                "candidate_id": c.candidate_id,
                                "memory_md_anchor": (
                                    f"L{row.memory_md_anchor.line_start}-"
                                    f"{row.memory_md_anchor.line_end}:"
                                    f"{row.memory_md_anchor.content_sha256[:12]}"
                                ),
                                "score": c.score,
                            },
                        ),
                    )
                promoted = list(selected)
            else:
                manifest_path = dreams_dir(workspace_root) / "promoted" / f"{run_id}.json"
                dreams_dir(workspace_root).joinpath("promoted").mkdir(parents=True, exist_ok=True)
                empty = PromotedBatchManifest(
                    run_id=run_id,
                    mode=mode,
                    memory_md_pre_bytes=len(
                        (workspace_root / "MEMORY.md").read_bytes(),
                    )
                    if (workspace_root / "MEMORY.md").is_file()
                    else 0,
                    memory_md_post_bytes=len(
                        (workspace_root / "MEMORY.md").read_bytes(),
                    )
                    if (workspace_root / "MEMORY.md").is_file()
                    else 0,
                    rows=[],
                )
                manifest_path.write_text(empty.model_dump_json(indent=2), encoding="utf-8")
            dreams_body = format_run_summary(
                run_id=run_id,
                promoted=promoted,
                skipped_count=len(skipped),
                llm_ranker_error=ranker_err,
            )
            if dreams_body:
                append_dreams_diary(workspace_root, run_id=run_id, body=dreams_body)
        else:
            n_pending = write_pending_files(workspace_root, run_id=run_id, candidates=selected)
            await self._trace.emit(
                TraceEvent(
                    kind="dreaming.promote",
                    span_id=str(uuid.uuid4()),
                    parent_span_id=None,
                    session_id="dreaming",
                    turn_id=run_id,
                    tier=None,
                    ts_start_ns=time.time_ns(),
                    ts_end_ns=time.time_ns(),
                    status="queued",
                    attrs=format_ack_required_trace_attrs(queued=n_pending),
                ),
            )
            promoted = []
            summary_path = dreams_dir(workspace_root) / "pending" / f"{run_id}_queue.json"
            dreams_dir(workspace_root).joinpath("pending").mkdir(parents=True, exist_ok=True)
            summary_path.write_text(
                json.dumps({"run_id": run_id, "queued": n_pending}, indent=2),
                encoding="utf-8",
            )
            manifest_path = summary_path
            dreams_body = format_run_summary(
                run_id=run_id,
                promoted=[],
                skipped_count=len(skipped),
                llm_ranker_error=ranker_err,
            )
            dreams_body = f"{dreams_body}\nqueued_pending_files: {n_pending}\n"
            append_dreams_diary(workspace_root, run_id=run_id, body=dreams_body)

        duration_ms = (time.time_ns() - start) / 1e6
        end_attrs: dict[str, object] = {
            "promoted_count": len(promoted),
            "skipped_count": len(skipped),
            "duration_ms": round(duration_ms, 3),
        }
        if ranker_err:
            end_attrs["llm_ranker_error"] = True
        await self._trace.emit(
            TraceEvent(
                kind="dreaming.run_end",
                span_id=str(uuid.uuid4()),
                parent_span_id=None,
                session_id="dreaming",
                turn_id=run_id,
                tier=None,
                ts_start_ns=time.time_ns(),
                ts_end_ns=time.time_ns(),
                status="ok" if not ranker_err else "degraded",
                attrs=end_attrs,
            ),
        )

        return build_run_result(
            run_id=run_id,
            mode=mode,
            promoted=promoted,
            skipped=skipped,
            dreams_md_append=dreams_body,
            promoted_manifest_path=manifest_path,
        )
