---
id: spec-26-claude-agent
kind: spec
title: Claude Agent — Spec
status: rejected
owner: Alex
summary: '- N/A: Spec rejected — no implementation rows for v0.0.2.'
last_updated: '2026-06-19'
fingerprint: sha256:fa2b6320a8f4d1b4766983f4bdd67707d234f602503b5d953202ac24799c18ba
related: []
sources:
- src/sevn/coding_agents/**
parent_prd: prd-08-coding-companion
depends_on: []
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
---

## Purpose

Offline scaffold for Claude Agent — Spec (spec-26-claude-agent) — Purpose.

## Public Interface

Offline scaffold for Claude Agent — Spec (spec-26-claude-agent) — Public Interface.

## Data Model

Offline scaffold for Claude Agent — Spec (spec-26-claude-agent) — Data Model.

## Internal Architecture

Offline scaffold for Claude Agent — Spec (spec-26-claude-agent) — Internal Architecture.

## Behavior

Offline scaffold for Claude Agent — Spec (spec-26-claude-agent) — Behavior.

## Failure Modes

Offline scaffold for Claude Agent — Spec (spec-26-claude-agent) — Failure Modes.

## Test Strategy

Offline scaffold for Claude Agent — Spec (spec-26-claude-agent) — Test Strategy.
