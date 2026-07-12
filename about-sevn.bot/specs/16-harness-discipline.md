---
id: spec-16-harness-discipline
kind: spec
title: Harness discipline — Spec
status: done
owner: Alex
summary: 45# Harness discipline — Spec
last_updated: '2026-07-07'
fingerprint: sha256:ec658899f82afd5f0a138328407204e02b564a13ff3835e5adc9635b28f37023
related: []
sources:
- src/sevn/runtime/**
parent_prd: prd-04-getting-things-done
depends_on:
- spec-02-config-and-workspace
- spec-13-rlm-triager
- spec-14-executor-tier-b
build_phase: null
interfaces:
- name: spawn_logged
  file: src/sevn/runtime/background_tasks.py
  symbol: spawn_logged
- name: augment_macos_dyld_library_path
  file: src/sevn/runtime/operator_path.py
  symbol: augment_macos_dyld_library_path
- name: augment_operator_path
  file: src/sevn/runtime/operator_path.py
  symbol: augment_operator_path
- name: operator_path_prefixes
  file: src/sevn/runtime/operator_path.py
  symbol: operator_path_prefixes
specs: []
personas: []
---

## Purpose

Offline scaffold for Harness discipline — Spec (spec-16-harness-discipline) — Purpose.

## Public Interface

Offline scaffold for Harness discipline — Spec (spec-16-harness-discipline) — Public Interface.

## Data Model

Offline scaffold for Harness discipline — Spec (spec-16-harness-discipline) — Data Model.

## Internal Architecture

Offline scaffold for Harness discipline — Spec (spec-16-harness-discipline) — Internal Architecture.

## Behavior

Offline scaffold for Harness discipline — Spec (spec-16-harness-discipline) — Behavior.

## Failure Modes

Offline scaffold for Harness discipline — Spec (spec-16-harness-discipline) — Failure Modes.

## Test Strategy

Offline scaffold for Harness discipline — Spec (spec-16-harness-discipline) — Test Strategy.
