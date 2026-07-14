---
id: spec-00-foundation
kind: spec
title: Foundation — Spec
status: done
owner: Alex
summary: 'Deliver the lowest layer every later spec assumes: a src/sevn/ package layout,
  uv-managed Python 3.12+ project (hatchling build backend), a root Makefile as the
  single recurring-command surface, pre-c'
last_updated: '2026-07-14'
fingerprint: sha256:bc2cb848e0ec03e511ef428ab1e6e967859ef90e25cc5718837adefec83f5d36
related: []
sources:
- src/sevn/__init__.py
parent_prd: prd-00-main
build_phase: null
---
## Purpose

Deliver the lowest layer every later spec assumes: a `src/sevn/` package layout,
**Python 3.12+** project managed by **uv**, **hatchling** build backend, and a
root **Makefile** as the single recurring-command surface for lint, typecheck, test,
and CI tiers. Agents and contributors must not invoke `ruff`, `mypy`, or `pytest`
directly in recurring flows — those tools run only through Make targets (ADR 17).

This spec is normative for project bootstrap (`make setup`), lockfile discipline
(`make lockcheck`), and the composable CI entry points (`make ci`, `make ci-resume`,
`make ci-affected`, `make ci-changed`). Feature specs depend on it via
`depends_on: [spec-00-foundation]`.

## Public Interface

| Symbol / target | Location | Role |
|-----------------|----------|------|
| `requires-python >= 3.12` | `pyproject.toml` | Minimum runtime |
| hatchling wheel | `pyproject.toml` `[build-system]` | Package build |
| `sevn` CLI entry | `pyproject.toml` → `sevn.cli.app:main` | Operator CLI |
| `make help` | `Makefile` | Canonical command index |
| `make setup` | `Makefile` | `uv sync`, pre-commit, git guards, CLI install |
| `make lint` | `Makefile` | ruff check/format, docstring + import policy |
| `make typecheck` | `Makefile` | mypy + type-hint gate |
| `make ci` | `Makefile` | Full pre-merge gate (core + infra + docs + skills + parity) |
| `make ci-resume` | `Makefile` | Resumable full CI loop |
| `make ci-affected` / `ci-changed` | `Makefile` | Path-aware partial gates for wave iteration |
| `make lint-imports` | `Makefile` | import-linter contracts (see spec-01) |

Plugin entry-point groups (`sevn.tools`, `sevn.skills`, `sevn.channels`) are declared
in `pyproject.toml` for optional extensions.

## Data Model

| Artifact | Contract |
|----------|----------|
| `pyproject.toml` | Project metadata, optional extras, tool config (ruff, mypy, import-linter) |
| `uv.lock` | Pinned dependency graph; `make lockcheck` fails on drift |
| `src/sevn/py.typed` | PEP 561 typed-package marker |
| `Makefile` | `CI_STEPS` ordered list for `ci-resume`; tier targets `ci-core`, `ci-infra`, `ci-docs`, `ci-skills`, `ci-parity` |
| `bin/git` | Git guard wrapper blocking `git clean -x`/`-X` |

The root package `src/sevn/__init__.py` is intentionally minimal; subsystems live in
top-level subpackages (`agent`, `gateway`, `config`, `tools`, …).

## Internal Architecture

```text
Developer / CI → make <target> → uv run … / scripts/*
Release → hatchling / uv build → wheel
Operator → sevn CLI (editable install via make setup)
```

**CI composition (`make ci`):** `ci-core` + `ci-infra` + `ci-docs` + `ci-skills` +
`ci-parity`. Advisory: `make ci-quality` (not in `make ci`).

## Behavior

1. **`make setup`** syncs dev extras, pre-commit, git guards, and the `sevn` CLI.
2. **`make lint`** runs ruff, docstring policy, CLI-help spec-ref ban, loguru-only check, import-linter.
3. **`make typecheck`** runs mypy on `src/sevn` plus the type-hint completeness script.
4. **`make ci`** runs the full ordered step list; mid-wave agents prefer `make ci-affected` or `make ci-changed`.
5. **`uv build`** produces the hatchling wheel from `src/sevn`.

## Failure Modes

| Failure | Observable behavior |
|---------|---------------------|
| Lock drift | `make lockcheck` exits non-zero |
| Lint / format | `make lint` fails on ruff or import-linter violations |
| Type errors | `make typecheck` / `make pyright` fail |
| Destructive git clean | `bin/git` blocks `-x`/`-X` |
| CI step failure | `make ci-resume` stops at first failing step |

## Test Strategy

| Gate | Coverage |
|------|----------|
| `make test` | Full pytest suite under `tests/` |
| `make doctest` | Doctests in `src/sevn` |
| `make ci-core` | lint, typecheck, pyright, test, doctest, security, build |
| Wave iteration | `make ci-changed` / `make ci-affected` |

Validate commit subjects with `make commit-msg-check MSG='…'` before commit.
