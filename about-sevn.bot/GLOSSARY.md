# Glossary

Domain / ubiquitous-language terms for sevn.bot. Filled lazily by the
`domain-modeling` skill (`spec-kit-wave/skills/domain-modeling/`, adopted in a
later wave of `docs/mattpocock-skills-integration.md`). Resolved by
`spec-kit-wave/scripts/context_paths.py` and `skw.toml [context].glossary` —
never hardcoded in a skill.

**Non-published:** see [`decisions/README.md`](decisions/README.md) — this
file carries no `_docsys/manifest.toml` entry.

## Terms

| Term | Definition | Primary code / doc |
| --- | --- | --- |
| Gateway | Long-lived process that accepts channel ingress, runs the turn spine (triage → executor → outbound), and hosts Mission Control. | [`agent_turn.py`](src/sevn/gateway/agent_turn.py), [spec-17-gateway](spec-17-gateway) |
| Triager | Routing brain that emits `TriageResult` (tier, intent, tools) per turn without executing tools. | [`run.py`](src/sevn/agent/triager/run.py), [spec-13-rlm-triager](spec-13-rlm-triager) |
| Tier A / B / C / D | Executor tiers: A = canned replies only; B = pydantic-ai tool loop; C/D = planner / Lambda-RLM backends. | [ARCHITECTURE.md](ARCHITECTURE.md), [spec-14-executor-tier-b](spec-14-executor-tier-b) |
| Egress proxy | Shared-secret HTTP broker for `/llm/*`, `/web/*`, and integration calls so gateway/agent never hold raw provider keys. | [`auth.py`](src/sevn/proxy/auth.py), [spec-07-egress-proxy](spec-07-egress-proxy) |
| LCM | Lossless Context Management — SQLite-backed conversation memory with compaction. | [`assemble.py`](src/sevn/lcm/assemble.py), [spec-15-memory-lcm](spec-15-memory-lcm) |
| Second Brain | Filesystem wiki vault (`raw/`, `wiki/`) with Obsidian-compatible layout; not a sync daemon. | [`paths.py`](src/sevn/second_brain/paths.py), [spec-27-second-brain](spec-27-second-brain) |
| OpenUI | Agent-generated HTML panels via `openui_render`, CSP-wrapped and delivered on Telegram/webchat. | [`bridge.py`](src/sevn/ui/openui/bridge.py), [spec-37-openui](spec-37-openui) |
| Sub-agent (L1/L2) | Tracked concurrent role runs (L1) that may spawn workers/specialists (L2); `gateway.queue_mode=multi` classifies busy-session traffic. | [spec-36-sub-agents](spec-36-sub-agents) |
| Mission Control | Same-process dashboard SPA for traces, config, sub-agents, evolution, and operator controls. | [`tab_registry.py`](src/sevn/ui/dashboard/tab_registry.py), [spec-24-dashboard](spec-24-dashboard) |

<!-- HUMAN-INPUT[owner=operator]: Confirm or refine ambiguous terms (e.g. "steer" vs "cancel" queue semantics, "dreaming" vs LCM boundary) before publishing this glossary broadly. -->
