---
name: telegram_test
description: >-
  Run host-side Playwright Telegram E2E (sevn telegram-test) while building sevn.bot.
  Use after gateway/menu/session/diagnostics changes. Not in gateway container.
version: "1.0.0"
see_also:
  - telegram
  - browser-harness
  - playwright-browser
---

# telegram_test skill

**Canonical developer guide:** `docs/telegram-e2e-developer-guide.md` (repo root).

Run the **session** Playwright suite against Telegram Web K on the **operator host**
(developer laptop or CI machine with Docker + browser). Validates real inline keyboards and
slash commands — not unit-test mocks.

## When to run

- After edits to gateway menu, Session toggles, queue mode, deployment id, `/logs` `/traces`,
  or `/config` Logs section.
- When the user asks to “run the session suite” or “telegram e2e”.
- After fixing regressions where “/config buttons do nothing”.

## Prerequisites

1. Repo checkout at `SEVN_REPO_ROOT` or cwd.
2. `uv sync --extra dev` and `playwright install chromium`.
3. `.env` with `SEVN_TELEGRAM_BOT_TOKEN`, `OPENAI_API_KEY`, `TG_TARGET_BOT`.
4. Local target: `make compose-up`, onboard (see developer guide), `/ready` OK.
5. `sevn telegram-test login` once per machine (exit **7** if session expired).

## Commands

| Command | Purpose |
|---------|---------|
| `sevn telegram-test login` | QR login; profile `tools/telegram-tester/.browser-profile/` |
| `sevn telegram-test list` | `session` |
| `sevn telegram-test run session --target local --json` | Full suite + JSON report |
| `sevn telegram-test run session --target prod --json` | Remote bot; no compose override |
| `sevn telegram-test status --json` | Last `artifacts/session-latest.json` |
| `make telegram-e2e` | Shorthand for local session run |

## JSON report (`--json`)

Fields to summarize for the user:

- `deployment_id_observed` — from `/status`
- `tests[]` — `name`, `status` (`passed`/`failed`/`skipped`), `message`
- `artifacts_dir` — failure screenshots/traces
- `target` — `local` or `prod`

## Exit codes

| Code | Action |
|------|--------|
| `0` | All tests passed |
| `1` | One or more tests failed — inspect JSON |
| `7` | Run `sevn telegram-test login` |
| `2` | Fix CLI arguments |
| `4` | Run `uv sync --extra dev` or start compose / run a suite before `status` |

## Host only

Never run from `sevn-gateway` Docker. Tester lives in `tools/telegram-tester/` (uv workspace
member), not in `Dockerfile.gateway`.

## Agent procedure (step by step)

1. Confirm working directory is repo root.
2. Optional: `make ci` for fast unit gate.
3. `sevn telegram-test run session --target local --json` (capture stdout).
4. If exit `7`, tell operator to run `login` and stop.
5. Parse JSON; list failures with test names and messages.
6. Map failures using the table in `docs/telegram-e2e-developer-guide.md` § “Session suite reference”.

## Short operator runbook

`docs/runbooks/telegram-e2e.md` — compose bootstrap and safety rules.
