<!-- generated: do not edit by hand; run `sevn readme update index` -->
# README catalog

> **Summary.** Generated catalog of every subsystem README with profile, one-line summary, and fingerprint freshness status. **Freshness ≠ semantic accuracy** — a `fresh` row only means source fingerprints match; run `make readme-check` for full validation.

**Operator clarity** — see [`STANDARD.md`](STANDARD.md) §9.4 for cross-cutting topics (secrets gateway vs proxy, channel stub vs production, schema vs Pydantic gaps). Load-bearing packages outside this catalog (e.g. `src/sevn/browser/`) are listed in STANDARD § out-of-catalog.

| Slug | Title | Profile | Summary | Status |
|------|-------|---------|---------|--------|
| [root](../../README.md) | sevn.bot | `root` | Brand-led entry: value prop, highlights, subsystem map, quick start — deep detail in docs/readmes/. | fresh |
| [gateway](gateway.md) | Gateway | `subsystem` | FastAPI control plane: channels, sessions, turn spine, queue/steer, Telegram menus. | fresh |
| [agent](agent.md) | Agent runtime | `subsystem` | Triager, tier-B/C executors, harness discipline, sandboxes, and turn orchestration. | fresh |
| [channels](channels.md) | Channels | `subsystem` | Telegram, Web UI bridge, and channel adapter patterns. | fresh |
| [tools](tools.md) | Tools registry | `subsystem` | Module inventory for the tools registry, adapters, and permission gates. | fresh |
| [skills](skills.md) | Skills system | `catalog` | Curated inventory of bundled and workspace skills, loaders, and subprocess runners. | fresh |
| [discogs](discogs.md) | Discogs skills | `guide` | Opt-in Discogs API skill group — catalog, marketplace, collection, wantlist, identity; User-token and OAuth auth. | fresh |
| [ui-mission-control](ui-mission-control.md) | Mission Control UI | `subsystem` | Dashboard SPA, tab registry, traces, ops surfaces, and OpenUI delivery. | fresh |
| [security](security.md) | Security scanner | `subsystem` | LLM Guard, .llmignore, block-and-notify, and channel security copy. | fresh |
| [secrets](secrets.md) | Secrets | `subsystem` | Secrets backends, logical-key chain, TTL, and fingerprint confirmation. | fresh |
| [proxy-egress](proxy-egress.md) | Egress proxy | `subsystem` | Shared-secret-guarded `/llm/*` egress proxy, Transport wire shapes, and route handlers. | fresh |
| [tracing](tracing.md) | Tracing | `subsystem` | TraceSink JSONL/SQLite sinks, OTLP export bridge, and trace maintenance. | fresh |
| [memory-context](memory-context.md) | Memory & context | `subsystem` | LCM store, compaction, user model, dreaming, and Honcho opt-ins. | fresh |
| [second-brain](second-brain.md) | Second brain | `subsystem` | Wiki vault layout, ingest paths, and wikilink-compatible provenance for operator knowledge. | fresh |
| [voice](voice.md) | Voice | `subsystem` | Gateway-level STT/TTS chains, trigger keywords, and voice trace events. | fresh |
| [triggers](triggers.md) | Non-interactive triggers | `subsystem` | Webhooks, cron, dedupe, dispatcher, and notify-only automation. | fresh |
| [config-workspace](config-workspace.md) | Config & workspace | `subsystem` | sevn.json schema, workspace layout, defaults, and layout validation. | fresh |
| [storage](storage.md) | Storage | `subsystem` | SQLite paths, connections, schema migrations, and D1 layout. | fresh |
| [code-understanding](code-understanding.md) | Code understanding | `subsystem` | MYCODE, Graphify, code-review-graph, and CGR integration for repo orientation. | fresh |
| [self-improve](self-improve.md) | Self-improvement | `subsystem` | Self-upgrade harness, eval workers, spec-kit stages, and improve jobs. | fresh |
| [integrations](integrations.md) | Integrations | `subsystem` | Cursor Cloud, GitHub skill clients, and external integration call paths. | fresh |
| [onboarding](onboarding.md) | Onboarding | `guide` | Operator setup: CLI, web wizard, Telegram flows, daemon install, and profiles. | fresh |
| [subagents](subagents.md) | Sub-agents | `subsystem` | Level-1 role runs, level-2 workers, specialists, multi queue mode, registry, and kill surfaces. | fresh |
| [evolution](evolution.md) | Bot evolution | `subsystem` | Issue pipelines, spec-kit stages, approvals, and Mission Control evolution APIs. | fresh |
| [plugins](plugins.md) | Plugin hooks | `subsystem` | In-process hook chains, channel plugin registry, slash bindings, and trigger mux. | fresh |
