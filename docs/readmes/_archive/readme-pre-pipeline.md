# sevn.bot — Personal AI Assistant

**One bot. Your machine. Your model. Your memory.**

[![CI](https://github.com/sevn-bot/sevn/actions/workflows/ci.yml/badge.svg)](.github/workflows/ci.yml) [![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE) [![Python](https://img.shields.io/badge/python-3.12%2B-blue.svg)](pyproject.toml) [![Package](https://img.shields.io/badge/package-0.0.2c-orange.svg)](pyproject.toml)

**sevn.bot** is a _single AI assistant you own_ that lives in the channels you already use. It remembers you across sessions, runs on whichever LLM provider you can afford or trust, and gets work done by composing tools, skills, and external integrations under your control. The gateway is the control plane — the product is the assistant.

If you want a personal, single-user assistant that feels local, fast, model-agnostic, and never locks you into a vendor, this is it.

Supported channels at launch: **Web UI** (in-core, OpenUI-driven), **Telegram** (DMs, groups, forum topics, voice, attachments, inline-keyboard menus, quick-action bar, pinned dashboard), and **Voice** (gateway-level STT/TTS, no voice skills). Other channels (Discord, Slack, WhatsApp, Signal, Matrix, …) ship as `pip` plugin adapters post-v1.

[User help](about-sevn.bot/index.html) · [Evolution docs](evolution/README.md) · [Changelog](CHANGELOG.md) · [License](LICENSE)

New install? Start here: **`sevn onboard`**.

Preferred setup: run `sevn onboard` in your terminal. The onboarding wizard guides you step by step through setting up the gateway, workspace, channels, secrets backend, and feature opt-ins. Use `sevn onboard --web` for the browser wizard (shared design package under `styles/sevn/style/`, built with `make styles-build`). It is the recommended CLI setup path and works on **macOS** and **Linux**; **Windows is supported via WSL2** (native Win32 is out of scope for v1).

## Sponsors

sevn.bot is a single-operator project. No sponsors today — see [LICENSE](LICENSE) (MIT) and the [Community](#community) section below if you want to contribute.

**Subscriptions (OAuth):**

- **Anthropic** (Claude.ai consumer subscription)
- **OpenAI** (ChatGPT / Codex)
- **Google** (Gemini-CLI)
- **Vercel** (ai-gateway)

Each ships as an opt-in regime; per-token API keys are always available as fallback. Refresh tokens never leave the egress proxy.

Model note: many providers and models are supported via four `Transport` shapes (Anthropic Messages, OpenAI Chat Completions, OpenAI Responses, Bedrock Converse). The shipped Triager default is `minimax/text-01`; prefer a current flagship model from the provider you already trust.

## Install (recommended)

Runtime: **Python 3.12+** with **[uv](https://docs.astral.sh/uv/)**. v0.0.2 ships from source today; PyPI publication and `pipx install sevn` follow the `v0.0.2` tag.

```bash
git clone https://github.com/sevn-bot/sevn.git
cd sevn.bot
make setup

sevn onboard --install-daemon
```

`sevn onboard --install-daemon` registers **paired** launchd/systemd user services for the gateway and the egress proxy so both survive reboot.

To pull the latest source and reinstall the CLI (keeps `.env` / `.env.proxy`): `sevn sync` from inside the clone, or set `SEVN_REPO_ROOT`. Use `sevn sync --latest` to rerun setup even when already at the remote tip. Tracks **`test-pre`** until stable moves to **`main`**.

## Quick start (TL;DR)

Runtime: **Python 3.12+** with **uv**.

The onboarding wizard (`sevn onboard`) walks through auth, channels, secrets backends, and tunnels.

```bash
make setup
make ci                  # full pre-merge gate (lint, typecheck, tests, security, build)

# After onboard: paired daemons load keys from the secrets store (no .env.proxy required)
sevn gateway restart   # proxy first, then gateway; logs under {workspace}/logs/

# Dev-only without SEVN_HOME: Terminal 1 — proxy on http://127.0.0.1:8787
# cp .env.proxy.example .env.proxy && make proxy-env

# Terminal 2 — gateway on http://127.0.0.1:3001 (Web UI + Mission Control under /mission/)
export SEVN_PROXY_URL=http://127.0.0.1:8787
make run

# Talk to the assistant from the CLI (delivered back to any connected channel)
sevn config validate
sevn doctor --json
```

### Optional: Browser skills

Browser automation uses the native CDP engine (`browser-cdp` extra):

```bash
uv sync --extra browser-cdp
```

Host-first headed sessions on macOS. See `CLAUDE.md` → "Optional Python
extras" for Docker and config (`skills.browser.*`) details.

Upgrading? Run **`sevn doctor`** before and after — every restart playbook ends with doctor green.

## Security defaults (DM access)

sevn.bot connects to real messaging surfaces. Treat inbound DMs as **untrusted input**.

Default behaviour on Telegram (Web UI is owner-only):

- **DMs default to `PAIRING`** — unknown senders receive a short pairing code and the bot does **not** route their message into Triager.
- **Groups default to `ALLOWLIST`** — per-chat opt-in by chat ID; non-listed groups are ignored entirely.
- Approve with: `sevn config telegram approve <code>` (the sender / chat is added to a local allowlist store).
- Public inbound DMs require an explicit owner switch to `dmPolicy="OPEN"` plus an explicit `allowFrom` entry; `DISABLED` blocks the channel outright.

Run `sevn doctor` to surface risky / misconfigured DM and group policies.

## Highlights

- **Local-first gateway** — single FastAPI control plane for sessions, channels, tools, traces, and events.
- **Multi-channel inbox** — Web UI (in-core, OpenUI-driven), Telegram (DMs / groups / forum topics / voice / attachments / inline menus / quick-action bar / pinned dashboard), and Voice. Discord / Slack / WhatsApp / Signal / Matrix / SMS ship as plugin adapters post-v1.
- **Triager + tiered executors** — single LLM pass per message classifies tier `A | B | C | D`; tier A is the Triager's own reply, tier B runs a Pydantic AI agent loop, tier C/D runs a DSPy pipeline (decompose → plan-gate → DSPy `RLM` REPL → synthesize) with **opt-in λ-RLM** backend.
- **Vendor-neutral providers** — pluggable `Transport` shapes (Anthropic Messages, OpenAI Chat Completions, OpenAI Responses, Bedrock Converse) bound at `resolve_model` time, with `fallback_chain` per tier and prompt-cache discipline (> 70 % hit rate target on Triager calls).
- **Voice at the gateway** — STT chain (whisper.cpp → OpenAI → Deepgram → Google → xAI) and TTS chain (Kokoro local default → KittenTTS → Edge → OpenAI → ElevenLabs → Voxtral → Google Gemini TTS). TTS default off; opt-in per session via `/voice`.
- **OpenUI** — agent-generated visual workspace; web renders live HTML (sanitiser allowlist + strict CSP), other channels get a rasterised PNG or PDF cover.
- **Memory that grows with you** — Lossless Context Management (LCM) compaction DAG + workspace files (`SOUL.md` / `USER.md` / `MEMORY.md` / `TOOLS.md`); optional **dreaming** consolidation and optional **Honcho** cross-session profile inference.
- **Skills & tools** — unified `@sevn_tool` callable contract, framework-agnostic adapters (`pydantic_adapter`, `dspy_adapter`, optional λ-RLM adapter), skill manifest + body cache + agent-generated skills, MCP servers opt-in per session.
- **Mission Control dashboard** — FastAPI backend + React SPA, owner-only auth, traces / budget / replay / kill-switch, paired-daemon health, redaction at query time.
- **Non-interactive triggers** — webhook receiver + cron runner with two delivery modes: `agent_pass` (full executor run) and `notify_only` (zero-LLM template render).
- **Second Brain** — Karpathy-style wiki with provenance + Obsidian bidirectional sync; optional PDF URL ingest; preview — full release in v1.1.
- **Code understanding** — MYCODE, roam-code, code-graph-rag, Graphify MCP, code-review-graph MCP, all wired into Triager orientation; preview — full release in v1.1.
- **Self-improvement** — opt-in trajectory feedback + experiment-based eval + git-worktree-based auto-upgrade.

## Security model (important)

- **Egress LLM proxy** is the only process that holds real provider keys. Agent, sandbox, and channel adapters cannot read them. Real keys live in your secrets backend (macOS Keychain / OpenBao / Proton Pass / Linux secret service / encrypted file) and are injected into the proxy at boot. Never put them in `sevn.json` or `.env` checked into the repo.
- **Default-deny egress in sandboxes.** A skill that calls `requests.get("https://api.github.com/...")` with a hand-set header is **403'd at the proxy** before the upstream is contacted. Authenticated calls go through `integration_call` only.
- **Permission narrowing — never widening.** `PermissionConfig = intersect(source_template, triager_decision)`; mid-run narrowing accepts stricter configs only.
- **LLM Guard** runs on every inbound (text, voice transcript, tool result) before the routing model sees it. Curated injection corpus target: ≥ 95 % catch rate.
- **`.llmignore/` quarantine** is a one-way mirror with five enforcement layers. No LLM — agent, skill, scanner, indexer, compactor, dreaming — ever reads from it.
- **Production sandbox is Docker.** Subprocess fallback is dev/CI-only and gated by `security.sandbox.allow_subprocess_fallback`. Per-sandbox-boot session token carries the run's permission ceiling.
- **Self-preservation enforced.** The agent cannot terminate the gateway, the proxy, or its own sandbox parent.
- **Kill button.** `/stop`, dashboard "kill all runs", `sevn gateway stop`, and dashboard "revoke session tokens" each interrupt in-flight work within ≤ 2 s.

Before exposing anything remotely, review the trust, egress-proxy, sandbox, and security-scanner design docs.

## Docker deployment

For a local gateway + proxy stack in Docker (operator testing, Telegram E2E **local** target):

1. Copy `.env.example` to `.env` and set `SEVN_TELEGRAM_BOT_TOKEN`, `OPENAI_API_KEY`, and `TG_TARGET_BOT`.
2. `make compose-up` — builds and starts `sevn-proxy` + `sevn-gateway` on localhost (`SEVN_GATEWAY_PORT`, default **3001**).
3. First boot (seeds `sevn.json` + secrets on the shared volume):

   ```bash
   docker compose run --rm sevn-gateway sevn onboard \
     --config /bootstrap/onboard-compose.json \
     --profile good_value_docker \
     --no-install-daemon --no-start-services \
     --no-prompt-bot-name --bot-name Sevn
   ```

4. Check readiness: `curl -sf http://127.0.0.1:${SEVN_GATEWAY_PORT:-3001}/ready`.

Persistent volume layout (`SEVN_HOME=/operator`): `workspace/sevn.json`, `workspace/logs/gateway.log`, and `workspace/.sevn/traces.db` — aligned with `resolve_service_log_path` / gateway diagnostics.

Telegram Web checks run on the host via the browser ``telegram_web`` recipe, not inside the container.

- **Building sevn.bot:** [`docs/telegram-e2e-developer-guide.md`](docs/telegram-e2e-developer-guide.md) — setup, daily loop, Cursor + Claude skills
- **Operator runbook:** [`docs/runbooks/telegram-e2e.md`](docs/runbooks/telegram-e2e.md)

## Operator quick refs

- **Slash commands (8 total):** `/start`, `/help`, `/new`, `/status`, `/stop`, `/config`, `/voice`, `/model`. Everything else is reachable from inline-keyboard menus under `/config` (plus owner-only `/logs` and `/traces` when shipped).
- **CLI surface:** `sevn onboard`, `sevn gateway {start,stop,restart,status,logs}`, `sevn proxy {start,stop,restart,status,logs}`, `sevn doctor [--json]`, `sevn config {validate,edit,…}`, `sevn secrets {set,get,list,rotate}`, `sevn improve {doctor,replay-sampler,learn}`, `sevn migrate <PATH>` (imports legacy agent / OpenClaw / predecessor workspaces).
- **Tier C/D budgets:** outer rounds 30/turn; inner sub-LM calls 20 / 50 / 30 for `PER_TOKEN` / `SUBSCRIPTION` / `FREE_LOCAL` respectively.
- **Architecture overview:** [`about-sevn.bot/ARCHITECTURE.md`](about-sevn.bot/ARCHITECTURE.md) — module map, import-graph rules, shared protocols (`Transport`, `TraceSink`, `PluginHook`).
- **Make surface:** `make help` lists every recurring command. `make ci` is the canonical pre-merge gate.

## Docs by goal

The full PRD and spec set is local-only (kept out of the published repo). User-facing
documentation lives under [`about-sevn.bot/`](about-sevn.bot/), with the architecture index at
[`about-sevn.bot/ARCHITECTURE.md`](about-sevn.bot/ARCHITECTURE.md).

- **Building sevn.bot:** [`docs/telegram-e2e-developer-guide.md`](docs/telegram-e2e-developer-guide.md), `docs/runbooks/`
- **Troubleshooting:** `docs/runbooks/proxy.md`, `docs/runbooks/cli.md`, `docs/runbooks/telegram-e2e.md`, `docs/runbooks/triggers.md`, `docs/runbooks/triager.md`, `docs/runbooks/sandbox.md`, `docs/runbooks/llmignore-scanner.md`, `docs/runbooks/secrets-operator-env.md`, `docs/runbooks/ci-github-settings.md`

## Surfaces (optional)

The gateway alone delivers the daily-driver experience. The surfaces below are optional and additive.

### Mission Control dashboard (optional)

- FastAPI backend + vanilla JS SPA at `http://127.0.0.1:3001/mission/` (same gateway process).
- Loopback access skips login when `dashboard.local_open` is effective; tunneled or remote access uses owner password login at `/mission/`.
- Run `sevn dashboard` to print the URL and hints; `sevn dashboard --open` opens your browser.
- 40 tabs across Core / Observability / Agent / Knowledge / Self-improve / Ops / Surfaces; traces, budget, replay, kill all runs, paired-daemon health, page-agent intent.
- Onboarding sets `web_ui.url` when `dashboard.enabled` is true so Telegram menu deep links resolve.
- Validated by `make dash-build` and `make dash-test`.

### Web UI chat (in-core, v1 first-channel gate)

- WebSocket chat at `/ws/webchat`; static SPA at `/webapp/`.
- OpenUI-driven (live HTML; sanitiser allowlist + strict CSP, no client JS in v1).
- Owner-only auth; reuses the gateway session token. Same agent, same `SessionManager`, same memory as Telegram.

### Telegram bot (in-core)

- Polling (default) or webhook delivery; `webhook_secret_token` minted once on first `setWebhook` and persisted.
- DMs, groups, supergroups, and forum topics; topics are independent sessions with per-topic system prompt + tool/skill restrictions.
- Inline-keyboard menus replace the predecessor's 30+ slash commands; 8 commands remain.
- Voice, attachments, reply-quote context; per-locale `setMyCommands`.

### Voice (in-core)

- Gateway-level STT/TTS only — no voice skills.
- Inbound voice messages are auto-transcribed and routed as text. TTS default **off**; opt-in via `/voice` or `when_asked` keywords.

### Channel plugins (post-v1)

Discord, Slack, WhatsApp, Signal, Matrix, SMS, Messenger ship as separate `pip` packages (`sevn-channel-*`) when prioritised. The `PluginHook` and `ChannelAdapter` contracts are stable from v0.0.2.

## From source (development)

This repository is a `uv`-managed Python project (hatchling build backend). All recurring commands route through **`make`** — do not use raw `uv run pytest` / `ruff` / `mypy` in everyday workflows.

```bash
git clone https://github.com/sevn-bot/sevn.git
cd sevn.bot

make setup                # uv sync + install pre-commit hooks
make ci                   # full pre-merge gate (lockcheck, lint, typecheck, pyright, test, doctest, security, schema, build)

# Run locally (two terminals) — production path uses SEVN_HOME + workspace secrets:
export SEVN_HOME=~/.sevn   # after sevn onboard
make proxy                # factory boot: http://127.0.0.1:8787
make run                  # http://127.0.0.1:3001

# Dev-only .env shortcut: make proxy-env (see .env.proxy.example)

# Smoke gates from the release plans:
make v1-smoke             # seven sequential v1 user-path probes
make v2-smoke             # v1 regression + v2 gates
```

Pre-commit runs Ruff (check + format), Markdownlint on the local-only design-doc trees, an `sevn-mypy` hook that mirrors `make typecheck`, and a **commit-msg** hook that enforces [Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/) (`make commit-msg-check MSG='feat: …'`). Setup and agent usage (Cursor, Claude Code, sevn gateway): [`src/sevn/data/standards/README.md`](src/sevn/data/standards/README.md). `make ci` is the same chain CI runs on every PR.

Provider keys live in the **secrets backend** and are injected into the proxy at boot via **`build_proxy_settings`**. Service logs: **`{workspace}/logs/gateway.log`** and **`proxy.log`**; restart rotates to timestamped siblings; retention is configured under **`logging`** in `sevn.json` (Mission Control **System → Log retention**). For local dev without `SEVN_HOME`, **`.env.proxy`** + **`make proxy-env`** remains supported. Operator notes: [`docs/runbooks/proxy.md`](docs/runbooks/proxy.md).

OpenUI rasterised PNG/PDF rendering uses [WeasyPrint](https://weasyprint.org/) which needs native **Pango/Cairo/GDK-Pixbuf** libraries on the host. On macOS: `brew install pango cairo gdk-pixbuf libffi`. On Debian/Ubuntu follow WeasyPrint's [installation guide](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html#installation).

## Release channels

sevn.bot is pre-1.0; the API surface and `sevn.json` schema may evolve without backwards-compatibility guarantees.

- **stable** — tagged releases (`v0.0.x`); current shipped milestone is **`v0.0.1`** (gates: `make v1-smoke`). Next milestone is **`v0.0.2`** (gates: `make v1-smoke` + `make v2-smoke`).
- **pre** — `test-pre` branch; v2 work-in-progress; not safe for daily-driver use.
- **main** — moving head; merged from `test-pre` when the operator declares readiness.

Two CI workflows back this: [`.github/workflows/ci.yml`](.github/workflows/ci.yml) is the **sole merge gate** on PRs to `main` / `develop` (runs `make setup` then `make ci`); [`.github/workflows/ci-cd.yml`](.github/workflows/ci-cd.yml) is the **six-phase delivery DAG** for pushes to `main`, `v*` tags, and manual dispatch (does **not** run on PRs — no double-gating).

## Agent workspace + skills

- **Workspace root** is bound at first onboarding (default: a workspace directory you pick; commonly `~/sevn-workspace/` or similar). It is the single source of truth — there is no `XDG_CONFIG_HOME` / `~/.sevnrc` / `.env` walk-up.
- **Injected prompt files** live at the workspace root: `SOUL.md` (the bot's voice), `USER.md` (who the operator is), `MEMORY.md` (long-term facts), `TOOLS.md` (tool / skill / MCP narration). Editing any of these bumps `personality_version` and reuses the Triager prompt cache correctly.
- **Skills:** bundled core skills ship inside the wheel under `sevn/data/bundled_skills/`; workspace skills live at `<workspace>/skills/<skill>/SKILL.md` and are loaded by manifest with body-cache memoisation. Plugin skills register via the `sevn.skills` entry-point group.
- **Second Brain:** when enabled, the vault lives at `<workspace>/second_brain/` with per-scope `wiki/` / `raw/` / `outputs/` (default off; opt-in in `sevn.json`).

## Configuration

`sevn.json` is the **only** authoritative config file. The only env overrides are the curated `SEVN_*` allowlist. Schema: [`infra/sevn.schema.json`](infra/sevn.schema.json) (validated by `make config-schema`).

Minimal `sevn.json`:

```json
{
  "agent_name": "sevn",
  "providers": {
    "primary": {
      "transport": "anthropic",
      "model": "claude-sonnet-4-5"
    }
  },
  "triager": {
    "model": "minimax/text-01"
  },
  "tracing": {
    "sinks": [{ "kind": "jsonl" }]
  },
  "channels": {
    "webchat": { "enabled": true },
    "telegram": { "enabled": false }
  }
}
```

The full configuration reference lives in the config design docs. Validate locally with `sevn config validate` or `make config-schema`.

## Star History

[github.com/sevn-bot/sevn](https://github.com/sevn-bot/sevn) — pre-1.0; star history reflects an early-stage project. Issues and contributions welcome.

## About

sevn.bot is built and maintained by **Alex** as a daily-driver personal AI assistant. It evolves the patterns from a working predecessor project (gateway + channel adapters + intent routing + skills + lossless context management) but replaces the brittle pieces — direct provider calls, Logfire-only tracing, the closed marketplace, monolithic agent loops — with pluggable, locally-runnable, model-agnostic equivalents. The product hypothesis: one bot that travels with you, remembers you, can be told to plan-then-do, and never locks you into a vendor.

## Community

This is a single-operator project. PRs are welcome — read [`CLAUDE.md`](CLAUDE.md) and [`about-sevn.bot/_standards/coding-standards.md`](about-sevn.bot/_standards/coding-standards.md) before submitting. Use **`make ci`** before opening a PR (same command CI runs). For security-sensitive issues, please open a private issue rather than a public PR.
