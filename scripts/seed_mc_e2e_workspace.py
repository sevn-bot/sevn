#!/usr/bin/env python3
"""Seed trace + secrets fixtures for Mission Control E2E (MC W2).

Module: scripts.seed_mc_e2e_workspace
Depends: sevn.agent.tracing.traces_migrate, sevn.cli.workspace, sevn.config.workspace_config,
    sevn.security.secrets.backends.encrypted_file, sevn.self_improve.trajectories.ingest,
    sevn.storage.paths, sevn.ui.dashboard.query.traces, sevn.workspace.layout

Exports:
    main — create ``.sevn/traces.db`` row + encrypted store entry under the MC workspace.
    resolve_mc_e2e_workspace — resolve active workspace from ``SEVN_MC_WORKSPACE`` or fixture.
    is_fixture_mc_workspace — whether the path is the committed E2E fixture tree.
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
from pathlib import Path

from sevn.cli.workspace import operator_home_from_sevn_json
from sevn.config.workspace_config import WorkspaceConfig
from sevn.security.secrets.backends.encrypted_file import EncryptedFileBackend
from sevn.security.secrets.factory import parse_optional_master_key_hex
from sevn.self_improve.trajectories.ingest import ingest_trajectory_facts_from_traces
from sevn.storage.migrate import apply_migrations
from sevn.storage.paths import traces_sqlite_path
from sevn.ui.dashboard.query.traces import ensure_trace_connection
from sevn.workspace.layout import WorkspaceLayout

_FIXTURE_WORKSPACE = (
    Path(__file__).resolve().parent.parent / "infra" / "e2e-mission-control-workspace"
)
_DEFAULT_MASTER_KEY = "cc" * 32
_FIXTURE_ALIAS = "e2e.fixture.key"
_FIXTURE_VALUE = "mc-e2e-fixture-secret"
_DATA_PATH_PROVIDER_SPAN = "e2e-mc-provider-call-1"
_DATA_PATH_TRIAGE_SPAN = "e2e-mc-triage-complete-1"
_DATA_PATH_EXPERIMENT_ID = "e2e-mc-experiment"
_DATA_PATH_IMPROVE_CLIENT_TOKEN = "mc-e2e-data-path-improve"


def resolve_mc_e2e_workspace() -> Path:
    """Resolve the Mission Control E2E workspace directory.

    Uses ``SEVN_MC_WORKSPACE`` when set (directory containing ``sevn.json``);
    otherwise the committed fixture under ``infra/e2e-mission-control-workspace/``.

    Returns:
        Path: Absolute workspace content root.

    Examples:
        >>> resolve_mc_e2e_workspace().name
        'e2e-mission-control-workspace'
    """
    override = os.environ.get("SEVN_MC_WORKSPACE")
    if not override:
        return _FIXTURE_WORKSPACE.resolve()
    candidate = Path(override).expanduser().resolve()
    if candidate.is_file() and candidate.name == "sevn.json":
        return candidate.parent
    if (candidate / "sevn.json").is_file():
        return candidate
    msg = f"SEVN_MC_WORKSPACE does not contain sevn.json: {candidate}"
    raise SystemExit(msg)


def is_fixture_mc_workspace(workspace: Path) -> bool:
    """Return whether ``workspace`` is the committed MC E2E fixture tree.

    Args:
        workspace (Path): Resolved workspace content root.

    Returns:
        bool: ``True`` when ``workspace`` matches the fixture path.

    Examples:
        >>> is_fixture_mc_workspace(_FIXTURE_WORKSPACE.resolve())
        True
    """
    return workspace.resolve() == _FIXTURE_WORKSPACE.resolve()


def _load_workspace(workspace: Path) -> tuple[Path, WorkspaceConfig, WorkspaceLayout]:
    """Load workspace config and layout from ``workspace/sevn.json``.

    Args:
        workspace (Path): Workspace content root containing ``sevn.json``.

    Returns:
        tuple[Path, WorkspaceConfig, WorkspaceLayout]: Config path, parsed config, layout.

    Examples:
        >>> _load_workspace(_FIXTURE_WORKSPACE)  # doctest: +SKIP
    """
    sevn_json = workspace / "sevn.json"
    raw = json.loads(sevn_json.read_text(encoding="utf-8"))
    cfg = WorkspaceConfig.model_validate(raw)
    layout = WorkspaceLayout.from_config(sevn_json, cfg)
    return sevn_json, cfg, layout


def _seed_traces(layout: WorkspaceLayout) -> None:
    """Insert one deterministic trace row when ``traces.db`` is empty or missing the fixture.

    Args:
        layout (WorkspaceLayout): Resolved workspace layout for the MC E2E tree.

    Examples:
        >>> _seed_traces(WorkspaceLayout.from_config(  # doctest: +SKIP
        ...     Path("/tmp/sevn.json"), WorkspaceConfig.minimal(),
        ... ))
    """
    db_path = traces_sqlite_path(layout.dot_sevn)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    traces = ensure_trace_connection(db_path)
    try:
        row = traces.execute(
            "SELECT span_id FROM trace_events WHERE span_id = ?",
            ("e2e-mc-span-1",),
        ).fetchone()
        if row is None:
            traces.execute(
                """
                INSERT INTO trace_events (
                    span_id, parent_span_id, session_id, turn_id, tier, kind,
                    ts_start_ns, ts_end_ns, status, attrs_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "e2e-mc-span-1",
                    None,
                    "e2e-mc-session",
                    "e2e-mc-turn",
                    "B",
                    "b_turn",
                    1,
                    2,
                    "ok",
                    "{}",
                ),
            )
            traces.commit()
    finally:
        traces.close()


def _seed_data_path_traces(traces: sqlite3.Connection) -> None:
    """Emit ``provider.call`` + ``triage.complete`` spans for data-path E2E (opt-in).

    Default fixture seed keeps budget/trajectories empty (E0 negative baseline).
    Set ``SEVN_MC_DATA_PATH_SEED=1`` before ``make mc-e2e`` once dev_eval emit paths
    land (E1/E2 positive assertions).

    Args:
        traces (sqlite3.Connection): Open ``traces.db`` connection.

    Examples:
        >>> _seed_data_path_traces(sqlite3.connect(":memory:"))  # doctest: +SKIP
    """
    from sevn.agent.tracing.provider_call import emit_provider_call

    provider_row = traces.execute(
        "SELECT span_id FROM trace_events WHERE span_id = ?",
        (_DATA_PATH_PROVIDER_SPAN,),
    ).fetchone()
    if provider_row is None:
        db_row = traces.execute("PRAGMA database_list").fetchone()
        db_path = Path(str(db_row[2])) if db_row and db_row[2] else None

        async def _emit(path: Path) -> None:
            from sevn.agent.tracing import SQLiteSink

            sink = SQLiteSink(path)
            await emit_provider_call(
                sink,
                span_id=_DATA_PATH_PROVIDER_SPAN,
                parent_span_id=None,
                session_id="e2e-mc-session",
                turn_id="e2e-mc-turn",
                model_id="anthropic/claude-sonnet-4-6",
                regime="SUBSCRIPTION",
                tokens_in=42,
                tokens_out=21,
                transport="anthropic",
                tier="B",
                status="ok",
                ts_start_ns=10,
                ts_end_ns=20,
            )
            await sink.close()

        if db_path is not None:
            asyncio.run(_emit(db_path))
    triage_row = traces.execute(
        "SELECT span_id FROM trace_events WHERE span_id = ?",
        (_DATA_PATH_TRIAGE_SPAN,),
    ).fetchone()
    if triage_row is None:
        traces.execute(
            """
            INSERT INTO trace_events (
                span_id, parent_span_id, session_id, turn_id, tier, kind,
                ts_start_ns, ts_end_ns, status, attrs_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _DATA_PATH_TRIAGE_SPAN,
                None,
                "e2e-mc-session",
                "e2e-mc-turn",
                "B",
                "triage.complete",
                5,
                9,
                "ok",
                json.dumps(
                    {
                        "intent": "chat",
                        "complexity": "B",
                        "budget_regime": "SUBSCRIPTION",
                        "model_id": "anthropic/claude-sonnet-4-6",
                    },
                ),
            ),
        )
    traces.commit()


def _seed_data_path_improve_job(
    layout: WorkspaceLayout,
    conn: sqlite3.Connection,
    *,
    workspace_id: str,
) -> None:
    """Persist one improve job + eval report via store APIs (E2 experiments data-path).

    Args:
        layout (WorkspaceLayout): Resolved workspace layout for job bundle paths.
        conn (sqlite3.Connection): Open ``sevn.db`` connection with migrations applied.
        workspace_id (str): Dashboard workspace scope key (fixture uses ``"."``).

    Examples:
        >>> _seed_data_path_improve_job(  # doctest: +SKIP
        ...     WorkspaceLayout.from_config(Path("/tmp/sevn.json"), WorkspaceConfig.minimal()),
        ...     sqlite3.connect(":memory:"),
        ...     workspace_id=".",
        ... )
    """
    from sevn.self_improve.jobs.store import enqueue_job_row, update_job_state

    job_id = enqueue_job_row(
        conn,
        workspace_id=workspace_id,
        experiment_id=_DATA_PATH_EXPERIMENT_ID,
        preset="A",
        sampler_seed=42,
        correlation_id=None,
        client_token=_DATA_PATH_IMPROVE_CLIENT_TOKEN,
        experiment_snapshot={"experiment_id": _DATA_PATH_EXPERIMENT_ID},
    )
    bundle_dir = layout.dot_sevn / "improve" / "jobs" / str(job_id)
    bundle_dir.mkdir(parents=True, exist_ok=True)
    report_path = bundle_dir / "eval_report.json"
    report_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "passed": True,
                "segments": [
                    {
                        "name": "fixture",
                        "status": "passed",
                        "detail": "mc-e2e data-path seed",
                    },
                ],
            },
        ),
        encoding="utf-8",
    )
    update_job_state(
        conn,
        job_id=job_id,
        state="awaiting_review",
        eval_report_path=str(report_path),
    )


def _seed_data_path_fixtures(layout: WorkspaceLayout, *, workspace_id: str) -> None:
    """Opt-in provider.call + trajectory ingest for Mission Control data-path specs.

    Args:
        layout (WorkspaceLayout): Resolved workspace layout for the MC E2E tree.
        workspace_id (str): Dashboard workspace scope key for improve-job rows.

    Examples:
        >>> _seed_data_path_fixtures(  # doctest: +SKIP
        ...     WorkspaceLayout.from_config(Path("/tmp/sevn.json"), WorkspaceConfig.minimal()),
        ...     workspace_id=".",
        ... )
    """
    if os.environ.get("SEVN_MC_DATA_PATH_SEED") != "1":
        return
    db_path = traces_sqlite_path(layout.dot_sevn)
    traces = ensure_trace_connection(db_path)
    try:
        _seed_data_path_traces(traces)
    finally:
        traces.close()
    sevn_db = layout.dot_sevn / "sevn.db"
    sevn_db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(sevn_db)
    try:
        apply_migrations(conn)
        ingest_trajectory_facts_from_traces(conn, db_path)
        _seed_data_path_improve_job(layout, conn, workspace_id=workspace_id)
        conn.commit()
    finally:
        conn.close()


def _seed_secrets(cfg: WorkspaceConfig, layout: WorkspaceLayout) -> None:
    """Upsert the encrypted-store fixture alias used by read-only Secrets tab specs.

    Args:
        cfg (WorkspaceConfig): Parsed MC E2E workspace config.
        layout (WorkspaceLayout): Resolved workspace layout for store path resolution.

    Examples:
        >>> _seed_secrets(WorkspaceConfig.minimal(), WorkspaceLayout.from_config(  # doctest: +SKIP
        ...     Path("/tmp/sevn.json"), WorkspaceConfig.minimal(),
        ... ))
    """
    os.environ.setdefault("SEVN_SECRETS_MASTER_KEY", _DEFAULT_MASTER_KEY)
    master_key = parse_optional_master_key_hex()
    if master_key is None:
        return
    chain = cfg.secrets_backend
    if chain is None or not chain.chain:
        return
    entry = chain.chain[0]
    store_path = layout.content_root / str(entry.path)
    store_path.parent.mkdir(parents=True, exist_ok=True)
    backend = EncryptedFileBackend(store_path, master_key=master_key, passphrase=None)

    async def _upsert() -> None:
        existing = await backend.get(_FIXTURE_ALIAS)
        if existing != _FIXTURE_VALUE:
            await backend.set(_FIXTURE_ALIAS, _FIXTURE_VALUE)

    asyncio.run(_upsert())


def _seed_gateway_sqlite(layout: WorkspaceLayout) -> None:
    """Ensure gateway sqlite exists so dashboard boot does not fail on first run.

    Args:
        layout (WorkspaceLayout): Resolved workspace layout for ``.sevn/gateway.db``.

    Examples:
        >>> from pathlib import Path
        >>> from sevn.config.workspace_config import WorkspaceConfig
        >>> from sevn.workspace.layout import WorkspaceLayout
        >>> cfg = WorkspaceConfig.minimal()
        >>> lay = WorkspaceLayout.from_config(Path("/tmp/sevn.json"), cfg)
        >>> _seed_gateway_sqlite(lay)  # doctest: +SKIP
    """
    db_path = layout.dot_sevn / "gateway.db"
    if db_path.exists():
        return
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.commit()
    finally:
        conn.close()


def main() -> None:
    """Write minimal trace + secrets fixtures for the active MC E2E workspace.

    Seeds the fixture workspace by default. For operator workspaces
    (``SEVN_MC_WORKSPACE`` pointing outside the fixture tree), seeding is
    skipped unless ``SEVN_MC_SEED=1`` is set explicitly.

    Examples:
        >>> main()  # doctest: +SKIP
    """
    workspace = resolve_mc_e2e_workspace()
    if not is_fixture_mc_workspace(workspace) and os.environ.get("SEVN_MC_SEED") != "1":
        home = operator_home_from_sevn_json(workspace / "sevn.json")
        print(
            f"[mc-e2e-seed] skipping operator workspace {workspace} "
            f"(SEVN_HOME={home}); set SEVN_MC_SEED=1 to seed fixtures",
            file=sys.stderr,
        )
        return

    _sevn_json, cfg, layout = _load_workspace(workspace)
    layout.dot_sevn.mkdir(parents=True, exist_ok=True)
    _seed_gateway_sqlite(layout)
    _seed_traces(layout)
    _seed_data_path_fixtures(layout, workspace_id=str(cfg.workspace_root or "."))
    _seed_secrets(cfg, layout)
    print(f"[mc-e2e-seed] seeded {workspace}", file=sys.stderr)


if __name__ == "__main__":
    main()
