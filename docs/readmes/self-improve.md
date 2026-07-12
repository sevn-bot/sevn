<!-- generated: do not edit by hand; run `sevn readme update self-improve` -->
# Self-improvement — Self-upgrade harness, eval workers, spec-kit stages, and improve jobs

[![Spec][spec-badge]][spec-link]
[![Source][source-badge]][source-link]
[![Index][index-badge]][index-link]

> **Summary.** Self-upgrade harness, eval workers, spec-kit stages, and improve jobs.

## Level 1 — Overview (non-technical)

**Self-improvement** is a core part of sevn.bot — the personal AI assistant you run on your own machine. Self-upgrade harness, eval workers, spec-kit stages, and improve jobs.

In everyday use, self-improvement helps Sevn do its job reliably: you interact through familiar channels (Telegram, browser, voice), and this layer keeps those interactions safe, consistent, and under your control.

Deliver src/sevn/self_improve/: ingest traces + session artefacts + explicit user feedback into trajectory_fact rows, deterministically shortlist turns for review or patching, optionally run an in-pro

## Level 2 — How it works (technical)

### Components and layout

Implementation lives under `src/sevn/self_improve/`. The package contains 36 Python module(s); primary entry points include `src/sevn/self_improve/__init__.py`, `src/sevn/self_improve/effective.py`, `src/sevn/self_improve/eval/__init__.py`, `src/sevn/self_improve/eval/baseline.py`, and 2 more.

### Data and control flow

Self-improvement sits in the sevn.bot turn spine: a channel delivers a message, the gateway normalises it, triage routes work to the right executor, and the reply returns through the same channel adapter. This subsystem owns the responsibilities described in the manifest summary and defers provider API calls to the paired egress proxy (keys never load in the gateway process).

### Configuration

Operator settings come from `sevn.json` in the workspace. Related normative specs: `specs/33-self-improvement.md`. Run `sevn config validate` after edits; use `sevn doctor` to confirm the install sees the expected layout.

### Key modules

- `src/sevn/self_improve/effective.py` — `effective_self_improve_enabled`
- `src/sevn/self_improve/eval/__init__.py` — `golden_routing_fixture_path`, `resolve_repo_root`, `eval_docker_required`, `eval_in_process_override`
- `src/sevn/self_improve/eval/baseline.py` — `baseline_path_for_job_bundle`, `load_last_known_good`, `save_last_known_good`, `compute_metric_deltas`
- `src/sevn/self_improve/eval/docker.py` — `run_eval_in_docker`
- `src/sevn/self_improve/eval/launcher.py` — `main`

### Spec context

From specs/33-self-improvement.md:
Deliver src/sevn/self_improve/: ingest traces + session artefacts + explicit user feedback into trajectory_fact rows, deterministically shortlist turns for review or patching, optionally run an in-pro

## Level 3 — Deep dive (low-level, technical)

Primary source tree: `src/sevn/self_improve/` (36 Python files). Normative design: `specs/33-self-improvement.md`.

### Module inventory

- `src/sevn/self_improve/__init__.py` — """Closed-loop self-improve subsystem ('specs/33-self-improvement.md').
- `src/sevn/self_improve/effective.py` — """Resolve effective self-improve enablement ('specs/33-self-improvement.md' §5).
- `src/sevn/self_improve/eval/__init__.py` — """Docker evaluation launcher ('specs/33-self-improvement.md' §4.3).
- `src/sevn/self_improve/eval/baseline.py` — """Last-known-good baseline and eval report deltas ('specs/33-self-improvement.md' §4.3).
- `src/sevn/self_improve/eval/docker.py` — """Docker compose runner for the improve evaluation graph.
- `src/sevn/self_improve/eval/launcher.py` — """CLI entry for improve evaluation inside Docker ('specs/33-self-improvement.md' §4.3).
- `src/sevn/self_improve/eval/replay.py` — """Golden routing and live replay smoke segments ('specs/33-self-improvement.md' §4.3).
- `src/sevn/self_improve/export.py` — """Trajectory export scaffold under ''.sevn/improve/exports/'' ('specs/33-self-improvement.md' §4.6).
- `src/sevn/self_improve/facade.py` — """Service façades for gateway and dashboard delegation ('specs/33-self-improvement.md' §2).
- `src/sevn/self_improve/feedback/__init__.py` — """Explicit feedback inserts ('specs/33-self-improvement.md' §3.4).
- `src/sevn/self_improve/forge_providers.py` — """Self-improve forge adapters ('specs/33-self-improvement.md' §11).
- `src/sevn/self_improve/jobs/__init__.py` — """Job queue SQLite helpers ('specs/33-self-improvement.md' §3.3).
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

Follow `specs/33-self-improvement.md` for merge gates, error semantics, and compatibility constraints. After code changes under `src/sevn/self_improve/`, run `sevn readme update self-improve` and `make readme-check`.

## References

- [specs/33-self-improvement.md](specs/33-self-improvement.md)

[spec-badge]: https://img.shields.io/badge/Spec-2a7fc6?style=for-the-badge&logo=readthedocs&logoColor=white
[spec-link]: specs/33-self-improvement.md
[source-badge]: https://img.shields.io/badge/Source-0c0a09?style=for-the-badge&logo=github&logoColor=white
[source-link]: src/sevn/self_improve/
[index-badge]: https://img.shields.io/badge/All_READMEs-5fb1f7?style=for-the-badge&logo=markdown&logoColor=white
[index-link]: docs/readmes/INDEX.md
