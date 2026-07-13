<!-- generated: do not edit by hand; run `sevn readme update tools` -->
# Tools registry

> **Summary.** Curated inventory of @sevn_tool plugins, adapters, and permission gates.

| Name | Path | Summary |
|------|------|---------|
| `__init__` | [`../../src/sevn/tools/__init__.py`](../../src/sevn/tools/__init__.py) | Tools registry package ('about-sevn.bot/specs/11-tools-registry.md'). |
| `base` | [`../../src/sevn/tools/base.py`](../../src/sevn/tools/base.py) | Core registry types: definitions, envelopes, dispatcher ('about-sevn.bot/specs/11-tools-registry.md' §2-§3). |
| `browser` | [`../../src/sevn/tools/browser.py`](../../src/sevn/tools/browser.py) | sevn-native ''browser'' tool — drive host Chrome over CDP (native engine). |
| `cache` | [`../../src/sevn/tools/cache.py`](../../src/sevn/tools/cache.py) | Per-session lazy payload cache keyed by registry generation ('about-sevn.bot/specs/11-tools-registry.md' §3.2). |
| `codes` | [`../../src/sevn/tools/codes.py`](../../src/sevn/tools/codes.py) | Normative ''ToolResult'' JSON ''code'' field values ('about-sevn.bot/specs/11-tools-registry.md' §3.1). |
| `coding_agent_invoke` | [`../../src/sevn/tools/coding_agent_invoke.py`](../../src/sevn/tools/coding_agent_invoke.py) | ''coding_agent_invoke'' tier-B/C tool — invoke a bound coding agent (CA6.1 + CA6.4). |
| `context` | [`../../src/sevn/tools/context.py`](../../src/sevn/tools/context.py) | Framework-agnostic runtime passed into every '@sevn_tool' body ('about-sevn.bot/specs/11-tools-registry.md' §2.3). |
| `decorator` | [`../../src/sevn/tools/decorator.py`](../../src/sevn/tools/decorator.py) | Declarative '@sevn_tool' metadata binding ('about-sevn.bot/specs/11-tools-registry.md' §2.3). |
| `entrypoints` | [`../../src/sevn/tools/entrypoints.py`](../../src/sevn/tools/entrypoints.py) | Setuptools ''sevn.tools'' entry-point group ('about-sevn.bot/specs/11-tools-registry.md' §2.8). |
| `evolution_issues` | [`../../src/sevn/tools/evolution_issues.py`](../../src/sevn/tools/evolution_issues.py) | Agent tool for filing evolution issues ('about-sevn.bot/specs/35-bot-evolution.md' EV-4). |
| `__init__` | [`../../src/sevn/tools/file_ops/__init__.py`](../../src/sevn/tools/file_ops/__init__.py) | Workspace file operation tools ('the design docs' Wave 1-3). |
| `delete` | [`../../src/sevn/tools/file_ops/delete.py`](../../src/sevn/tools/file_ops/delete.py) | Workspace ''delete'' tool with human gate ('about-sevn.bot/specs/11-tools-registry.md' §8). |
| `docstrings` | [`../../src/sevn/tools/file_ops/docstrings.py`](../../src/sevn/tools/file_ops/docstrings.py) | AST-backed docstring/symbol helpers for workspace Python files. |
| `graphify_result_prefix` | [`../../src/sevn/tools/file_ops/graphify_result_prefix.py`](../../src/sevn/tools/file_ops/graphify_result_prefix.py) | Graphify search-tool prefix injection ('about-sevn.bot/specs/28-code-understanding.md' §2.5). |
| `list_glob` | [`../../src/sevn/tools/file_ops/list_glob.py`](../../src/sevn/tools/file_ops/list_glob.py) | Directory listing, glob, find, and metadata tools ('about-sevn.bot/specs/11-tools-registry.md' §4.3). |
| `read` | [`../../src/sevn/tools/file_ops/read.py`](../../src/sevn/tools/file_ops/read.py) | Line-numbered ''read'' tool for workspace files and directories ('about-sevn.bot/specs/11-tools-registry.md' §4.3). |
| `search` | [`../../src/sevn/tools/file_ops/search.py`](../../src/sevn/tools/file_ops/search.py) | Ripgrep-backed ''search_in_file'' tool ('about-sevn.bot/specs/11-tools-registry.md' §4.3). |
| `write` | [`../../src/sevn/tools/file_ops/write.py`](../../src/sevn/tools/file_ops/write.py) | Mutating workspace file tools except ''delete'' ('about-sevn.bot/specs/11-tools-registry.md' §4.3). |
| `integration_classifier` | [`../../src/sevn/tools/integration_classifier.py`](../../src/sevn/tools/integration_classifier.py) | Heuristics for ''integration_call'' abortability toggles ('about-sevn.bot/specs/11-tools-registry.md' §8). |
| `integration_gh_repo` | [`../../src/sevn/tools/integration_gh_repo.py`](../../src/sevn/tools/integration_gh_repo.py) | Legacy ''gh_repo_*'' aliases mapped to :func:'integration_call' payloads ('about-sevn.bot/specs/11-tools-registry.md' §4.1). |
| `integration_proxy_client` | [`../../src/sevn/tools/integration_proxy_client.py`](../../src/sevn/tools/integration_proxy_client.py) | Egress-paired ''/integration'' client for gateway ''integration_call'' (Wave W2). |
| `llm_guard_tool` | [`../../src/sevn/tools/llm_guard_tool.py`](../../src/sevn/tools/llm_guard_tool.py) | Manual LLM Guard scan tool ('the design docs' Wave 7). |
| `log_query` | [`../../src/sevn/tools/log_query.py`](../../src/sevn/tools/log_query.py) | Gateway log read/filter tool ('the design docs' Wave 7). |
| `mcp_stdio_client` | [`../../src/sevn/tools/mcp_stdio_client.py`](../../src/sevn/tools/mcp_stdio_client.py) | Concrete stdio MCP client implementing :class:'McpStdioClient' ('about-sevn.bot/specs/11-tools-registry.md' §2.7, §10.2). |
| `memory_tools` | [`../../src/sevn/tools/memory_tools.py`](../../src/sevn/tools/memory_tools.py) | Short-term memory K/V tools and federated search ('the design docs' Wave 4). |
| `meta_escalation` | [`../../src/sevn/tools/meta_escalation.py`](../../src/sevn/tools/meta_escalation.py) | Tier-only escalation tool ('about-sevn.bot/specs/14-executor-tier-b.md' §2.4). |
| `meta_loaders` | [`../../src/sevn/tools/meta_loaders.py`](../../src/sevn/tools/meta_loaders.py) | Load meta tools attaching lazy bodies ('about-sevn.bot/specs/11-tools-registry.md' §2.4). |
| `outbound` | [`../../src/sevn/tools/outbound.py`](../../src/sevn/tools/outbound.py) | Outbound messaging and media tools ('the design docs' Wave 6). |
| `paths` | [`../../src/sevn/tools/paths.py`](../../src/sevn/tools/paths.py) | Path helpers rejecting ''.llmignore/'' realpaths ('about-sevn.bot/specs/11-tools-registry.md' §4.3). |
| `permissions` | [`../../src/sevn/tools/permissions.py`](../../src/sevn/tools/permissions.py) | Minimal permission surfaces for invoke-time gating ('about-sevn.bot/specs/11-tools-registry.md' §8). |
| `process` | [`../../src/sevn/tools/process.py`](../../src/sevn/tools/process.py) | Background process management tool ('the design docs' Wave 8). |
| `readiness` | [`../../src/sevn/tools/readiness.py`](../../src/sevn/tools/readiness.py) | Tool readiness hints for registry surfaces and error envelopes (Wave W6 / W1). |
| `registry` | [`../../src/sevn/tools/registry.py`](../../src/sevn/tools/registry.py) | Session-scoped ''ToolSet'' snapshots + staged registration helpers ('about-sevn.bot/specs/11-tools-registry.md' §4). |
| `runtime_bindings_factory` | [`../../src/sevn/tools/runtime_bindings_factory.py`](../../src/sevn/tools/runtime_bindings_factory.py) | Single gateway-boot factory for :class:'~sevn.tools.runtime_dispatch.RuntimeToolBindings'. |
| `runtime_dispatch` | [`../../src/sevn/tools/runtime_dispatch.py`](../../src/sevn/tools/runtime_dispatch.py) | Runtime hooks wiring ''integration_call'' / ''sandbox_exec'' / MCP stdio ('about-sevn.bot/specs/11-tools-registry.md' §4.1, §4.2, §10.1). |
| `semantic_search` | [`../../src/sevn/tools/semantic_search.py`](../../src/sevn/tools/semantic_search.py) | Witchcraft semantic search tool ('the design docs' Wave 7). |
| `skills_register` | [`../../src/sevn/tools/skills_register.py`](../../src/sevn/tools/skills_register.py) | Register skill tools backed by :class:'SkillsManager' ('about-sevn.bot/specs/11-tools-registry.md' §2.4-§2.5). |
| `spill_gc` | [`../../src/sevn/tools/spill_gc.py`](../../src/sevn/tools/spill_gc.py) | Best-effort cleanup for ''.sevn/tool_results/'' trees ('about-sevn.bot/specs/11-tools-registry.md' §3.1). |
| `subagent_spawn` | [`../../src/sevn/tools/subagent_spawn.py`](../../src/sevn/tools/subagent_spawn.py) | ''spawn_subagent'' — level-1 → level-2 sub-agent spawn tool (D9, 'about-sevn.bot/specs/36-sub-agents.md'). |
| `terminal` | [`../../src/sevn/tools/terminal.py`](../../src/sevn/tools/terminal.py) | Persistent terminal session tools ('the design docs' Wave 8). |
| `transcript` | [`../../src/sevn/tools/transcript.py`](../../src/sevn/tools/transcript.py) | Always-available session history tools for the current gateway session. |
| `validation` | [`../../src/sevn/tools/validation.py`](../../src/sevn/tools/validation.py) | Minimal JSON Schema object validation for adapter-bound arguments ('about-sevn.bot/specs/11-tools-registry.md' §6). |
| `web` | [`../../src/sevn/tools/web.py`](../../src/sevn/tools/web.py) | Web search and fetch tools ('the design docs' Wave 5). |
| `workspace_files` | [`../../src/sevn/tools/workspace_files.py`](../../src/sevn/tools/workspace_files.py) | Bootstrap-safe workspace markdown writes ('the design docs' Wave 3). |
