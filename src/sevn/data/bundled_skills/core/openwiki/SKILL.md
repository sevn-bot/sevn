---
name: openwiki
description: LLM-generated agent wiki for a codebase (LangChain OpenWiki CLI).
version: "0.1.0"
max_wall_seconds: 3600
see_also:
  - mycode
  - graphify
egress:
  - openrouter.ai
  - api.openai.com
  - api.anthropic.com
  - api.fireworks.ai
  - inference.baseten.co
scripts:
  - path: scripts/generate.py
    description: Generate or update OpenWiki docs non-interactively (`--init`, `--update`, or chat).
    args_overview: "--mode init|update|chat [--root PATH] [--message TEXT] [--model-id ID] [--dry-run]"
    abortable: true
  - path: scripts/status.py
    description: Report whether `openwiki/` exists and last-update metadata.
    args_overview: "[--root PATH]"
---

# openwiki skill

Use when the operator wants **LLM-maintained agent documentation** for a codebase —
narrative wiki pages under `openwiki/` that stay aligned with repository changes.

Prefer **`mycode`** for deterministic symbol/file scans (no LLM), and **`graphify`**
for architecture-level module graphs. Use **openwiki** when prose documentation,
onboarding guides, or agent-oriented wiki pages are the goal.

## Prerequisites (operator)

1. **Node >= 20** on the gateway host (`node --version`).
2. Install the upstream CLI: `sevn openwiki install` (or `npm install -g openwiki`).
3. **Store LLM credentials in sevn secrets** (not a host `~/.openwiki/.env` file):

   ```bash
   sevn openwiki configure --stdin
   ```

4.    Reference the secret in workspace `sevn.json`:

   ```json
   {
     "skills": {
       "openwiki": {
         "enabled": true,
         "provider": "openrouter",
         "model_id": "z-ai/glm-5.2",
         "api_key": "${SECRET:integration.openwiki.llm_api_key}"
       }
     }
   }
   ```

   **Auto-map:** When `api_key` is omitted, sevn forwards the API key from your
   **assigned LLM provider** (`providers.<name>.api_key` / `SEVN_SECRET_*`) when
   that provider is OpenWiki-compatible (`openrouter`, `openai`, `anthropic`,
   `fireworks`, `baseten`). You can also set `"api_key": "${SECRET:SEVN_SECRET_OPENROUTER}"`
   explicitly.

   The gateway resolves `${SECRET:…}` refs and forwards provider/model/API keys into
   the OpenWiki subprocess environment. You can also set per-provider refs under
   `skills.openwiki.api_keys.*` or reuse assigned provider secrets such as
   `${SECRET:SEVN_SECRET_OPENROUTER}`.

5. Enable in workspace config: `skills.openwiki.enabled: true`.

## sevn execution model

1. `load_skill("openwiki")` — read this contract.
2. `run_skill_script(skill_name="openwiki", script_path="status", args=[])` — check
   whether `openwiki/` already exists before spending LLM tokens.
3. When generation is needed:
   - **First run:** `script_path="generate", args=["--mode", "init"]`
   - **Refresh:** `script_path="generate", args=["--mode", "update"]`
   - **Custom prompt:** `script_path="generate", args=["--mode", "chat", "--message", "..."]`
4. Read generated pages from the wiki directory (see **Paths** below) with normal
   workspace `read` — do not re-run generation on every turn.

Pass `--dry-run` or set `SEVN_OPENWIKI_DRY_RUN=1` to inspect the argv plan without
calling the CLI.

## Paths

- Default repository root: **`source_code/`** when the workspace mirror exists;
  otherwise the workspace content root.
- Wiki output: **`<root>/openwiki/`** (markdown pages).
- Last-update metadata: **`<root>/openwiki/.last-update.json`** when present.
- In a typical sevn workspace, read pages at `source_code/openwiki/`.

OpenWiki may also append guidance to `AGENTS.md` and/or `CLAUDE.md` under the repo
root when it runs — that is upstream behavior.

## Error envelopes

| Code | Meaning |
|------|---------|
| `DEPENDENCY_MISSING` | `openwiki` npm CLI not on PATH |
| `CREDENTIALS_MISSING` | LLM provider keys not configured via sevn secrets / `skills.openwiki.api_key` |
| `BUILD_FAILED` | CLI exited nonzero |
| `VALIDATION_ERROR` | Invalid script arguments |

## Optional automation

Upstream ships a daily GitHub Actions workflow example:
https://github.com/langchain-ai/openwiki/blob/main/examples/openwiki-update.yml

Operators can copy it into `.github/workflows/` for scheduled wiki PRs outside the
gateway.

## Upstream

- Repository: https://github.com/langchain-ai/openwiki
- Install: `npm install -g openwiki`
