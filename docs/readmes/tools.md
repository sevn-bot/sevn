<!-- curated: hand-authored; after source changes review the body, then run `sevn readme fingerprint tools` -->
# Tools registry — Module inventory for the tools registry, adapters, and permission gates

[![Spec][spec-badge]][spec-link]
[![Source][source-badge]][source-link]
[![Index][index-badge]][index-link]

> **Summary.** Module inventory for the tools registry, adapters, and permission gates.

## Level 1 — Overview (non-technical)

The **tools registry** is the executor's toolbox: every `@sevn_tool` the tier-B/C agent can invoke is registered on a per-session [`ToolExecutor`](../../src/sevn/tools/base.py). Tools cover workspace file I/O, web search, memory, skills, integrations, sub-agents, and more — with permission gates and lazy caching between turns.

This README separates **registered tool names** (what the model sees) from **module files** (where implementations live — see Level 3).

## Level 2 — How it works (technical)

[`build_session_registry`](../../src/sevn/tools/registry.py#L1569) assembles the session toolset at gateway boot: file ops, web, memory, skills, second-brain wiki tools, code-understanding tools, integration/sandbox bindings, and plugin entry points.

### Registered tool names

| Tool name | Role | Registering module |
| --- | --- | --- |
| `read`, `write`, `edit`, `glob`, `search_in_file`, `delete` | Workspace file I/O | [`file_ops/`](../../src/sevn/tools/file_ops/__init__.py) via [`register_file_ops_tools`](../../src/sevn/tools/file_ops/__init__.py#L68) |
| `serp`, `web_search`, `web_fetch`, `get_page_content` | Web search/fetch | [`web.py`](../../src/sevn/tools/web.py) |
| `spawn_subagent` | Level-1 → level-2 sub-agent spawn | [`subagent_spawn.py`](../../src/sevn/tools/subagent_spawn.py#L107) |
| `integration_call` | Egress-proxied external REST | [`runtime_dispatch.py`](../../src/sevn/tools/runtime_dispatch.py#L295) |
| `sandbox_exec` | Sandboxed command execution | [`runtime_dispatch.py`](../../src/sevn/tools/runtime_dispatch.py) |
| `memory_store`, `memory_get`, `memory_search` | Short-term memory K/V | [`memory_tools.py`](../../src/sevn/tools/memory_tools.py) |
| `load_skill`, `run_skill_script` | Skills subprocess runners | [`skills_register.py`](../../src/sevn/tools/skills_register.py) |
| `log_query`, `semantic_search`, `llm_guard_scan` | Gateway observability / Witchcraft | respective modules under [`src/sevn/tools/`](../../src/sevn/tools/) |

[`runtime_dispatch.py`](../../src/sevn/tools/runtime_dispatch.py): [`IntegrationProxyClient.integration_call`](../../src/sevn/tools/runtime_dispatch.py#L148) dispatches through the egress proxy [`POST /integration`](../../src/sevn/proxy/integration/router.py) route when enabled.

Tools registered **outside** `source_globs` but wired at boot: [`register_code_understanding_tools`](../../src/sevn/code_understanding/tools_register.py) (e.g. legacy [`roam_code_tool`](../../src/sevn/code_understanding/tools_register.py#L228)), [`register_second_brain_tools`](../../src/sevn/second_brain/__init__.py#L562), [`register_openui_tools`](../../src/sevn/ui/openui/tools_register.py).

### Key modules

- [`registry.py`](../../src/sevn/tools/registry.py) — [`build_session_registry`](../../src/sevn/tools/registry.py#L1569), dispatch, caching
- [`decorator.py`](../../src/sevn/tools/decorator.py) — `@sevn_tool` metadata binding
- [`runtime_dispatch.py`](../../src/sevn/tools/runtime_dispatch.py) — integration/sandbox/MCP runtime hooks
- [`permissions.py`](../../src/sevn/tools/permissions.py) — invoke-time permission surfaces
- [`code_understanding/tools_register.py`](../../src/sevn/code_understanding/tools_register.py) — code-orientation tools outside `tools/**` globs

Normative spec: [`11-tools-registry.md`](../../about-sevn.bot/specs/11-tools-registry.md).


## Level 3 — Deep dive (low-level, technical)

Primary source tree: [`src/sevn/tools`](../../src/sevn/tools/) (44 Python files). Normative design: `about-sevn.bot/specs/11-tools-registry.md`.

### Module inventory

Tools registry package (about-sevn.bot/specs/11-tools-registry.md).

Working with [`__init__.py`](../../src/sevn/tools/__init__.py): inspect the public entry points below.

Core registry types: definitions, envelopes, dispatcher (about-sevn.bot/specs/11-tools-registry.md §2-§3).

Implements JSON result envelopes (§3.1), coarse validation, timeouts, tracing hooks,
.llmignore aware spill paths, and non-abortable asyncio.shield wrapping.

Working with [`base.py`](../../src/sevn/tools/base.py): inspect the public entry points below.
Start with [`ToolDefinition.to_dict`](../../src/sevn/tools/base.py#L96), then [`Tool.definition`](../../src/sevn/tools/base.py#L142), [`Tool.execute`](../../src/sevn/tools/base.py#L154), [`enveloped_success`](../../src/sevn/tools/base.py#L236).

sevn-native browser tool — drive host Chrome over CDP (native engine).

A single multi-action @sevn_tool over the :mod:sevn.browser engine: tab CRUD,
navigation, extraction, synthetic click/fill/type, screenshots, cookies, and a gated
eval. Attaches to the operator's Chrome (or spawns one) via the shared
sevn.skills.browser_session lifecycle; recipe actions (Google/Gmail/Telegram/…)
are layered on in later waves.

Working with [`browser.py`](../../src/sevn/tools/browser.py): inspect the public entry points below.
Start with [`set_eval_allowed`](../../src/sevn/tools/browser.py#L1002), then [`browser_tool`](../../src/sevn/tools/browser.py#L1032), [`register_browser_tool`](../../src/sevn/tools/browser.py#L1225).

Per-session lazy payload cache keyed by registry generation (about-sevn.bot/specs/11-tools-registry.md §3.2).

Uses a bounded OrderedDict eviction policy (FIFO) with configurable capacity.

Working with [`cache.py`](../../src/sevn/tools/cache.py): inspect the public entry points below.
Start with [`LoadedBodyCache.get`](../../src/sevn/tools/cache.py#L48), then [`LoadedBodyCache.set`](../../src/sevn/tools/cache.py#L73), [`LoadedBodyCache.clear`](../../src/sevn/tools/cache.py#L99).

Normative ToolResult JSON code field values (about-sevn.bot/specs/11-tools-registry.md §3.1).

Extend this enum rather than scattering string literals across tools and adapters.

Working with [`codes.py`](../../src/sevn/tools/codes.py): inspect the public entry points below.

coding_agent_invoke tier-B/C tool — invoke a bound coding agent (CA6.1 + CA6.4).

Working with [`coding_agent_invoke.py`](../../src/sevn/tools/coding_agent_invoke.py): inspect the public entry points below.
Start with [`coding_agent_invoke_tool`](../../src/sevn/tools/coding_agent_invoke.py#L69), then [`register_coding_agent_invoke_tool`](../../src/sevn/tools/coding_agent_invoke.py#L294), [`coding_agent_invoke`](../../src/sevn/tools/coding_agent_invoke.py#L313).

Framework-agnostic runtime passed into every @sevn_tool body (about-sevn.bot/specs/11-tools-registry.md §2.3).

Hosts session identifiers, filesystem roots, tracing, and coarse permission gates. Optional
handles stay None until gateway/sandbox/channel wiring lands.

Working with [`context.py`](../../src/sevn/tools/context.py): inspect the public entry points below.

Declarative @sevn_tool metadata binding (about-sevn.bot/specs/11-tools-registry.md §2.3).

Stores a finalized ToolDefinition on callable objects so gateways can iterate
registration tables without duplicated dictionaries.

Working with [`decorator.py`](../../src/sevn/tools/decorator.py): inspect the public entry points below.
Start with [`sevn_tool`](../../src/sevn/tools/decorator.py#L41), then [`tool_from_decorated`](../../src/sevn/tools/decorator.py#L125).

Setuptools sevn.tools entry-point group (about-sevn.bot/specs/11-tools-registry.md §2.8).

Third-party packages register Tool factories under [project.entry-points."sevn.tools"].
The core wheel ships a no-op row so the entry-point table validates under uv build.

Working with [`entrypoints.py`](../../src/sevn/tools/entrypoints.py): inspect the public entry points below.
Start with [`reserved_plugin_row`](../../src/sevn/tools/entrypoints.py#L20).

Agent tool for filing evolution issues (about-sevn.bot/specs/35-bot-evolution.md EV-4).

Working with [`evolution_issues.py`](../../src/sevn/tools/evolution_issues.py): inspect the public entry points below.
Start with [`file_evolution_issue_tool`](../../src/sevn/tools/evolution_issues.py#L80), then [`register_evolution_issue_tools`](../../src/sevn/tools/evolution_issues.py#L128).

Workspace file operation tools (about-sevn.bot/plan/tools-skills-full-inventory-wave-plan.md Wave 1-3).

Working with [`__init__.py`](../../src/sevn/tools/file_ops/__init__.py): inspect the public entry points below.
Start with [`register_file_ops_tools`](../../src/sevn/tools/file_ops/__init__.py#L68).

Workspace delete tool with human gate (about-sevn.bot/specs/11-tools-registry.md §8).

Working with [`delete.py`](../../src/sevn/tools/file_ops/delete.py): inspect the public entry points below.
Start with [`delete_tool`](../../src/sevn/tools/file_ops/delete.py#L58).

32 more Python files under [`src/sevn/tools`](../../src/sevn/tools/) — including `src/sevn/tools/file_ops/docstrings.py`, `src/sevn/tools/file_ops/graphify_result_prefix.py`, `src/sevn/tools/file_ops/list_glob.py`, `src/sevn/tools/file_ops/read.py`.

### Extension and invariants

Follow [`11-tools-registry.md`](../../about-sevn.bot/specs/11-tools-registry.md) for merge gates, error semantics, and compatibility constraints. After code changes under [`src/sevn/tools`](../../src/sevn/tools/), run `sevn readme update tools` and `make readme-check`.

## References

- [../../about-sevn.bot/specs/11-tools-registry.md](../../about-sevn.bot/specs/11-tools-registry.md)

[spec-badge]: https://img.shields.io/badge/Spec-2a7fc6?style=for-the-badge&logo=readthedocs&logoColor=white
[spec-link]: ../../about-sevn.bot/specs/11-tools-registry.md
[source-badge]: https://img.shields.io/badge/Source-0c0a09?style=for-the-badge&logo=github&logoColor=white
[source-link]: ../../src/sevn/tools/
[index-badge]: https://img.shields.io/badge/All_READMEs-5fb1f7?style=for-the-badge&logo=markdown&logoColor=white
[index-link]: INDEX.md
