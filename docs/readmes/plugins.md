<!-- generated: do not edit by hand; run `sevn readme update plugins` -->
# Plugin hooks — In-process hook chains, channel plugin registry, slash bindings, and trigger mux

[![Spec][spec-badge]][spec-link]
[![Source][source-badge]][source-link]
[![Index][index-badge]][index-link]

> **Summary.** In-process hook chains, channel plugin registry, slash bindings, and trigger mux. Deliver the in-process extension layer that intercepts existing tool and terminal I/O paths and registers dispatcher-level commands, without adding new tool symbols or transports in-tree.

## Level 1 — Overview (non-technical)

**Plugin hooks** is a core part of sevn.bot — the personal AI assistant you run on your own machine. In-process hook chains, channel plugin registry, slash bindings, and trigger mux.

In everyday use, plugin hooks helps Sevn do its job reliably: you interact through familiar channels (Telegram, browser, voice), and this layer keeps those interactions safe, consistent, and under your control.

Deliver the in-process extension layer that intercepts existing tool and terminal I/O paths and registers dispatcher-level commands, without adding new tool symbols or transports in-tree.

## Level 2 — How it works (technical)

### Components and layout

Implementation lives under `src/sevn/plugins/`. The package contains 6 Python module(s); primary entry points include `src/sevn/plugins/__init__.py`, `src/sevn/plugins/command_spec.py`, `src/sevn/plugins/hook.py`, `src/sevn/plugins/registry.py`, `src/sevn/plugins/runner.py`, `src/sevn/plugins/trigger_mux.py`.

### Data and control flow

Plugin hooks is organized around `  init  `, `command spec`, `hook`, `registry`, and 2 more under `src/sevn/plugins/` with 6 Python module(s) in the scanned tree. Primary entry points include hook.py (PluginHook.pre_tool_call), registry.py (valid_hook_name), runner.py (PluginHookChain.run_pre_tool_call), trigger_mux.py (TriggerPluginHooksMux.trigger_before_receive).

### Configuration

Operator settings come from `sevn.json` in the workspace. Related normative specs: `about-sevn.bot/specs/34-plugin-hooks.md`. Run `sevn config validate` after edits; use `sevn doctor` to confirm the install sees the expected layout.

### Key modules

- `src/sevn/plugins/hook.py` — `PluginHook.pre_tool_call`, `PluginHook.transform_tool_result`, `PluginHook.transform_terminal_output`, `PluginHook (+4 methods)`
- `src/sevn/plugins/registry.py` — `valid_hook_name`, `order_hooks_by_runs_after`, `load_plugin_hook_chain`, `collect_plugin_slash_bindings`
- `src/sevn/plugins/runner.py` — `PluginHookChain.run_pre_tool_call`, `PluginHookChain.run_transform_tool_result`, `PluginHookChain.transform_terminal_chunk`
- `src/sevn/plugins/trigger_mux.py` — `TriggerPluginHooksMux.trigger_before_receive`, `TriggerPluginHooksMux.trigger_after_dispatch`, `as_trigger_surface`

### Spec context

From about-sevn.bot/specs/34-plugin-hooks.md:
Deliver the in-process extension layer that intercepts existing tool and terminal I/O paths and registers dispatcher-level commands, without adding new tool symbols or transports in-tree.

Deliver the in-process extension layer that intercepts existing tool and terminal I/O paths and registers dispatcher-level commands, without adding new tool symbols or transports in-tree.

Primary code trees: `src/sevn/plugins/`.

Initial draft for **Purpose** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Purpose — acceptance criteria and edge cases.

## Level 3 — Deep dive (low-level, technical)

Primary source tree: [`src/sevn/plugins`](../../src/sevn/plugins/) (6 Python files). Normative design: `about-sevn.bot/specs/34-plugin-hooks.md`.

### Module inventory

Plugin loading and hook contracts.

Working with [`__init__.py`](../../src/sevn/plugins/__init__.py): inspect the public entry points below.

Plugin-registered slash commands (about-sevn.bot/specs/34-plugin-hooks.md §2.2).

Working with [`command_spec.py`](../../src/sevn/plugins/command_spec.py): inspect the public entry points below.

Plugin hook types (PluginHook protocol and optional base class).

Working with [`hook.py`](../../src/sevn/plugins/hook.py): inspect the public entry points below.
Start with [`PluginHook.pre_tool_call`](../../src/sevn/plugins/hook.py#L61), then [`PluginHook.transform_tool_result`](../../src/sevn/plugins/hook.py#L83), [`PluginHook.transform_terminal_output`](../../src/sevn/plugins/hook.py#L105), [`PluginHookBase.pre_tool_call`](../../src/sevn/plugins/hook.py#L213).

Entry-point discovery for sevn.plugin_hooks / sevn.channels (about-sevn.bot/specs/34-plugin-hooks.md §2.4).

Working with [`registry.py`](../../src/sevn/plugins/registry.py): inspect the public entry points below.
Start with [`valid_hook_name`](../../src/sevn/plugins/registry.py#L37), then [`order_hooks_by_runs_after`](../../src/sevn/plugins/registry.py#L151), [`load_plugin_hook_chain`](../../src/sevn/plugins/registry.py#L199), [`collect_plugin_slash_bindings`](../../src/sevn/plugins/registry.py#L279).

Ordered plugin hook invocation (about-sevn.bot/specs/34-plugin-hooks.md §4.2-§4.4).

Working with [`runner.py`](../../src/sevn/plugins/runner.py): inspect the public entry points below.
Start with [`PluginHookChain.run_pre_tool_call`](../../src/sevn/plugins/runner.py#L42), then [`PluginHookChain.run_transform_tool_result`](../../src/sevn/plugins/runner.py#L131), [`PluginHookChain.transform_terminal_chunk`](../../src/sevn/plugins/runner.py#L208).

Multiplex trigger ingress/egress across loaded plugin hooks.

Working with [`trigger_mux.py`](../../src/sevn/plugins/trigger_mux.py): inspect the public entry points below.
Start with [`TriggerPluginHooksMux.trigger_before_receive`](../../src/sevn/plugins/trigger_mux.py#L36), then [`TriggerPluginHooksMux.trigger_after_dispatch`](../../src/sevn/plugins/trigger_mux.py#L61), [`as_trigger_surface`](../../src/sevn/plugins/trigger_mux.py#L90).

### Extension and invariants

Follow [`34-plugin-hooks.md`](../../about-sevn.bot/specs/34-plugin-hooks.md) for merge gates, error semantics, and compatibility constraints. After code changes under [`src/sevn/plugins`](../../src/sevn/plugins/), run `sevn readme update plugins` and `make readme-check`.

## References

- [../../about-sevn.bot/specs/34-plugin-hooks.md](../../about-sevn.bot/specs/34-plugin-hooks.md)

[spec-badge]: https://img.shields.io/badge/Spec-2a7fc6?style=for-the-badge&logo=readthedocs&logoColor=white
[spec-link]: ../../about-sevn.bot/specs/34-plugin-hooks.md
[source-badge]: https://img.shields.io/badge/Source-0c0a09?style=for-the-badge&logo=github&logoColor=white
[source-link]: ../../src/sevn/plugins/
[index-badge]: https://img.shields.io/badge/All_READMEs-5fb1f7?style=for-the-badge&logo=markdown&logoColor=white
[index-link]: INDEX.md
