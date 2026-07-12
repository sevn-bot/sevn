---
name: sevn-diagnostics
description: >-
  sevn.bot operator repair playbooks for `sevn doctor --with-agent`: gateway token,
  secrets store unlock, proxy health, model auth, browser/CDP, and voice backends.
  Uses the bundled solutions catalog — do not duplicate remediation text here.
version: "1.0.0"
see_also:
  - conventional_commit
  - telegram_test
---

# sevn-diagnostics skill

Playbooks for the CLI **diagnostic agent** invoked by `sevn doctor --with-agent`.
The W3 **solutions catalog** (`doctor_solutions.json`) is injected into your context —
cite catalog `remediation[]` rows and prefer `auto_fixable` checks for `auto_fix` steps.

## Investigation order

1. Read the doctor report JSON (failing/warn `check_id` rows).
2. Pull matching catalog entries for explanation + remediation.
3. Use **read-only** tools: `diagnostics_log_query`, `diagnostics_config_show`,
   `diagnostics_gateway_get`, `diagnostics_read_file`, `diagnostics_run_sevn`.
4. Emit a **DiagnosticPlan** with ordered steps — highest severity / blocking issues first.

## Allowlisted read-only CLI (investigation)

| Command | When |
|---------|------|
| `sevn doctor --json` | Refresh machine report after a fix |
| `sevn gateway status` | Gateway listen + health when `gateway_*` checks fail |
| `sevn proxy status` | Proxy `/healthz` when `proxy_healthz` fails |
| `sevn config show` | Validate `sevn.json` layout / token refs |
| `sevn config validate` | Schema validation failures |
| `sevn secrets list` / `sevn secrets status` | Encrypted store / keychain unlock |

## Apply steps (orchestrator confirms — do not run mutating tools yourself)

| Issue class | Typical apply command |
|-------------|----------------------|
| Stale operator lock, `.llmignore`, WAL, legacy secrets, broken symlink | `action_type: auto_fix` (whitelist via `sevn doctor --fix --yes`) |
| Catalog `fix_command` | `action_type: sevn_command` with exact allowlisted string |
| Provider auth, Telegram pairing, manual infra | `action_type: manual` with numbered operator steps |

## Topic playbooks

### Gateway token / health (`gateway_token_configured`, `gateway_health`, `gateway_ready`)

- Confirm `gateway.token` resolves (not literal `${SECRET:…}` in output).
- `sevn gateway status` — if down, operator starts gateway (`make compose-up` / launchd).
- Re-run `sevn doctor --json` after gateway is listening.

### Secrets backend / keychain (`secrets_backend`, `keychain_unlock`)

- `sevn secrets status` — store readable? keychain unlocked?
- Legacy plaintext: propose `sevn doctor --fix --yes` when catalog marks `auto_fixable`.
- macOS: operator unlocks login keychain; Linux: libsecret collection available.

### Proxy (`proxy_healthz`, `llm_reachability`)

- `sevn proxy status` — conflict vs absent vs healthy.
- Inspect `logs/proxy.log` via `diagnostics_log_query`.
- When proxy down, LLM reachability may fail downstream — fix proxy first.

### Browser / CDP (`browser_extra`, `browser_cdp_engine`)

- Read doctor detail for missing extras (`uv sync --extra browser` / `uv sync --extra browser-cdp`).
- Headed Chrome required for onboarding web wizard — not inside gateway Docker.

### Voice (`voice_backends`)

- Check `sevn.json` `voice.*` providers and optional local TTS/STT installs.
- Doctor probe enumerates backend failures — manual install steps in catalog.

## Output contract

Return **DiagnosticPlan** only:

- `summary` — one paragraph for the operator.
- `steps[]` — each with `check_ids`, `title`, `action_type`, optional `command`, `explanation`.
- Never propose raw shell, `curl`, or file writes — mutations go through confirmed `sevn` apply paths.
