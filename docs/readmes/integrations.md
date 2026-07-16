<!-- generated: do not edit by hand; run `sevn readme update integrations` -->
# Integrations — Cursor Cloud, GitHub skill clients, and external integration call paths

[![Spec][spec-badge]][spec-link]
[![Source][source-badge]][source-link]
[![Index][index-badge]][index-link]

> **Summary.** Cursor Cloud, GitHub skill clients, and external integration call paths.

## Level 1 — Overview (non-technical)

**Integrations** is a core part of sevn.bot — the personal AI assistant you run on your own machine. Cursor Cloud, GitHub skill clients, and external integration call paths.

In everyday use, integrations helps Sevn do its job reliably: you interact through familiar channels (Telegram, browser, voice), and this layer keeps those interactions safe, consistent, and under your control.

## Level 2 — How it works (technical)

### Components and layout

Implementation lives under `src/sevn/integrations/`. The package contains 27 Python module(s); primary entry points include `src/sevn/integrations/__init__.py`, `src/sevn/integrations/code_graph_rag/__init__.py`, `src/sevn/integrations/cursor_cloud/__init__.py`, `src/sevn/integrations/cursor_cloud/client.py`, `src/sevn/integrations/cursor_cloud/config.py`, `src/sevn/integrations/cursor_cloud/errors.py`, and 21 more.

### Data and control flow

Integrations is organized around `  init  `, `  init  `, `  init  `, `client`, and 2 more under `src/sevn/integrations/` with 27 Python module(s) in the scanned tree. Primary entry points include client.py (create_cloud_agent), config.py (load_cursor_cloud_settings), jobs.py (insert_job), client.py (parse_github_repo).

### Configuration

Operator settings come from `sevn.json` in the workspace. Related normative specs: `about-sevn.bot/specs/29-cursor-cloud-agent.md`. Run `sevn config validate` after edits; use `sevn doctor` to confirm the install sees the expected layout.

### Key modules

- `src/sevn/integrations/cursor_cloud/client.py` — `create_cloud_agent`, `get_agent`, `get_run`, `list_artifacts`
- `src/sevn/integrations/cursor_cloud/config.py` — `load_cursor_cloud_settings`
- `src/sevn/integrations/cursor_cloud/jobs.py` — `insert_job`, `get_job`, `update_job`, `list_workspace_jobs`
- `src/sevn/integrations/github_skill/client.py` — `parse_github_repo`, `github_integration_call`, `github_integration_call_sync`, `github_legacy_call`
- `src/sevn/integrations/github_skill/gh_issues.py` — `list_issues`, `view_issue`, `create_issue`, `comment_on_issue`

### Spec context

From about-sevn.bot/specs/29-cursor-cloud-agent.md:
Let operators and agents launch, poll, and inspect Cursor Cloud Agents against any GitHub/GitLab repo when skills.cursor_cloud.enabled is true, returning PR URLs, dashboard links (remote desktop), and

Let operators and agents launch, poll, and inspect Cursor Cloud Agents against any GitHub/GitLab repo when skills.cursor_cloud.enabled is true, returning PR URLs, dashboard links (remote desktop), and

Primary code trees: `src/sevn/integrations/`.

Initial draft for **Purpose** — grounded in extracted interfaces; confirm normative wording.

<!-- HUMAN-INPUT[owner=operator]: Product/normative contract for Purpose — acceptance criteria and edge cases.

## Level 3 — Deep dive (low-level, technical)

Primary source tree: [`src/sevn/integrations`](../../src/sevn/integrations/) (27 Python files). Normative design: [`29-cursor-cloud-agent.md`](../../about-sevn.bot/specs/29-cursor-cloud-agent.md).

### Module inventory

External system integrations (scaffold).

Working with [`__init__.py`](../../src/sevn/integrations/__init__.py): inspect the public entry points below.

Optional CGR integration package root (about-sevn.bot/specs/28-code-understanding.md §4.2).

Memgraph clients, export daemons, and vendor packaging are expected to live
here once the code-graph-rag optional extra ships. The stable library surface
for argv caps and export truncation remains sevn.code_understanding.cgr_adapter.

Working with [`__init__.py`](../../src/sevn/integrations/code_graph_rag/__init__.py): inspect the public entry points below.

Cursor Cloud Agent integration for bundled cursor_cloud skill.

Working with [`__init__.py`](../../src/sevn/integrations/cursor_cloud/__init__.py): inspect the public entry points below.

Cursor Cloud Agents API client via egress proxy.

Working with [`client.py`](../../src/sevn/integrations/cursor_cloud/client.py): inspect the public entry points below.
Start with [`create_cloud_agent`](../../src/sevn/integrations/cursor_cloud/client.py#L62), then [`get_agent`](../../src/sevn/integrations/cursor_cloud/client.py#L141), [`get_run`](../../src/sevn/integrations/cursor_cloud/client.py#L162), [`list_artifacts`](../../src/sevn/integrations/cursor_cloud/client.py#L184).

Workspace config helpers for cursor_cloud skill.

Working with [`config.py`](../../src/sevn/integrations/cursor_cloud/config.py): inspect the public entry points below.
Start with [`load_cursor_cloud_settings`](../../src/sevn/integrations/cursor_cloud/config.py#L61).

Stable error codes for Cursor cloud integration.

Working with [`errors.py`](../../src/sevn/integrations/cursor_cloud/errors.py): inspect the public entry points below.

SQLite persistence for Cursor cloud agent jobs.

Working with [`jobs.py`](../../src/sevn/integrations/cursor_cloud/jobs.py): inspect the public entry points below.
Start with [`insert_job`](../../src/sevn/integrations/cursor_cloud/jobs.py#L132), then [`get_job`](../../src/sevn/integrations/cursor_cloud/jobs.py#L213), [`update_job`](../../src/sevn/integrations/cursor_cloud/jobs.py#L253), [`list_workspace_jobs`](../../src/sevn/integrations/cursor_cloud/jobs.py#L331).

GitHub bundled skill helpers — REST via integration_call proxy.

Working with [`__init__.py`](../../src/sevn/integrations/github_skill/__init__.py): inspect the public entry points below.

Shared GitHub skill helpers — repo parsing and integration dispatch.

Working with [`client.py`](../../src/sevn/integrations/github_skill/client.py): inspect the public entry points below.
Start with [`parse_github_repo`](../../src/sevn/integrations/github_skill/client.py#L29), then [`github_integration_call`](../../src/sevn/integrations/github_skill/client.py#L67), [`github_integration_call_sync`](../../src/sevn/integrations/github_skill/client.py#L108), [`github_legacy_call`](../../src/sevn/integrations/github_skill/client.py#L138).

Issue operations for bundled gh-issues skill scripts.

Working with [`gh_issues.py`](../../src/sevn/integrations/github_skill/gh_issues.py): inspect the public entry points below.
Start with [`list_issues`](../../src/sevn/integrations/github_skill/gh_issues.py#L27), then [`view_issue`](../../src/sevn/integrations/github_skill/gh_issues.py#L64), [`create_issue`](../../src/sevn/integrations/github_skill/gh_issues.py#L99), [`comment_on_issue`](../../src/sevn/integrations/github_skill/gh_issues.py#L145).

Pull request operations for bundled gh-pr skill scripts.

Working with [`gh_pr.py`](../../src/sevn/integrations/github_skill/gh_pr.py): inspect the public entry points below.
Start with [`list_pull_requests`](../../src/sevn/integrations/github_skill/gh_pr.py#L25), then [`view_pull_request`](../../src/sevn/integrations/github_skill/gh_pr.py#L69), [`create_pull_request`](../../src/sevn/integrations/github_skill/gh_pr.py#L109), [`merge_pull_request`](../../src/sevn/integrations/github_skill/gh_pr.py#L166).

GitHub manager operations for bundled github-manager skill scripts.

Working with [`github_manager.py`](../../src/sevn/integrations/github_skill/github_manager.py): inspect the public entry points below.
Start with [`list_branches`](../../src/sevn/integrations/github_skill/github_manager.py#L32), then [`create_branch`](../../src/sevn/integrations/github_skill/github_manager.py#L67), [`delete_branch`](../../src/sevn/integrations/github_skill/github_manager.py#L112), [`list_workflows`](../../src/sevn/integrations/github_skill/github_manager.py#L150).

15 more Python files under [`src/sevn/integrations`](../../src/sevn/integrations/) — including `src/sevn/integrations/github_skill/hooks.py`, `src/sevn/integrations/litellm_lap/__init__.py`, `src/sevn/integrations/litellm_lap/client.py`, `src/sevn/integrations/proxy_client.py`.

### Extension and invariants

Follow [`29-cursor-cloud-agent.md`](../../about-sevn.bot/specs/29-cursor-cloud-agent.md) for merge gates, error semantics, and compatibility constraints. After code changes under [`src/sevn/integrations`](../../src/sevn/integrations/), run `sevn readme update integrations` and `make readme-check`.

## References

- [../../about-sevn.bot/specs/29-cursor-cloud-agent.md](../../about-sevn.bot/specs/29-cursor-cloud-agent.md)

[spec-badge]: https://img.shields.io/badge/Spec-2a7fc6?style=for-the-badge&logo=readthedocs&logoColor=white
[spec-link]: ../../about-sevn.bot/specs/29-cursor-cloud-agent.md
[source-badge]: https://img.shields.io/badge/Source-0c0a09?style=for-the-badge&logo=github&logoColor=white
[source-link]: ../../src/sevn/integrations/
[index-badge]: https://img.shields.io/badge/All_READMEs-5fb1f7?style=for-the-badge&logo=markdown&logoColor=white
[index-link]: INDEX.md
