---
id: spec-06-secrets
kind: spec
title: Secrets — Spec
status: done
owner: Alex
summary: 'Deliver a single trust boundary for credentials: backend modules + TTL cache
  under src/sevn/security/, wired exclusively by the egress proxy (src/sevn/proxy/)
  so agent-facing processes never see raw k'
last_updated: '2026-07-12'
fingerprint: sha256:2d9ba184791b8379bf02d30a43002848db5ba5ceb7cea2d4eef8f610ec618145
related: []
sources:
- src/sevn/secrets/**
parent_prd: prd-03-trust-and-control
depends_on:
- spec-00-foundation
- spec-02-config-and-workspace
build_phase: null
interfaces:
- name: fingerprint_sha256_hex
  file: src/sevn/secrets/fingerprint.py
  symbol: fingerprint_sha256_hex
- name: PromotionResult
  file: src/sevn/secrets/migrate.py
  symbol: PromotionResult
- name: encrypted_file_backend_for_workspace
  file: src/sevn/secrets/migrate.py
  symbol: encrypted_file_backend_for_workspace
- name: legacy_plaintext_entries
  file: src/sevn/secrets/migrate.py
  symbol: legacy_plaintext_entries
- name: non_legacy_files_present
  file: src/sevn/secrets/migrate.py
  symbol: non_legacy_files_present
- name: promote_legacy_plaintext_to_encrypted_store
  file: src/sevn/secrets/migrate.py
  symbol: promote_legacy_plaintext_to_encrypted_store
- name: promote_legacy_plaintext_to_encrypted_store_sync
  file: src/sevn/secrets/migrate.py
  symbol: promote_legacy_plaintext_to_encrypted_store_sync
- name: remove_legacy_plaintext_artifacts
  file: src/sevn/secrets/migrate.py
  symbol: remove_legacy_plaintext_artifacts
- name: secrets_dir_under_content_root
  file: src/sevn/secrets/migrate.py
  symbol: secrets_dir_under_content_root
- name: store_enc_reserved_path
  file: src/sevn/secrets/migrate.py
  symbol: store_enc_reserved_path
specs: []
personas: []
prd_profile: null
---

## Purpose

Offline scaffold for Secrets — Spec (spec-06-secrets) — Purpose.

## Public Interface

Offline scaffold for Secrets — Spec (spec-06-secrets) — Public Interface.

## Data Model

Offline scaffold for Secrets — Spec (spec-06-secrets) — Data Model.

## Internal Architecture

Offline scaffold for Secrets — Spec (spec-06-secrets) — Internal Architecture.

## Behavior

Offline scaffold for Secrets — Spec (spec-06-secrets) — Behavior.

## Failure Modes

Offline scaffold for Secrets — Spec (spec-06-secrets) — Failure Modes.

## Test Strategy

Offline scaffold for Secrets — Spec (spec-06-secrets) — Test Strategy.
