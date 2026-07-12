"""SQLite façade wiring (`specs/33-self-improvement.md` §3.3)."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

from sevn.config.loader import load_workspace
from sevn.self_improve.facade import enqueue_improve_job
from sevn.self_improve.types import OwnerPrincipal
from sevn.storage.migrate import apply_migrations


def test_enqueue_is_idempotent_on_client_token(tmp_path: Path) -> None:
    sevn_json = tmp_path / "sevn.json"
    sevn_json.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "self_improve": {"enabled": True, "preset": "A"},
                "gateway": {"token": "${SECRET:keychain:sevn.gateway.token}"},
            }
        ),
        encoding="utf-8",
    )
    cfg, layout = load_workspace(sevn_json=sevn_json)
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    principal = OwnerPrincipal(principal_kind="owner", principal_id="me")
    tok = "dedupe-me"

    async def _run() -> tuple[str, str]:
        j1 = await enqueue_improve_job(
            workspace_id="ws",
            experiment_id="exp",
            trigger="manual",
            correlation_id=None,
            owner_principal=principal,
            workspace_config=cfg,
            layout=layout,
            sqlite_conn=conn,
            client_token=tok,
        )
        j2 = await enqueue_improve_job(
            workspace_id="ws",
            experiment_id="exp",
            trigger="manual",
            correlation_id=None,
            owner_principal=principal,
            workspace_config=cfg,
            layout=layout,
            sqlite_conn=conn,
            client_token=tok,
        )
        return j1, j2

    one, two = asyncio.run(_run())
    assert one == two
