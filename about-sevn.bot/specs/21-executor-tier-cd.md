---
id: spec-21-executor-tier-cd
kind: spec
title: Executor tier C/D — Spec
status: scaffold
owner: Alex
summary: 'Tier C/D is the planned-work executor for messages the Triager classifies
  as complexity == C or complexity == D (prd-04-getting-things-done §5.3–§5.4): structured
  planning, optional owner approval (Pl'
last_updated: '2026-07-12'
fingerprint: sha256:fa2b6320a8f4d1b4766983f4bdd67707d234f602503b5d953202ac24799c18ba
related: []
sources:
- src/sevn/coding_agents/**
parent_prd: prd-04-getting-things-done
depends_on:
- spec-02-config-and-workspace
- spec-05-llm-transports
- spec-13-rlm-triager
- spec-14-executor-tier-b
- spec-16-harness-discipline
build_phase: null
interfaces:
- name: EvaluatorResult
  file: src/sevn/coding_agents/alrca/evaluator.py
  symbol: EvaluatorResult
- name: NullEvaluator
  file: src/sevn/coding_agents/alrca/evaluator.py
  symbol: NullEvaluator
- name: evaluate_turn
  file: src/sevn/coding_agents/alrca/evaluator.py
  symbol: evaluate_turn
- name: GoalContract
  file: src/sevn/coding_agents/alrca/goal.py
  symbol: GoalContract
- name: GoalStatus
  file: src/sevn/coding_agents/alrca/goal.py
  symbol: GoalStatus
- name: list_goals
  file: src/sevn/coding_agents/alrca/goal.py
  symbol: list_goals
- name: load_goal
  file: src/sevn/coding_agents/alrca/goal.py
  symbol: load_goal
- name: new_goal
  file: src/sevn/coding_agents/alrca/goal.py
  symbol: new_goal
- name: save_goal
  file: src/sevn/coding_agents/alrca/goal.py
  symbol: save_goal
- name: ALRCALoopWorker
  file: src/sevn/coding_agents/alrca/loop_worker.py
  symbol: ALRCALoopWorker
- name: LoopResult
  file: src/sevn/coding_agents/alrca/loop_worker.py
  symbol: LoopResult
- name: run_alrca_loop
  file: src/sevn/coding_agents/alrca/loop_worker.py
  symbol: run_alrca_loop
- name: BuiltinVerifierKind
  file: src/sevn/coding_agents/alrca/verifiers/base.py
  symbol: BuiltinVerifierKind
- name: VerifierResult
  file: src/sevn/coding_agents/alrca/verifiers/base.py
  symbol: VerifierResult
- name: build_verifier
  file: src/sevn/coding_agents/alrca/verifiers/base.py
  symbol: build_verifier
- name: run_verifier_spec
  file: src/sevn/coding_agents/alrca/verifiers/base.py
  symbol: run_verifier_spec
- name: list_all_runs
  file: src/sevn/coding_agents/artifacts/vault.py
  symbol: list_all_runs
- name: list_run_artifacts
  file: src/sevn/coding_agents/artifacts/vault.py
  symbol: list_run_artifacts
- name: read_artifact
  file: src/sevn/coding_agents/artifacts/vault.py
  symbol: read_artifact
- name: write_artifact
  file: src/sevn/coding_agents/artifacts/vault.py
  symbol: write_artifact
- name: StubExecutor
  file: src/sevn/coding_agents/executors/__init__.py
  symbol: StubExecutor
- name: build_executor
  file: src/sevn/coding_agents/executors/__init__.py
  symbol: build_executor
- name: ExecutorProtocol
  file: src/sevn/coding_agents/executors/protocol.py
  symbol: ExecutorProtocol
- name: ExecutorResult
  file: src/sevn/coding_agents/executors/protocol.py
  symbol: ExecutorResult
- name: migrate_legacy_claude_agent_topic
  file: src/sevn/coding_agents/migrate.py
  symbol: migrate_legacy_claude_agent_topic
- name: binding_matches
  file: src/sevn/coding_agents/registry.py
  symbol: binding_matches
- name: list_agent_summaries
  file: src/sevn/coding_agents/registry.py
  symbol: list_agent_summaries
- name: match_telegram_binding
  file: src/sevn/coding_agents/registry.py
  symbol: match_telegram_binding
specs: []
personas: []
prd_profile: null
---


## Purpose

Tier C/D is the planned-work executor for messages the Triager classifies as complexity == C or complexity == D (prd-04-getting-things-done §5.3–§5.4): structured planning, optional owner approval (Pl

Primary code trees: [`src/sevn/coding_agents`](src/sevn/coding_agents/__init__.py).

Initial draft for **Purpose** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Purpose — acceptance criteria and edge cases. -->
## Public Interface

Initial draft for **Public Interface** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Public Interface — acceptance criteria and edge cases. -->

- [`EvaluatorResult`](src/sevn/coding_agents/alrca/evaluator.py) — `src/sevn/coding_agents/alrca/evaluator.py`
- [`NullEvaluator`](src/sevn/coding_agents/alrca/evaluator.py) — `src/sevn/coding_agents/alrca/evaluator.py`
- [`evaluate_turn`](src/sevn/coding_agents/alrca/evaluator.py) — `src/sevn/coding_agents/alrca/evaluator.py`
- [`GoalContract`](src/sevn/coding_agents/alrca/goal.py) — `src/sevn/coding_agents/alrca/goal.py`
- [`GoalStatus`](src/sevn/coding_agents/alrca/goal.py) — `src/sevn/coding_agents/alrca/goal.py`
- [`list_goals`](src/sevn/coding_agents/alrca/goal.py) — `src/sevn/coding_agents/alrca/goal.py`
- [`load_goal`](src/sevn/coding_agents/alrca/goal.py) — `src/sevn/coding_agents/alrca/goal.py`
- [`new_goal`](src/sevn/coding_agents/alrca/goal.py) — `src/sevn/coding_agents/alrca/goal.py`
- [`save_goal`](src/sevn/coding_agents/alrca/goal.py) — `src/sevn/coding_agents/alrca/goal.py`
- [`ALRCALoopWorker`](src/sevn/coding_agents/alrca/loop_worker.py) — `src/sevn/coding_agents/alrca/loop_worker.py`
- [`LoopResult`](src/sevn/coding_agents/alrca/loop_worker.py) — `src/sevn/coding_agents/alrca/loop_worker.py`
- [`run_alrca_loop`](src/sevn/coding_agents/alrca/loop_worker.py) — `src/sevn/coding_agents/alrca/loop_worker.py`
- _…and 16 more in frontmatter `interfaces:`._
## Data Model

Initial draft for **Data Model** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Data Model — acceptance criteria and edge cases. -->

- [`EvaluatorResult`](src/sevn/coding_agents/alrca/evaluator.py) — `src/sevn/coding_agents/alrca/evaluator.py`
- [`NullEvaluator`](src/sevn/coding_agents/alrca/evaluator.py) — `src/sevn/coding_agents/alrca/evaluator.py`
- [`evaluate_turn`](src/sevn/coding_agents/alrca/evaluator.py) — `src/sevn/coding_agents/alrca/evaluator.py`
- [`GoalContract`](src/sevn/coding_agents/alrca/goal.py) — `src/sevn/coding_agents/alrca/goal.py`
- [`GoalStatus`](src/sevn/coding_agents/alrca/goal.py) — `src/sevn/coding_agents/alrca/goal.py`
- [`list_goals`](src/sevn/coding_agents/alrca/goal.py) — `src/sevn/coding_agents/alrca/goal.py`
- [`load_goal`](src/sevn/coding_agents/alrca/goal.py) — `src/sevn/coding_agents/alrca/goal.py`
- [`new_goal`](src/sevn/coding_agents/alrca/goal.py) — `src/sevn/coding_agents/alrca/goal.py`
- [`save_goal`](src/sevn/coding_agents/alrca/goal.py) — `src/sevn/coding_agents/alrca/goal.py`
- [`ALRCALoopWorker`](src/sevn/coding_agents/alrca/loop_worker.py) — `src/sevn/coding_agents/alrca/loop_worker.py`
- [`LoopResult`](src/sevn/coding_agents/alrca/loop_worker.py) — `src/sevn/coding_agents/alrca/loop_worker.py`
- [`run_alrca_loop`](src/sevn/coding_agents/alrca/loop_worker.py) — `src/sevn/coding_agents/alrca/loop_worker.py`
- _…and 16 more in frontmatter `interfaces:`._
## Internal Architecture

See **Implemented by** and [`src/sevn/coding_agents`](src/sevn/coding_agents/__init__.py).
## Behavior

Initial draft for **Behavior** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Behavior — acceptance criteria and edge cases. -->

Trace control flow starting from the load-bearing symbols in **Implemented by** (below) and cross-check against [`src/sevn/coding_agents`](src/sevn/coding_agents/__init__.py).
## Failure Modes

Initial draft for **Failure Modes** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Failure Modes — acceptance criteria and edge cases. -->

Document observable failure surfaces from the implementing modules (exceptions, logged errors, degraded modes) — cite code paths.
## Amendments (spec-36-sub-agents)

Tier C/D executor runs register as **level-1** sub-agents where the turn spine wraps
them (`src/sevn/gateway/agent_turn.py`). `spawn_subagent` is available where the
tier tool registry allows (D1/D9).

## Implemented by

- [`EvaluatorResult`](src/sevn/coding_agents/alrca/evaluator.py) — `src/sevn/coding_agents/alrca/evaluator.py`
- [`NullEvaluator`](src/sevn/coding_agents/alrca/evaluator.py) — `src/sevn/coding_agents/alrca/evaluator.py`
- [`evaluate_turn`](src/sevn/coding_agents/alrca/evaluator.py) — `src/sevn/coding_agents/alrca/evaluator.py`
- [`GoalContract`](src/sevn/coding_agents/alrca/goal.py) — `src/sevn/coding_agents/alrca/goal.py`
- [`GoalStatus`](src/sevn/coding_agents/alrca/goal.py) — `src/sevn/coding_agents/alrca/goal.py`
- [`list_goals`](src/sevn/coding_agents/alrca/goal.py) — `src/sevn/coding_agents/alrca/goal.py`
- [`load_goal`](src/sevn/coding_agents/alrca/goal.py) — `src/sevn/coding_agents/alrca/goal.py`
- [`new_goal`](src/sevn/coding_agents/alrca/goal.py) — `src/sevn/coding_agents/alrca/goal.py`
- [`save_goal`](src/sevn/coding_agents/alrca/goal.py) — `src/sevn/coding_agents/alrca/goal.py`
- [`ALRCALoopWorker`](src/sevn/coding_agents/alrca/loop_worker.py) — `src/sevn/coding_agents/alrca/loop_worker.py`
- [`LoopResult`](src/sevn/coding_agents/alrca/loop_worker.py) — `src/sevn/coding_agents/alrca/loop_worker.py`
- [`run_alrca_loop`](src/sevn/coding_agents/alrca/loop_worker.py) — `src/sevn/coding_agents/alrca/loop_worker.py`
- [`BuiltinVerifierKind`](src/sevn/coding_agents/alrca/verifiers/base.py) — `src/sevn/coding_agents/alrca/verifiers/base.py`
- [`VerifierResult`](src/sevn/coding_agents/alrca/verifiers/base.py) — `src/sevn/coding_agents/alrca/verifiers/base.py`
- [`build_verifier`](src/sevn/coding_agents/alrca/verifiers/base.py) — `src/sevn/coding_agents/alrca/verifiers/base.py`
- [`run_verifier_spec`](src/sevn/coding_agents/alrca/verifiers/base.py) — `src/sevn/coding_agents/alrca/verifiers/base.py`
- [`list_all_runs`](src/sevn/coding_agents/artifacts/vault.py) — `src/sevn/coding_agents/artifacts/vault.py`
- [`list_run_artifacts`](src/sevn/coding_agents/artifacts/vault.py) — `src/sevn/coding_agents/artifacts/vault.py`
- [`read_artifact`](src/sevn/coding_agents/artifacts/vault.py) — `src/sevn/coding_agents/artifacts/vault.py`
- [`write_artifact`](src/sevn/coding_agents/artifacts/vault.py) — `src/sevn/coding_agents/artifacts/vault.py`
- _…and 8 more in frontmatter `interfaces:`._

## Test Strategy

Initial draft for **Test Strategy** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Test Strategy — acceptance criteria and edge cases. -->

Map to existing tests under `tests/` that cover this subsystem; add Makefile-only gates where applicable.
