# sevn-telegram-tester

Host-side Playwright harness for Telegram Web K E2E against a sevn.bot gateway.

**Start here for day-to-day development:**
[`docs/telegram-e2e-developer-guide.md`](../../docs/telegram-e2e-developer-guide.md)
(setup, dev loop, Cursor + Claude skills, troubleshooting).

Shorter operator runbook: [`docs/runbooks/telegram-e2e.md`](../../docs/runbooks/telegram-e2e.md).

**Not** shipped inside the gateway Docker image.

## Quick start

```bash
uv sync --extra dev && playwright install chromium
cp .env.example .env   # set tokens + TG_TARGET_BOT
make compose-up
docker compose run --rm sevn-gateway sevn onboard \
  --config /bootstrap/onboard-compose.json \
  --profile good_value_docker \
  --no-install-daemon --no-start-services \
  --no-prompt-bot-name --bot-name Sevn
sevn telegram-test login
make telegram-e2e
```

## Session suite (11 tests)

| Test | What it checks |
|------|----------------|
| `test_deployment_id_visible` | `/status` shows `Deployment id: …` |
| `test_config_opens` | `/config` root has 19 section tiles + Help + Close |
| `test_session_section_buttons` | Session section: Regen + Queue row, no 🚧 |
| `test_regen_toggle_persists_in_caption` | Regen toggle updates Session caption |
| `test_regen_toggle_affects_next_reply` | Regen off → no Regen QA on next echo reply |
| `test_queue_mode_cycle_persists` | Queue mode toggle updates caption |
| `test_queue_mode_runtime_reflects` | Steer + overlapping echoes → `/logs` contains `gateway.queue_steer_queued` |
| `test_logs_section_smoke` | `/config` → 📜 Logs → Tail gateway responds |
| `test_channels_section_buttons` | `/config` → 🔌 Channels → Show routing row pressable (no 🚧) |
| `test_show_routing_toggle_persists_in_caption` | Show routing toggle updates Channels caption |
| `test_show_routing_toggle_affects_next_reply` | Show routing on → `intent=… · tier=…` footer on next reply; off omits it |

## Agent skills

| Environment | Skill path |
|-------------|------------|
| **Cursor** | `.cursor/skills/telegram_test/SKILL.md` |
| **sevn.bot / Claude Code** | `src/sevn/data/bundled_skills/core/telegram_test/SKILL.md` |

## CI

`make ci` runs **unit tests only** (`tools/telegram-tester/tests/` with mocked Playwright).
Browser E2E is opt-in via `make telegram-e2e`.

## Layout

```text
tools/telegram-tester/
  compose.override.e2e.yml   # E2E echo delay (test runs only)
  artifacts/                 # JSON reports (gitignored)
  .browser-profile/          # Telegram Web session (gitignored)
  src/sevn_telegram_tester/
    runner.py
    suites/session.py
    telegram_client.py       # SELECTORS — update when Telegram Web DOM drifts
```
