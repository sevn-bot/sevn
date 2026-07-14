---
id: spec-34-plugin-hooks
kind: spec
title: Plugin hooks & channel plugins — Spec
status: scaffold
owner: Alex
summary: Deliver the in-process extension layer that intercepts existing tool and
  terminal I/O paths and registers dispatcher-level commands, without adding new tool
  symbols or transports in-tree.
last_updated: '2026-07-12'
fingerprint: sha256:ab4e914f79036515eb4f237c238304c982aa0fc45e281f11d363ab2dd6627349
related: []
sources:
- src/sevn/plugins/**
parent_prd: prd-13-extensibility
depends_on:
- spec-01-system-overview
- spec-02-config-and-workspace
- spec-04-tracing
- spec-06-secrets
- spec-08-sandbox
- spec-11-tools-registry
- spec-16-harness-discipline
- spec-17-gateway
- spec-18-channel-telegram
- spec-23-cli
- spec-24-dashboard
- spec-30-non-interactive-triggers
build_phase: null
interfaces:
- name: PluginCommandSpec
  file: src/sevn/plugins/command_spec.py
  symbol: PluginCommandSpec
- name: PluginSlashBinding
  file: src/sevn/plugins/command_spec.py
  symbol: PluginSlashBinding
- name: Block
  file: src/sevn/plugins/hook.py
  symbol: Block
- name: Continue
  file: src/sevn/plugins/hook.py
  symbol: Continue
- name: HookContext
  file: src/sevn/plugins/hook.py
  symbol: HookContext
- name: PluginHook
  file: src/sevn/plugins/hook.py
  symbol: PluginHook
- name: PluginHookBase
  file: src/sevn/plugins/hook.py
  symbol: PluginHookBase
- name: Replace
  file: src/sevn/plugins/hook.py
  symbol: Replace
- name: ChannelPluginSpec
  file: src/sevn/plugins/registry.py
  symbol: ChannelPluginSpec
- name: DashboardBadgeEntry
  file: src/sevn/plugins/registry.py
  symbol: DashboardBadgeEntry
- name: build_trigger_mux
  file: src/sevn/plugins/registry.py
  symbol: build_trigger_mux
- name: collect_plugin_slash_bindings
  file: src/sevn/plugins/registry.py
  symbol: collect_plugin_slash_bindings
- name: load_channel_plugin_classes
  file: src/sevn/plugins/registry.py
  symbol: load_channel_plugin_classes
- name: load_dashboard_badge_entries
  file: src/sevn/plugins/registry.py
  symbol: load_dashboard_badge_entries
- name: load_plugin_hook_chain
  file: src/sevn/plugins/registry.py
  symbol: load_plugin_hook_chain
- name: order_hooks_by_runs_after
  file: src/sevn/plugins/registry.py
  symbol: order_hooks_by_runs_after
- name: valid_hook_name
  file: src/sevn/plugins/registry.py
  symbol: valid_hook_name
- name: PluginHookChain
  file: src/sevn/plugins/runner.py
  symbol: PluginHookChain
- name: RegisteredHook
  file: src/sevn/plugins/runner.py
  symbol: RegisteredHook
- name: TriggerPluginHooksMux
  file: src/sevn/plugins/trigger_mux.py
  symbol: TriggerPluginHooksMux
- name: as_trigger_surface
  file: src/sevn/plugins/trigger_mux.py
  symbol: as_trigger_surface
specs: []
personas: []
prd_profile: null
---


## Purpose

Deliver the in-process extension layer that intercepts existing tool and terminal I/O paths and registers dispatcher-level commands, without adding new tool symbols or transports in-tree.

Primary code trees: `src/sevn/plugins/`.

Initial draft for **Purpose** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Purpose — acceptance criteria and edge cases. -->
## Public Interface

Initial draft for **Public Interface** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Public Interface — acceptance criteria and edge cases. -->

- [`PluginCommandSpec`](src/sevn/plugins/command_spec.py) — `src/sevn/plugins/command_spec.py`
- [`PluginSlashBinding`](src/sevn/plugins/command_spec.py) — `src/sevn/plugins/command_spec.py`
- [`Block`](src/sevn/plugins/hook.py) — `src/sevn/plugins/hook.py`
- [`Continue`](src/sevn/plugins/hook.py) — `src/sevn/plugins/hook.py`
- [`HookContext`](src/sevn/plugins/hook.py) — `src/sevn/plugins/hook.py`
- [`PluginHook`](src/sevn/plugins/hook.py) — `src/sevn/plugins/hook.py`
- [`PluginHookBase`](src/sevn/plugins/hook.py) — `src/sevn/plugins/hook.py`
- [`Replace`](src/sevn/plugins/hook.py) — `src/sevn/plugins/hook.py`
- [`ChannelPluginSpec`](src/sevn/plugins/registry.py) — `src/sevn/plugins/registry.py`
- [`DashboardBadgeEntry`](src/sevn/plugins/registry.py) — `src/sevn/plugins/registry.py`
- [`build_trigger_mux`](src/sevn/plugins/registry.py) — `src/sevn/plugins/registry.py`
- [`collect_plugin_slash_bindings`](src/sevn/plugins/registry.py) — `src/sevn/plugins/registry.py`
- _…and 9 more in frontmatter `interfaces:`._
## Data Model

Initial draft for **Data Model** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Data Model — acceptance criteria and edge cases. -->

- [`PluginCommandSpec`](src/sevn/plugins/command_spec.py) — `src/sevn/plugins/command_spec.py`
- [`PluginSlashBinding`](src/sevn/plugins/command_spec.py) — `src/sevn/plugins/command_spec.py`
- [`Block`](src/sevn/plugins/hook.py) — `src/sevn/plugins/hook.py`
- [`Continue`](src/sevn/plugins/hook.py) — `src/sevn/plugins/hook.py`
- [`HookContext`](src/sevn/plugins/hook.py) — `src/sevn/plugins/hook.py`
- [`PluginHook`](src/sevn/plugins/hook.py) — `src/sevn/plugins/hook.py`
- [`PluginHookBase`](src/sevn/plugins/hook.py) — `src/sevn/plugins/hook.py`
- [`Replace`](src/sevn/plugins/hook.py) — `src/sevn/plugins/hook.py`
- [`ChannelPluginSpec`](src/sevn/plugins/registry.py) — `src/sevn/plugins/registry.py`
- [`DashboardBadgeEntry`](src/sevn/plugins/registry.py) — `src/sevn/plugins/registry.py`
- [`build_trigger_mux`](src/sevn/plugins/registry.py) — `src/sevn/plugins/registry.py`
- [`collect_plugin_slash_bindings`](src/sevn/plugins/registry.py) — `src/sevn/plugins/registry.py`
- _…and 9 more in frontmatter `interfaces:`._
## Internal Architecture

See **Implemented by** and [`src/sevn/plugins`](src/sevn/plugins/__init__.py).
## Behavior

Initial draft for **Behavior** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Behavior — acceptance criteria and edge cases. -->

Trace control flow starting from the load-bearing symbols in **Implemented by** (below) and cross-check against [`src/sevn/plugins`](src/sevn/plugins/__init__.py).
## Failure Modes

Initial draft for **Failure Modes** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Failure Modes — acceptance criteria and edge cases. -->

Document observable failure surfaces from the implementing modules (exceptions, logged errors, degraded modes) — cite code paths.
## Test Strategy

Initial draft for **Test Strategy** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Test Strategy — acceptance criteria and edge cases. -->

Map to existing tests under `tests/` that cover this subsystem; add Makefile-only gates where applicable.
