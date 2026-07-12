# Workspace layout

Canonical directory and file layout for this sevn.bot workspace. The gateway validates this shape on boot and emits `workspace.layout_mismatch` when folders or narrative files are missing.

Read this file on demand when you need to describe, list, or verify the workspace — it is **not** loaded into the agent prompt by default.

## Root tree

```
<content_root>/              # workspace root (where sevn.json lives)
├── sevn.json                # operator config — channels, memory, tools, tracing
├── WORKSPACE.md             # this file — canonical layout reference
├── AGENTS.md                # operating manual
├── sevn.bot.md              # product context for sevn.bot deployments
├── BOOTSTRAP.md             # first-run dialogue (delete after USER.md is filled)
├── IDENTITY.md              # agent name, vibe, emoji, boundaries
├── SOUL.md                  # tone, rules, personality
├── USER.md                  # operator profile (+ Honcho flush target)
├── MEMORY.md                # curated long-term memory (main session)
├── TOOLS.md                 # operator environmental notes + tool registry
├── memory/                  # daily logs (YYYY-MM-DD.md) and dreaming artefacts
├── out/                     # generated artifacts (PDFs, fetched pages, screenshots; per-session subfolders)
├── sessions/                # append-only session mirror JSONL (when enabled)
├── skills/                  # core/, user/, generated/, plugins/
├── tools/                   # optional per-tool long descriptions (<name>.md)
├── logs/                    # gateway.log, proxy.log, rotated <name>-<UTC>.log
└── .sevn/
    ├── sevn.db              # sessions, LCM, memory tables, dispatcher state
    ├── traces.db            # runtime trace spans (when SQLite sink enabled)
    ├── traces/              # JSONL trace files (when configured)
    └── turns/               # per-turn diagnostic bundles (when diagnostics.turn_bundles.enabled)
        └── <DDMMYY>/        # UTC day partition (e.g. 160626 = 16 Jun 2026)
            ├── index.json   # turn_id → file, has_error, processed, …
            └── <safe_turn_id>.jsonl   # interleaved log | message | trace records for one turn
```

Paths resolve from `sevn.json` (`workspace_root` key, default `.` beside the config file).

## Required directories

| Path | Purpose |
|------|---------|
| `.sevn/` | SQLite databases, trace exports, turn-bundle diagnostics, deployment metadata |
| `.sevn/turns/` | Per-turn JSONL bundles in UTC day folders (`<DDMMYY>/index.json` + `*.jsonl`) when `diagnostics.turn_bundles.enabled` (or after `sevn turn-bundle export`) |
| `logs/` | Active gateway and proxy daemon logs |
| `memory/` | Daily session notes (`YYYY-MM-DD.md`) and dreaming sources |
| `sessions/` | Gateway session mirror JSONL (when `gateway.session_mirror` is enabled) |
| `skills/` | Skill packages under `core/`, `user/`, `generated/`, `plugins/` |
| `out/` | Generated tool/skill output (`workspace.output_dir`; default `out/<session_id>/`) |

## Required narrative files

| File | Purpose |
|------|---------|
| `AGENTS.md` | Operating rules, decomposition, memory subsystems |
| `sevn.bot.md` | sevn.bot-specific product context |
| `IDENTITY.md` | Agent display name, vibe, emoji |
| `SOUL.md` | Tone and behavioural boundaries |
| `USER.md` | Operator profile and preferences |
| `MEMORY.md` | Curated durable facts for the main session |
| `TOOLS.md` | Operator environmental notes and live tool/skill catalog |
| `WORKSPACE.md` | This canonical layout reference |

`BOOTSTRAP.md` is seeded on first onboard and removed after the operator profile is captured — its absence after bootstrap is expected.

## Logs layout

| File | Writer |
|------|--------|
| `logs/gateway.log` | Gateway daemon (default tail target for `log_query`) |
| `logs/proxy.log` | Egress proxy daemon |
| `logs/gateway-<UTC>.log` | Rotated gateway log after restart |
| `logs/proxy-<UTC>.log` | Rotated proxy log after restart |

Use `log_query` with `file=<name>` to read any `*.log` under `logs/` (tail with
`offset_from_tail`, forward from `starting_reading_line`, or explicit `ranges`).

## Verification

- **Gateway boot:** missing folders or required markdown files emit a `workspace.layout_mismatch` trace event (non-blocking).
- **On demand:** read this file, or use `glob` / `read` to inspect the tree.
- **CLI:** `sevn doctor` validates config and runtime probes; layout checks complement doctor on every gateway restart.
