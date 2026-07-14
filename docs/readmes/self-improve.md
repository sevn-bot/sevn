<!-- curated: hand-authored; after source changes review the body, then run `sevn readme fingerprint self-improve` -->
# Self-improvement — Self-upgrade harness, eval workers, spec-kit stages, and improve jobs

[![Spec][spec-badge]][spec-link]
[![Source][source-badge]][source-link]
[![Index][index-badge]][index-link]

> **Summary.** Self-upgrade harness, eval workers, spec-kit stages, and improve jobs.

## Level 1 — Overview (non-technical)

**Self-improvement** is an **opt-in, offline loop** — separate from the live message turn spine. When enabled, sevn periodically (or on demand) collects signals from past turns, proposes bounded harness fixes, runs automated checks, and waits for **your approval** before anything lands in workspace prompts or skills.

The loop in plain language:

1. **Collect** — Gateway tracing and explicit feedback (thumbs-down, structured notes) are ingested into trajectory facts.
2. **Shortlist** — A deterministic sampler picks representative failure turns with coverage caps across channel, intent, and tier.
3. **Propose** (presets B/C only) — An optional spec-kit plan stage may run first; then a patch author drafts a diff limited to allowed globs (prompts/skills by default).
4. **Evaluate** — Golden routing replay and/or a Docker eval graph must pass before promotion.
5. **Approve** — Jobs stop at **awaiting review** until you approve in Mission Control (or Telegram copy points you there). Preset C can auto-merge only when explicitly configured **and** eval passed.

Default is **off** (preset A observe-only is the safe starting point). Nothing silently rewrites your workspace.

## Level 2 — How it works (technical)

Self-improve runs as a **background async worker** (`ImproveJobWorker`) inside the gateway process — not inline on each channel message. The gateway turn spine still handles live chat; improve jobs are enqueued via cron, Mission Control, or `/improve` and processed from `self_improve_jobs` in `sevn.db`.

### Presets A / B / C

| Preset | Sampler + shortlist | Patch author | Post-eval promotion |
| --- | --- | --- | --- |
| **A** | Yes | Skipped | N/A (observe / calibrate) |
| **B** | Yes | Yes (propose-only) | Stops at `awaiting_review` — operator must approve merge |
| **C** | Yes | Yes | May auto-merge when `auto_merge_enabled` **and** eval passed (see audit below) |

### Job states

Typical happy path: `queued` → `running` → (`awaiting_plan_review` when spec-kit HITL is on) → `awaiting_eval` → `awaiting_review` on eval pass, or `blocked` / `aborted` on failure or operator kill.

Terminal states include `merged` (promotion complete) and `aborted` (operator or kill switch).

### Pipeline stages (`src/sevn/self_improve/jobs/worker.py`)

1. **Trajectory ingest** — `_ingest_trajectory_facts()` reads `traces.db` via `run_trajectory_ingest` (also scheduled per-turn and by cron).
2. **Sampler** — `load_sampler_candidates` + `allocate_shortlist` write `shortlist.json` and `context_pack.json` under the job bundle.
3. **Spec-kit plan** (optional) — `run_improve_spec_kit_plan` when `self_improve.spec_kit.enabled` and `require_plan_before_patch`; HITL pauses at `awaiting_plan_review` until `plan_approved` marker exists.
4. **Patch author** (presets B/C) — `author_patch_from_shortlist` enforces glob/policy gates and daily token budget; writes `patch/diff.patch`.
5. **Eval graph** — `run_docker_eval_graph` writes `eval_report.json`; failures → `blocked` with `eval_failed`.
6. **Review gate** — Eval pass → `awaiting_review`; no automatic workspace write in the worker today.

### Kill switches and effective enablement

| Control | Effect |
| --- | --- |
| `self_improve.enabled: false` (default) | Subsystem off |
| `SEVN_DISABLE_SELF_IMPROVE=1` | Forces off regardless of `sevn.json` (`effective_self_improve_enabled`) |
| `SEVN_DISABLE_AUTO_MERGE` | Documented in schema; **not yet wired** in runtime (see audit) |
| [`abort_improve_job`](../../src/sevn/self_improve/facade.py#L547) / dashboard abort | Facade + store transition exist; **no** live Mission Control, Telegram, or CLI caller wires it today (Telegram only renders `si:abort:` copy in [`self_improve_copy.py`](../../src/sevn/channels/self_improve_copy.py)) |

### Configuration (`sevn.json` → `self_improve`)

Key knobs (full schema: `infra/sevn.schema.json`):

- `enabled`, `preset` (`A`/`B`/`C`)
- `auto_merge_enabled`, `require_human_approval`
- `allowed_globs` / `deny_globs`, `allow_dependency_changes`, `allow_config_changes`, `allow_lcm_memory_changes`
- `sampler.*` (coverage caps, `max_candidates`, `explicit_feedback_floor_pct`)
- `jobs.max_concurrent_writers`
- `eval.docker_required`, `eval.in_process_override`
- `spec_kit.enabled`, `require_plan_before_patch`, `require_hitl_for_plan`
- `trajectories.ingest_on_turn`, `trajectories.ingest_cron`
- `hub.repo` (required for presets B/C)
- `export.enabled`, `export.ttl_days`

Validate after edits: `sevn config validate`; `sevn doctor` for layout hints.

### Artefact paths (under `.sevn/improve/`)

| Path | Contents |
| --- | --- |
| `<job_id>/shortlist.json` | Sampler output + diagnostics |
| `<job_id>/context_pack.json` | Context for spec-kit / patch author |
| `<job_id>/spec-kit/plan.md` | Optional plan stage output |
| `<job_id>/spec-kit/plan_approved` | HITL marker after MC approval |
| `<job_id>/patch/diff.patch` | Proposed unified diff |
| `<job_id>/eval_report.json` | Eval graph outcome |
| `self_improve_audit.jsonl` | Merge/revert audit (append-only; writer not yet live) |
| `exports/` | Opt-in export scaffolds |

SQLite: `trajectory_fact`, `feedback_events`, `self_improve_jobs` in gateway `sevn.db`; trace spans in `.sevn/traces.db`.

### Preset C, approval, and auto-merge

Code-path audit (honest status as of this branch):

| Path | Status | Where |
| --- | --- | --- |
| Job enqueue guards (enabled, writer cap) | **live** | `facade.enqueue_improve_job` |
| Trajectory ingest (per-turn + cron) | **live** | `trajectory_ingest_hooks`, `scheduler`, `worker._ingest_trajectory_facts` |
| Sampler + shortlist | **live** | `worker._build_shortlist`, `sampler/` |
| Spec-kit plan stage | **live** | `spec_kit_stage.run_improve_spec_kit_plan` |
| Plan HITL (`awaiting_plan_review` → approve → requeue) | **live** | `worker` + `dashboard/api/self_improve.approve_self_improve_plan` |
| Patch author + glob/policy reject | **live** | `proposer/patch_author.py` |
| Eval graph + `awaiting_review` on pass | **live** | `worker._process_job`, `eval/` |
| `ensure_preset_c_auto_merge_allowed` eval gate | **partial** | Implemented + tested in `facade.py`; **not called** from worker or any merge path |
| `require_human_approval` enforcement | **stub** | Config + schema only (`config/sections/self_improve.py`); no runtime check before merge |
| `SEVN_DISABLE_AUTO_MERGE` env | **stub** | Documented in `infra/sevn.schema.json`; no reader in `self_improve/` |
| Patch approval / merge API (MC) | **stub** | No `approve_patch` or `merge` route in `dashboard/api/self_improve.py` |
| Workspace patch apply / `merged` state transition | **stub** | `merged` state exists in `jobs/store` and Telegram copy; **no producer** sets it |
| `self_improve_audit.jsonl` writer | **stub** | Path helper in `paths.py`; no append on promotion |
| Forge PR / `promotion_open_pr` Telegram event | **stub** | Copy in `channels/self_improve_copy.py`; no emitter in improve pipeline |
| `auto_merge_enabled` → workspace write | **stub** | Config flag only; worker stops at `awaiting_review` |

Normative target: [`about-sevn.bot/prd/12-self-improvement.md`](../../about-sevn.bot/prd/12-self-improvement.md). Implementation spec: [`about-sevn.bot/specs/33-self-improvement.md`](../../about-sevn.bot/specs/33-self-improvement.md).

### Key modules

- `src/sevn/self_improve/jobs/worker.py` — async job loop (shortlist → plan → patch → eval → review)
- `src/sevn/self_improve/facade.py` — enqueue, abort, eval wrapper, preset-C eval gate helper
- `src/sevn/self_improve/trajectories/` — ingest, scheduler, runner
- `src/sevn/self_improve/proposer/patch_author.py` — bounded diff authoring
- `src/sevn/self_improve/spec_kit_stage.py` — optional plan-before-patch
- `src/sevn/self_improve/eval/` — golden replay + Docker eval graph
- `src/sevn/ui/dashboard/api/self_improve.py` — Mission Control REST + plan approval

### Spec context

From [`about-sevn.bot/specs/33-self-improvement.md`](../../about-sevn.bot/specs/33-self-improvement.md): closed-loop ingest → shortlist → optional plan → patch author → eval graph → operator-gated promotion. Merge gates and §10 checklist live in that spec.

## Level 3 — Deep dive (low-level, technical)

Primary source tree: `src/sevn/self_improve/` (36 Python files). Normative design: [`about-sevn.bot/specs/33-self-improvement.md`](../../about-sevn.bot/specs/33-self-improvement.md).

### Module inventory

- `src/sevn/self_improve/__init__.py` — """Closed-loop self-improve subsystem ('about-sevn.bot/specs/33-self-improvement.md').
- `src/sevn/self_improve/effective.py` — """Resolve effective self-improve enablement ('about-sevn.bot/specs/33-self-improvement.md' §5).
- `src/sevn/self_improve/eval/__init__.py` — """Docker evaluation launcher ('about-sevn.bot/specs/33-self-improvement.md' §4.3).
- `src/sevn/self_improve/eval/baseline.py` — """Last-known-good baseline and eval report deltas ('about-sevn.bot/specs/33-self-improvement.md' §4.3).
- `src/sevn/self_improve/eval/docker.py` — """Docker compose runner for the improve evaluation graph.
- `src/sevn/self_improve/eval/launcher.py` — """CLI entry for improve evaluation inside Docker ('about-sevn.bot/specs/33-self-improvement.md' §4.3).
- `src/sevn/self_improve/eval/replay.py` — """Golden routing and live replay smoke segments ('about-sevn.bot/specs/33-self-improvement.md' §4.3).
- `src/sevn/self_improve/export.py` — """Trajectory export scaffold under ''.sevn/improve/exports/'' ('about-sevn.bot/specs/33-self-improvement.md' §4.6).
- `src/sevn/self_improve/facade.py` — """Service façades for gateway and dashboard delegation ('about-sevn.bot/specs/33-self-improvement.md' §2).
- `src/sevn/self_improve/feedback/__init__.py` — """Explicit feedback inserts ('about-sevn.bot/specs/33-self-improvement.md' §3.4).
- `src/sevn/self_improve/forge_providers.py` — """Self-improve forge adapters ('about-sevn.bot/specs/33-self-improvement.md' §11).
- `src/sevn/self_improve/jobs/__init__.py` — """Job queue SQLite helpers ('about-sevn.bot/specs/33-self-improvement.md' §3.3).
- … and 24 more Python modules

### Effective (`src/sevn/self_improve/effective.py`)

Public entry points:
- `effective_self_improve_enabled` — see `src/sevn/self_improve/effective.py`

###   Init   (`src/sevn/self_improve/eval/__init__.py`)

Public entry points:
- `golden_routing_fixture_path` — see `src/sevn/self_improve/eval/__init__.py`
- `resolve_repo_root` — see `src/sevn/self_improve/eval/__init__.py`
- `eval_docker_required` — see `src/sevn/self_improve/eval/__init__.py`
- `eval_in_process_override` — see `src/sevn/self_improve/eval/__init__.py`
- `run_eval_graph` — see `src/sevn/self_improve/eval/__init__.py`
- `run_docker_eval_graph` — see `src/sevn/self_improve/eval/__init__.py`
- `eval_report_passed` — see `src/sevn/self_improve/eval/__init__.py`

### Baseline (`src/sevn/self_improve/eval/baseline.py`)

Public entry points:
- `baseline_path_for_job_bundle` — see `src/sevn/self_improve/eval/baseline.py`
- `load_last_known_good` — see `src/sevn/self_improve/eval/baseline.py`
- `save_last_known_good` — see `src/sevn/self_improve/eval/baseline.py`
- `compute_metric_deltas` — see `src/sevn/self_improve/eval/baseline.py`
- `parse_token_budget_daily` — see `src/sevn/self_improve/eval/baseline.py`
- `baseline_section_for_report` — see `src/sevn/self_improve/eval/baseline.py`

### Docker (`src/sevn/self_improve/eval/docker.py`)

Public entry points:
- `run_eval_in_docker` — see `src/sevn/self_improve/eval/docker.py`

### Launcher (`src/sevn/self_improve/eval/launcher.py`)

Public entry points:
- `main` — see `src/sevn/self_improve/eval/launcher.py`

### Replay (`src/sevn/self_improve/eval/replay.py`)

Public entry points:
- `strip_corpus_locale_prefix` — see `src/sevn/self_improve/eval/replay.py`
- `golden_routing_fixture_path` — see `src/sevn/self_improve/eval/replay.py`
- `run_golden_routing_replay` — see `src/sevn/self_improve/eval/replay.py`
- `run_live_replay_smoke` — see `src/sevn/self_improve/eval/replay.py`

### Export (`src/sevn/self_improve/export.py`)

Public entry points:
- `improve_export_dir` — see `src/sevn/self_improve/export.py`
- `scaffold_improve_export_bundle` — see `src/sevn/self_improve/export.py`
- `prune_stale_export_bundles` — see `src/sevn/self_improve/export.py`

### Facade (`src/sevn/self_improve/facade.py`)

Public entry points:
- `ensure_preset_c_auto_merge_allowed` — see `src/sevn/self_improve/facade.py`
- `run_improve_job_eval` — see `src/sevn/self_improve/facade.py`
- `enqueue_improve_job` — see `src/sevn/self_improve/facade.py`
- `abort_improve_job` — see `src/sevn/self_improve/facade.py`

###   Init   (`src/sevn/self_improve/feedback/__init__.py`)

Public entry points:
- `insert_feedback_event` — see `src/sevn/self_improve/feedback/__init__.py`
- `mirror_structured_feedback_to_events` — see `src/sevn/self_improve/feedback/__init__.py`

### Additional modules

24 more Python files under `src/sevn/self_improve/` — including `src/sevn/self_improve/jobs/events.py`, `src/sevn/self_improve/jobs/store.py`, `src/sevn/self_improve/jobs/worker.py`, `src/sevn/self_improve/lessons/__init__.py`.

### Extension and invariants

Follow [`about-sevn.bot/specs/33-self-improvement.md`](../../about-sevn.bot/specs/33-self-improvement.md) for merge gates, error semantics, and compatibility constraints.

## References

- [Product PRD — self-improvement](../../about-sevn.bot/prd/12-self-improvement.md)
- [Spec 33 — self-improvement](../../about-sevn.bot/specs/33-self-improvement.md)

[spec-badge]: https://img.shields.io/badge/Spec-2a7fc6?style=for-the-badge&logo=readthedocs&logoColor=white
[spec-link]: ../../about-sevn.bot/specs/33-self-improvement.md
[source-badge]: https://img.shields.io/badge/Source-0c0a09?style=for-the-badge&logo=github&logoColor=white
[source-link]: ../../src/sevn/self_improve/
[index-badge]: https://img.shields.io/badge/All_READMEs-5fb1f7?style=for-the-badge&logo=markdown&logoColor=white
[index-link]: INDEX.md
