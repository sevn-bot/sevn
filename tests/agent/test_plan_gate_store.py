"""Tests for C/D PlanGate persistence helpers."""

from __future__ import annotations

import sqlite3

import pytest

from sevn.agent.executors.cd_types import Plan, PlanStep
from sevn.agent.executors.plan_gate_store import (
    expire_pending_plans,
    store_pending_plan,
    supersede_pending_plan,
)
from sevn.storage.migrate import apply_migrations


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    return conn


def _plan() -> Plan:
    return Plan(
        steps=[PlanStep(id="1", title="review")],
        summary="review changes",
        meta=Plan.Meta(complexity="C", registry_version=1),
    )


def test_store_pending_plan_rejects_duplicate_active_turn() -> None:
    conn = _db()
    store_pending_plan(
        conn,
        session_id="s",
        turn_id="t",
        plan=_plan(),
        c_d_backend="dspy",
        now_ns=1,
    )
    with pytest.raises(sqlite3.IntegrityError):
        store_pending_plan(
            conn,
            session_id="s",
            turn_id="t",
            plan=_plan(),
            c_d_backend="lambda_rlm",
            now_ns=2,
        )


def test_expire_and_supersede_pending_plans() -> None:
    conn = _db()
    first = store_pending_plan(
        conn,
        session_id="s1",
        turn_id="t1",
        plan=_plan(),
        c_d_backend="dspy",
        now_ns=1,
        ttl_seconds=1,
    )
    second = store_pending_plan(
        conn,
        session_id="s2",
        turn_id="t2",
        plan=_plan(),
        c_d_backend="dspy",
        now_ns=1,
        ttl_seconds=100,
    )
    assert expire_pending_plans(conn, now_ns=first.expires_at_ns) == 1
    assert supersede_pending_plan(conn, session_id="s2", turn_id="t2", now_ns=3) == 1
    rows = dict(conn.execute("SELECT plan_id, status FROM pending_plans").fetchall())
    assert rows[first.plan_id] == "expired"
    assert rows[second.plan_id] == "superseded"
