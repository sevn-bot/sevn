---
id: spec-38-google-workspace
kind: spec
title: Google Workspace skill — Spec
status: scaffold
owner: Alex
summary: Bundled google-workspace skill — OAuth2 Gmail, Calendar, Drive, Sheets, Docs,
  Contacts; optional gws CLI bridge.
last_updated: '2026-07-18'
fingerprint: sha256:1c7382e3fc07f38e95cd3cbf5ffb732428db7a165e873e049aef95eeccaade7e
related:
- spec-12-skills-system
- spec-02-config-and-workspace
- spec-06-secrets
- spec-07-egress-proxy
- spec-11-tools-registry
sources:
- src/sevn/data/bundled_skills/core/google-workspace/**
- src/sevn/skills/google_workspace.py
parent_prd: prd-04-getting-things-done
depends_on:
- spec-02-config-and-workspace
- spec-06-secrets
- spec-07-egress-proxy
- spec-12-skills-system
build_phase: null
interfaces:
- name: main
  file: src/sevn/data/bundled_skills/core/google-workspace/scripts/google_api.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/google-workspace/scripts/gws_bridge.py
  symbol: main
- name: main
  file: src/sevn/data/bundled_skills/core/google-workspace/scripts/setup.py
  symbol: main
- name: GoogleWorkspacePaths
  file: src/sevn/skills/google_workspace.py
  symbol: GoogleWorkspacePaths
- name: build_service
  file: src/sevn/skills/google_workspace.py
  symbol: build_service
- name: check_auth
  file: src/sevn/skills/google_workspace.py
  symbol: check_auth
- name: check_auth_live
  file: src/sevn/skills/google_workspace.py
  symbol: check_auth_live
- name: client_secret_path
  file: src/sevn/skills/google_workspace.py
  symbol: client_secret_path
- name: dry_run_requested
  file: src/sevn/skills/google_workspace.py
  symbol: dry_run_requested
- name: ensure_google_deps
  file: src/sevn/skills/google_workspace.py
  symbol: ensure_google_deps
- name: exchange_auth_code
  file: src/sevn/skills/google_workspace.py
  symbol: exchange_auth_code
- name: get_auth_url
  file: src/sevn/skills/google_workspace.py
  symbol: get_auth_url
- name: get_credentials
  file: src/sevn/skills/google_workspace.py
  symbol: get_credentials
- name: get_valid_token_for_gws
  file: src/sevn/skills/google_workspace.py
  symbol: get_valid_token_for_gws
- name: gws_binary
  file: src/sevn/skills/google_workspace.py
  symbol: gws_binary
- name: install_deps
  file: src/sevn/skills/google_workspace.py
  symbol: install_deps
- name: load_token_payload
  file: src/sevn/skills/google_workspace.py
  symbol: load_token_payload
- name: missing_scopes_from_payload
  file: src/sevn/skills/google_workspace.py
  symbol: missing_scopes_from_payload
- name: normalize_authorized_user_payload
  file: src/sevn/skills/google_workspace.py
  symbol: normalize_authorized_user_payload
- name: paths
  file: src/sevn/skills/google_workspace.py
  symbol: paths
- name: pending_auth_path
  file: src/sevn/skills/google_workspace.py
  symbol: pending_auth_path
- name: prefer_gws_enabled
  file: src/sevn/skills/google_workspace.py
  symbol: prefer_gws_enabled
- name: revoke_token
  file: src/sevn/skills/google_workspace.py
  symbol: revoke_token
- name: run_gws
  file: src/sevn/skills/google_workspace.py
  symbol: run_gws
- name: store_client_secret
  file: src/sevn/skills/google_workspace.py
  symbol: store_client_secret
- name: token_path
  file: src/sevn/skills/google_workspace.py
  symbol: token_path
---

# Google Workspace skill — Spec

## Purpose

Deliver Hermes Agent **google-workspace parity** as a bundled core skill covering Gmail, Calendar, Drive, Sheets, Docs, and Contacts through OAuth2-authenticated Google APIs. See **§1 Goal** below for scope and references.

## Public Interface

Bundled scripts under `src/sevn/data/bundled_skills/core/google-workspace/scripts/` (`setup.py`, `google_api.py`, `gws_bridge.py`) plus `src/sevn/skills/google_workspace.py` helpers (`build_service`, `check_auth`, `get_auth_url`, `exchange_auth_code`, `run_gws`, …). Function inventory in **§4**; agent consumption in **§5**.

## Data Model

OAuth client secret + token payloads stored via the workspace secrets chain; config under `skills.google_workspace.*` in `sevn.json`. Credential paths and token JSON shape in **§3.2** and **§3.4**.

## Internal Architecture

Python Google API client fallback with optional `gws` CLI bridge; skill subprocess JSON envelopes; egress via the workspace proxy. Layout and execution backend in **§3**.

## Behavior

Setup wizard exchanges auth codes, refreshes tokens, routes read/write calls to Gmail/Calendar/Drive/Sheets/Docs/Contacts APIs (or `gws` when enabled). Phased rollout in **§7**; security gates in **§3.6**.

## Failure Modes

Missing deps, expired or revoked tokens, insufficient OAuth scopes, proxy/egress blocks, and gated writes without operator confirmation — surfaced as script envelope errors and `check_auth` diagnostics.

## Test Strategy

Unit tests mock Google API clients and token IO; integration tests cover auth refresh and allowlisted script envelopes; live smoke is operator-observed with real OAuth. See **§8 Testing strategy**.

## 1. Goal

Deliver **Hermes Agent google-workspace parity** as a sevn **bundled core skill** (`google-workspace`), covering Gmail, Calendar, Drive, Sheets, Docs, and Contacts through OAuth2-authenticated Google APIs.

Reference implementation: [Hermes `skills/productivity/google-workspace/`](https://github.com/NousResearch/hermes-agent/tree/main/skills/productivity/google-workspace) (v1.1+ with optional [`gws` CLI](https://github.com/googleworkspace/cli) backend).

Operator-facing function catalog: `about-sevn.bot/google-workspace.html` (help site).

## 2. Gap analysis — Hermes vs sevn today

| Area | Hermes google-workspace | sevn today |
|------|-------------------------|------------|
| Gmail read/search | OAuth + Gmail API (`gmail search`, `gmail get`) | Shipped in bundled `google-workspace`; browser/email-management remain fallbacks |
| Gmail send/reply | OAuth API (`gmail send`, `gmail reply`, labels) | Shipped in bundled `google-workspace`; browser gated writes and `email-management` still available |
| Gmail labels | `gmail labels`, `gmail modify` | Shipped in bundled `google-workspace` |
| Calendar | list/create/delete | Shipped in bundled `google-workspace` |
| Drive | search/get/upload/download/folder/share/delete | Shipped in bundled `google-workspace` |
| Sheets | create/get/update/append | Shipped in bundled `google-workspace` |
| Docs | get/create/append | Shipped in bundled `google-workspace` |
| Contacts | list | Shipped in bundled `google-workspace` |
| OAuth setup | Agent-driven PKCE flow (`setup.py`) | Shipped in bundled `google-workspace` |
| Backend | `gws` preferred, Python fallback | Python/OAuth backend shipped; `gws` bridge still pending |

**Conclusion:** sevn now ships a bundled `google-workspace` core surface for OAuth setup, Gmail API, Calendar, Drive search/get, and Contacts. Browser paths and `email-management` remain the fallbacks for no-OAuth or quick email-only work, while Sheets/Docs, Drive write flows, and the `gws` bridge remain follow-on work.

## 3. Architecture (sevn-adapted)

```mermaid
flowchart TB
    T[Triager selects google-workspace] --> B[Tier-B deferred capability]
    B --> LS[load_skill]
    B --> RS[run_skill_script]
    RS --> SM[SkillsManager subprocess]
    SM --> GW[google_workspace.py library]
    GW --> BR[gws_bridge.py optional]
    BR --> GWS[gws CLI]
    GW --> PY[Python google-api fallback]
    GW --> TOK[.sevn/google_token.json]
    SM --> EGR[Egress proxy allowlist]
```

### 3.1 Skill layout

```
src/sevn/data/bundled_skills/core/google-workspace/
├── SKILL.md
├── references/
│   └── gmail-search-syntax.md
└── scripts/
    ├── setup.py              # OAuth PKCE (check, client-secret, auth-url, auth-code, revoke)
    ├── google_api.py         # Hermes-compatible CLI: gmail|calendar|drive|...
    └── gws_bridge.py         # Token refresh → GOOGLE_WORKSPACE_CLI_TOKEN for gws
```

Shared library (testable, no subprocess in unit tests):

```
src/sevn/skills/google_workspace.py
```

### 3.2 Credential storage (sevn conventions)

| Artifact | Path | Notes |
|----------|------|-------|
| OAuth token | `<workspace>/.sevn/google_token.json` | Auto-refresh; never returned in script JSON |
| Client secret | `<workspace>/.sevn/google_client_secret.json` | Operator supplies once |
| Pending PKCE | `<workspace>/.sevn/google_oauth_pending.json` | Ephemeral until exchange |
| Last auth URL | `<workspace>/.sevn/google_oauth_last_url.txt` | Operator handoff aid |

Env overrides (optional): `SEVN_GOOGLE_TOKEN_PATH`, `SEVN_GOOGLE_CLIENT_SECRET_PATH`.

### 3.3 Execution backend

1. **Preferred:** [`gws`](https://github.com/googleworkspace/cli) when on PATH — `gws_bridge.py` injects refreshed token via `GOOGLE_WORKSPACE_CLI_TOKEN`.
2. **Fallback:** bundled Python client (same JSON output contract as Hermes `google_api.py`).
3. **Degraded:** triager may still route Gmail reads to `browser` gmail recipe or `email-management` when skill reports `NOT_AUTHENTICATED`.

### 3.4 Config (`sevn.json`)

```json
{
  "skills": {
    "google_workspace": {
      "enabled": true,
      "prefer_gws": true,
      "default_services": "all",
      "account_label": "Primary Google",
      "dry_run": false
    }
  }
}
```

Typed section: `GoogleWorkspaceSkillConfig` in `src/sevn/config/sections/skills_google_workspace.py`.

### 3.5 Egress

Skill manifest `egress:`:

- `gmail.googleapis.com`
- `www.googleapis.com`
- `oauth2.googleapis.com`
- `people.googleapis.com`
- `sheets.googleapis.com`
- `docs.googleapis.com`
- `drive.googleapis.com`
- `calendar.googleapis.com`

### 3.6 Security and operator gates

| Operation class | Gate |
|-----------------|------|
| Read (search, get, list) | Allowed after auth check |
| Send email, create calendar, upload/share/delete drive, sheets update, docs append | **Ask operator first**; scripts set `abortable: false` where Hermes rules require confirmation |
| OAuth setup | Operator-driven; agent sends URLs, never stores client secret in chat |
| Token material | Redacted in traces; SkillSpector scans scripts |

Hermes rules 1–5 carry over verbatim in `SKILL.md` body.

## 4. Function inventory (Hermes parity)

All commands flow through `scripts/google_api.py` with JSON stdout (`write_ok` / `write_error` from `sevn.lcm.script_cli`).

### 4.1 Setup (`scripts/setup.py`)

| Command | Purpose |
|---------|---------|
| `--check` | `AUTHENTICATED` / `NOT_AUTHENTICATED` / partial scopes |
| `--client-secret PATH` | Store Desktop OAuth client JSON |
| `--auth-url [--services …]` | PKCE auth URL (json or plain) |
| `--auth-code CODE_OR_URL` | Exchange code; refresh on expiry |
| `--revoke` | Revoke and delete token |
| `--install-deps` | Install optional Python deps |

Service sets: `email`, `calendar`, `drive`, `sheets`, `docs`, `contacts`, `all`.

### 4.2 Gmail

| Command | Write? |
|---------|--------|
| `gmail search QUERY [--max N]` | No |
| `gmail get MESSAGE_ID` | No |
| `gmail send --to --subject --body [--html] [--from] [--cc]` | Yes |
| `gmail reply MESSAGE_ID --body [--from]` | Yes |
| `gmail labels` | No |
| `gmail modify MESSAGE_ID --add-labels/--remove-labels` | Yes |

### 4.3 Calendar

| Command | Write? |
|---------|--------|
| `calendar list [--start ISO] [--end ISO]` | No |
| `calendar create --summary --start --end [--location] [--attendees]` | Yes |
| `calendar delete EVENT_ID` | Yes |

### 4.4 Drive

| Command | Write? |
|---------|--------|
| `drive search QUERY [--max N] [--raw-query]` | No |
| `drive get FILE_ID` | No |
| `drive upload PATH [--name] [--parent]` | Yes |
| `drive download FILE_ID [--output] [--export-mime]` | No |
| `drive create-folder NAME [--parent]` | Yes |
| `drive share FILE_ID --email/--type/--role [--notify]` | Yes |
| `drive delete FILE_ID [--permanent]` | Yes |

### 4.5 Contacts

| Command | Write? |
|---------|--------|
| `contacts list [--max N]` | No |

### 4.6 Sheets

| Command | Write? |
|---------|--------|
| `sheets create --title [--sheet-name]` | Yes |
| `sheets get SHEET_ID RANGE` | No |
| `sheets update SHEET_ID RANGE --values JSON` | Yes |
| `sheets append SHEET_ID RANGE --values JSON` | Yes |

### 4.7 Docs

| Command | Write? |
|---------|--------|
| `docs get DOC_ID` | No |
| `docs create --title [--body]` | Yes |
| `docs append DOC_ID --text TEXT` | Yes |

Full usage table: `about-sevn.bot/google-workspace.html`.

## 5. Agent consumption (sevn skills system)

1. Triager adds `google-workspace` to `TriageResult.skills` for Gmail API, calendar, drive, sheets, docs, and contacts intents.
2. Tier-B attaches deferred capability `google-workspace__run_skill_script`.
3. Agent calls `load_skill("google-workspace")` → receives `capabilities[]` from `SKILL.md` scripts + prose.
4. Agent invokes e.g. `run_skill_script("google-workspace", "scripts/google_api.py", ["gmail", "search", "is:unread", "--max", "10"])`.

**Email-only triage:** prefer `email-management` (IMAP, no Cloud project) unless Calendar/Drive/Sheets/Docs are needed — same guidance as Hermes/himalaya split.

## 6. Relationship to existing integrations

| Existing | Current role with shipped core surface |
|----------|----------------------------------------|
| `email-management` | Keep for multi-account IMAP/SMTP and non-Google mail; Gmail API dry-run plans migrate to live calls via shared helpers or deprecation notice in SKILL.md |
| `browser` gmail recipe | Keep for operators without OAuth; document as fallback in google-workspace SKILL.md |
| `browser` google_search/maps/youtube | Unchanged; not part of this skill |

## 7. Implementation phases

### Phase 0 — Planning (this spec + help HTML)

- [x] Gap analysis and architecture
- [x] Function catalog HTML for operators and implementers
- [ ] Manifest entry in `_docsys/manifest.toml` (optional CI follow-up)

### Phase 1 — OAuth + auth library

- [x] `src/sevn/skills/google_workspace.py` — paths, token load/refresh, scope sets
- [x] `scripts/setup.py` — PKCE flow ported from Hermes, sevn path conventions
- [x] Config section + egress registration
- [x] Unit tests with fixture tokens (no network)

### Phase 2 — Core API (Python fallback)

- [x] `scripts/google_api.py` — Gmail + Calendar read/write
- [x] Drive search/get
- [x] Contacts list
- [x] JSON output contract tests (golden files)

### Phase 3 — Docs/Sheets + Drive writes

- [x] Sheets create/get/update/append
- [x] Docs get/create/append
- [x] Drive upload/download/folder/share/delete

### Phase 4 — gws bridge

- [x] `scripts/gws_bridge.py`
- [x] `prefer_gws` config flag
- [x] Doctor check: `sevn doctor` reports gws presence

### Phase 5 — Bundling and routing

- [x] `SKILL.md` + `INDEX.md` row
- [x] Triager routing hints (workspace template / AGENTS.md)
- [x] Onboarding capability stub update (`onboarding_capabilities.json`)
- [ ] Agent-level E2E test beyond setup dry-run + gmail search mock coverage
- [ ] Live OAuth E2E with a test Google Cloud project

## 8. Testing strategy

| Layer | Approach |
|-------|----------|
| Library | Mock HTTP / recorded responses |
| Scripts | Subprocess argv → JSON envelope assertions |
| gws bridge | Skip if gws absent; integration job optional |
| Agent E2E | `tests/agent/test_e2e_skill_execution.py` pattern with quarantine off for core |
| Security | SkillSpector baseline update; no token leakage in stdout |

## 9. Dependencies

- Optional: `google-api-python-client`, `google-auth-oauthlib` (install via `uv pip install 'sevn[google-workspace]'` or `setup.py --install-deps`)
- Optional system: `gws` (`npm i -g @googleworkspace/cli` or Homebrew)
- No new MCP server required for v1 (future: expose gws MCP behind egress policy)

## 10. Open questions

1. **Unify with email-management?** Recommend separate skills: email-management = multi-provider IMAP; google-workspace = Google OAuth suite. Cross-link in both SKILL.md files.
2. **Workspace vs personal Google?** Same OAuth flow; document Advanced Protection / Workspace admin allowlist (Hermes troubleshooting table).
3. **Dry-run mode?** Follow email-management: `--dry-run` and `SEVN_GOOGLE_DRY_RUN=1` emit plan envelopes without API I/O.

## 11. Acceptance criteria

- [x] Bundled `google-workspace` skill passes `scripts/check_skills_index.py`
- [x] All functions in §4 callable via `run_skill_script` with Hermes-compatible JSON shapes
- [ ] OAuth setup completable from Telegram/webchat (URL handoff) — manual/live E2E
- [ ] Write operations blocked without operator confirmation in harness
- [x] Help page `google-workspace.html` stays in sync with `SKILL.md` scripts
