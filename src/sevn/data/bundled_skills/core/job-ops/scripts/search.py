#!/usr/bin/env python3
"""Bundled ``job-ops`` skill — discover jobs across boards and persist them.

Runs the selected board extractors, normalizes + de-duplicates results, and stores
them in ``<content_root>/job-ops/jobs.jsonl``. Emits a single JSON envelope.
"""

from __future__ import annotations

import argparse

from sevn.lcm.script_cli import write_error, write_ok

from lib.extractors import registry
from lib.models import SearchQuery
from lib.settings import get_logger
from lib.store import JobStore

_WORKPLACE_CHOICES = ("remote", "hybrid", "onsite")


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def main(argv: list[str] | None = None) -> int:
    """Run selected extractors and persist normalized jobs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", required=True, help="Comma-separated search terms.")
    parser.add_argument(
        "--sources",
        default="",
        help="Comma-separated board ids (default: all). See --list-sources.",
    )
    parser.add_argument("--country", default="", help="Country hint (e.g. 'united kingdom').")
    parser.add_argument("--locations", default="", help="Comma-separated city/region filters.")
    parser.add_argument(
        "--workplace-types",
        default="",
        help=f"Comma-separated subset of {_WORKPLACE_CHOICES}.",
    )
    parser.add_argument(
        "--results-wanted", type=int, default=50, help="Max jobs per term per board."
    )
    parser.add_argument("--hours-old", type=int, default=168, help="Freshness window (jobspy).")
    parser.add_argument("--remote", action="store_true", help="Prefer remote roles.")
    parser.add_argument("--list-sources", action="store_true", help="List board ids and exit.")
    args = parser.parse_args(argv)

    log = get_logger()

    if args.list_sources:
        write_ok({"sources": registry.available_sources()})
        return 0

    workplace_types = [w for w in _split_csv(args.workplace_types) if w in _WORKPLACE_CHOICES]
    query = SearchQuery(
        search_terms=_split_csv(args.query),
        country=args.country.strip(),
        locations=_split_csv(args.locations),
        workplace_types=workplace_types,
        results_wanted=max(1, args.results_wanted),
        hours_old=max(1, args.hours_old),
        is_remote=bool(args.remote),
    )

    selected = _split_csv(args.sources) or registry.available_sources()
    unknown = [s for s in selected if registry.get_extractor(s) is None]
    if unknown:
        write_error(
            code="VALIDATION_ERROR",
            error=f"unknown sources: {', '.join(unknown)}; available: {', '.join(registry.available_sources())}",
        )
        return 1

    per_source: list[dict[str, object]] = []
    challenges: list[dict[str, str]] = []
    all_jobs = []
    for source in selected:
        run_fn = registry.get_extractor(source)
        if run_fn is None:
            continue
        log.info("running extractor {}", source)
        result = run_fn(query)
        per_source.append(
            {
                "source": source,
                "success": result.success,
                "found": len(result.jobs),
                "error": result.error,
            }
        )
        if result.challenge_required:
            challenges.append({"source": source, "url": result.challenge_required})
        all_jobs.extend(result.jobs)

    store = JobStore()
    added, updated = store.upsert_many(all_jobs)

    write_ok(
        {
            "sources_run": selected,
            "per_source": per_source,
            "discovered": len(all_jobs),
            "added": added,
            "updated": updated,
            "challenges": challenges,
            "store": str(store.jobs_path),
        },
        message=f"discovered {len(all_jobs)} jobs ({added} new, {updated} updated)",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
