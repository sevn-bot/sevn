---
name: hermes-model-eval
description: >-
  Advisory cross-model eval on the golden_llm harness — compare Hermes 4 and other
  configured aliases for tool-call reliability, coding, summarization, and policy/approval
  scenarios. Results inform routing; they never change defaults (D9).
version: "1.0.0"
see_also:
  - sevn-diagnostics
  - skill_management
scripts:
  - path: scripts/_common.py
    description: Shared JSON envelope helpers and workspace binding.
    args_overview: "(library module — not invoked directly)"
  - path: scripts/list_suite.py
    description: List fixed eval suite cases grouped by scenario class.
    args_overview: "(no args)"
  - path: scripts/replay_report.py
    description: Tokenless replay comparison via golden_llm pydantic-evals (CI-safe).
    args_overview: "[--case-id ID ...]"
  - path: scripts/compare_models.py
    description: Live cross-model comparison (requires SEVN_HERMES_MODEL_EVAL=1 + proxy keys).
    args_overview: "[--case-id ID ...]"
---

# hermes-model-eval skill

Advisory workflow to compare configured models (including Hermes 4 aliases) on the
fixed **golden_llm** tier-B eval suite. Built for [#91](https://github.com/sevn-bot/sevn/issues/91).

## D21 operator gate (recorded)

`scripts/spy_hermes.py` and `make spy-hermes-*` are **absent** from this checkout.
This skill uses `tests/fixtures/golden_llm/` only — no upstream spy_hermes tooling.

## Scenario classes

| Class | Cases | What it exercises |
| --- | --- | --- |
| `tool_call` | `read_01`, `glob_01` | Native tool selection and success |
| `coding` | `edit_01`, `composite_write_read_01` | Workspace edits and multi-tool coding |
| `summarization` | `summarize_01` | Read + concise summary |
| `policy_approval` | `policy_approval_01` | Registry/policy awareness |

Entry point for tokenless CI replay: `make golden-llm-ci`.

## Configuration (default off — D9)

Enable in `sevn.json` when you want the skill exposed to the agent:

```json
{
  "skills": {
    "hermes_model_eval": {
      "enabled": true,
      "models": [
        { "label": "tier_b_default", "model_id": "openai/gpt-4o-mini" },
        { "label": "hermes_4", "model_id": "openrouter/nousresearch/hermes-4-70b" }
      ]
    }
  }
}
```

Hermes aliases are **provider-agnostic catalog ids** — configure per your provider
(`openrouter/…`, `together/…`, local proxy aliases, etc.). Empty `models` falls
back to the workspace tier-B default for baseline comparison.

Results are **advisory only** — they do not mutate routing defaults.

## Scripts

List the fixed suite:

```bash
python scripts/list_suite.py
```

Tokenless replay report (no API keys):

```bash
python scripts/replay_report.py
```

Live cross-model matrix (operator opt-in):

```bash
export SEVN_HERMES_MODEL_EVAL=1
python scripts/compare_models.py
```

Live runs require a reachable egress proxy (`SEVN_PROXY_URL`) and provider keys.
Reports include pass rates, latency, and token usage where the transport returns them.
