#!/usr/bin/env python3
"""Daily watchlist research + new-only briefing for cron/agent-pass.

Chains ``watchlist run-one`` (persists findings with URL dedup) then builds
briefing JSON from findings *first seen on this run* only — never re-shares
items already delivered on prior days.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from sevn.lcm.script_cli import write_error, write_ok

SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(SCRIPT_DIR))

import store
from watchlist import _run_topic


def _top_finding_payload(finding: dict) -> dict:
    source_url = finding.get("source_url", "")
    return {
        "title": finding.get("source_title", ""),
        "source": finding.get("source", ""),
        "source_url": source_url,
        "url": source_url,
        "author": finding.get("author", ""),
        "engagement": finding.get("engagement_score", 0),
        "content": (finding.get("content") or "")[:300],
    }


def build_digest_for_run(*, topic: dict, run_result: dict) -> dict:
    """Build briefing-shaped JSON for findings new in ``run_result['run_id']``."""
    run_id = run_result.get("run_id")
    if run_id is None:
        return {
            "status": "error",
            "message": "Watchlist run did not return run_id.",
        }

    if run_result.get("status") != "completed":
        return {
            "status": "failed",
            "message": run_result.get("error", "Watchlist research failed."),
            "run": run_result,
        }

    new_findings = store.get_findings_new_in_run(int(run_id))
    new_count = len(new_findings)
    updated_count = int(run_result.get("updated", 0))

    if new_count == 0:
        return {
            "status": "no_new",
            "message": (
                f'No new findings for "{topic["name"]}" '
                f"({updated_count} already-known items refreshed)."
            ),
            "run": run_result,
            "total_new": 0,
            "total_updated": updated_count,
        }

    top = max(new_findings, key=lambda f: f.get("engagement_score", 0))
    daily_cost = store.get_daily_cost()
    budget = float(store.get_setting("daily_budget", "5.00"))

    return {
        "status": "ok",
        "date": datetime.now(UTC).strftime("%Y-%m-%d"),
        "since": "this_run",
        "run": run_result,
        "topics": [
            {
                "name": topic["name"],
                "findings": new_findings,
                "new_count": new_count,
                "last_run": topic.get("last_run"),
                "last_status": "completed",
                "stale": False,
                "hours_ago": None,
                "top_finding": _top_finding_payload(top),
            }
        ],
        "total_new": new_count,
        "total_updated": updated_count,
        "total_topics": 1,
        "top_finding": {
            **_top_finding_payload(top),
            "topic": topic["name"],
        },
        "cost": {"daily": daily_cost, "budget": budget},
        "failed_topics": [],
    }


def run_topic(topic_name: str) -> dict:
    """Run watchlist research for one topic and return new-only digest data."""
    store.init_db()
    topic = store.get_topic(topic_name)
    if not topic:
        return {
            "status": "not_found",
            "message": (
                f'Watchlist topic not found: "{topic_name}". '
                f'Add with: watchlist.py add "{topic_name}"'
            ),
        }
    if not topic.get("enabled", True):
        return {
            "status": "no_enabled",
            "message": f'Watchlist topic "{topic_name}" is paused.',
        }

    run_result = _run_topic(topic)
    return build_digest_for_run(topic=topic, run_result=run_result)


def _emit(result: dict) -> int:
    status = str(result.get("status", "ok"))
    if status in {"not_found", "no_enabled", "error", "failed"}:
        write_error(
            code=status.upper(),
            error=str(result.get("message", status)),
        )
        return 1
    write_ok(result)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run watchlist research and emit new-only daily digest JSON",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser(
        "run",
        help="Research one watchlist topic and return only new findings",
    )
    run_parser.add_argument(
        "--topic",
        required=True,
        help="Watchlist topic name (must exist via watchlist.py add)",
    )

    args = parser.parse_args()
    if args.command == "run":
        raise SystemExit(_emit(run_topic(args.topic)))

    parser.print_help()
    raise SystemExit(1)


if __name__ == "__main__":
    main()
