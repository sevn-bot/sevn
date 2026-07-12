"""Self-improve CLI hooks (`specs/33-self-improvement.md` §2.3).

Module: sevn.cli.commands.improve_cmd
Depends: json, os, pathlib, typer, sevn.cli.workspace, sevn.self_improve.*

Exports:
    register — attach ``sevn improve`` subtree to the root Typer app.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import typer

from sevn.cli.workspace import load_bound_workspace
from sevn.self_improve.effective import effective_self_improve_enabled
from sevn.self_improve.lessons.io import append_jsonl_locked
from sevn.self_improve.paths import improve_root
from sevn.self_improve.sampler import ShortlistCandidate, allocate_shortlist


def register(app: typer.Typer) -> None:
    """Attach ``sevn improve`` subtree to ``app``.

    Args:
        app (typer.Typer): Root Typer application.

    Examples:
        >>> register(typer.Typer()) is None
        True
    """
    imp = typer.Typer(
        help="Inspect and drive the self-improvement sampler loop (Mission Control parity)."
    )
    app.add_typer(imp, name="improve")

    @imp.command("doctor")
    def improve_doctor(
        json_out: bool = typer.Option(
            False,
            "--json",
            help="Emit a JSON diagnostic object on stdout instead of human-readable lines.",
        ),
    ) -> None:
        """Print config/env posture for Mission Control parity checks."""
        bw = load_bound_workspace()
        ws = bw.config
        si = ws.self_improve
        hub_repo = ""
        if si and si.hub:
            hub_repo = (si.hub.repo or "").strip()
        preset = si.preset if si else "A"
        hub_ok = True
        if si and si.enabled and preset in ("B", "C"):
            hub_ok = bool(hub_repo)
        payload = {
            "effective_enabled": effective_self_improve_enabled(ws),
            "config_enabled": bool(si and si.enabled),
            "preset": preset,
            "hub_repo_configured": hub_ok,
            "hub_repo_non_empty": bool(hub_repo),
            "env_disable_self_improve": os.environ.get("SEVN_DISABLE_SELF_IMPROVE", "").strip()
            == "1",
        }
        if json_out:
            typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        else:
            for key in sorted(payload.keys()):
                typer.echo(f"{key}: {payload[key]}")

    @imp.command("replay-sampler")
    def improve_replay_sampler(
        fixture: Path = typer.Option(
            ...,
            "--fixture",
            help="JSON payload with candidates + allocator parameters (see tests/fixtures/self_improve/).",
            exists=True,
            dir_okay=False,
            file_okay=True,
            readable=True,
        ),
    ) -> None:
        """Deterministically replay a frozen candidate pool (developer / golden aid)."""
        data = json.loads(fixture.read_text(encoding="utf-8"))
        raw_cands = data["candidates"]
        cands: list[ShortlistCandidate] = []
        for row in raw_cands:
            sig = row.get("signals")
            cands.append(
                ShortlistCandidate(
                    turn_id=str(row["turn_id"]),
                    bucket=row["bucket"],
                    channel=str(row["channel"]),
                    intent=row.get("intent"),
                    complexity_tier=row.get("complexity_tier"),
                    score=float(row.get("score", 0.0)),
                    signals=sig if isinstance(sig, dict) else None,
                ),
            )
        selected, diagnostics = allocate_shortlist(
            candidates=cands,
            max_candidates=int(data["max_candidates"]),
            explicit_feedback_floor_pct=float(data["explicit_feedback_floor_pct"]),
            per_channel_pct_max=float(data["per_channel_pct_max"]),
            per_intent_pct_max=float(data["per_intent_pct_max"]),
            per_tier_pct_max=float(data["per_tier_pct_max"]),
            per_channel_pct_min={
                str(k): float(v) for k, v in dict(data.get("per_channel_pct_min") or {}).items()
            }
            or None,
        )
        typer.echo(
            json.dumps(
                {
                    "shortlist_turn_ids": [c.turn_id for c in selected],
                    "diagnostics": diagnostics,
                    "count": len(selected),
                },
                indent=2,
                sort_keys=True,
            ),
        )

    @imp.command("learn")
    def improve_learn(
        claim: str = typer.Argument(..., help="Short structured claim text."),
        rationale: str = typer.Option(..., "--rationale", help="Operator rationale string."),
    ) -> None:
        """Append one ``CandidateLesson`` row for downstream graduation pipelines."""
        bw = load_bound_workspace()
        root = improve_root(bw.layout)
        append_jsonl_locked(
            root / "candidate_lessons.jsonl",
            {
                "claim": claim,
                "rationale": rationale,
                "created_at": datetime.now(tz=UTC).isoformat(),
                "schema_version": 1,
            },
        )
        typer.echo("appended candidate_lessons.jsonl")
