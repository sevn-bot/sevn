<!-- generated: do not edit by hand; run `sevn readme update onboarding` -->
# Onboarding

> **Summary.** Operator setup: CLI, web wizard, Telegram flows, daemon install, and profiles.

## Overview

Operator setup: CLI, web wizard, Telegram flows, daemon install, and profiles.

This guide walks through operator setup step by step. Normative specs: `about-sevn.bot/specs/22-onboarding.md`, `about-sevn.bot/specs/23-cli.md`.

From about-sevn.bot/specs/22-onboarding.md:
Deliver the merge + validation + promotion pipeline every setup path shares so sevn.json stays the single source of truth (prd-06-setup-and-operations §5.4, spec-02-config-and-workspace): shipped pres

From about-sevn.bot/specs/23-cli.md:
Deliver the primary operator and automation surface for install, upgrades, health checks, workspace + daemon lifecycle, and scriptable inspection. The CLI is not the agent’s in-harness tool API and no

## First-time setup

From the repo root run **`make setup`**, then **`sevn onboard`** (web wizard by default; `sevn onboard --cli` for terminal UI). Finish with **`sevn doctor`** to confirm health.

## Daily operations

Use **`sevn gateway start`**, **`sevn config validate`**, and channel-specific commands documented in the linked specs. Re-run onboarding safely with `sevn onboard` when adding channels or rotating secrets.

## References

- [../../about-sevn.bot/specs/22-onboarding.md](../../about-sevn.bot/specs/22-onboarding.md)
- [../../about-sevn.bot/specs/23-cli.md](../../about-sevn.bot/specs/23-cli.md)
