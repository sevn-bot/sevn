# Design specs index

Compact map for agents. Normative spec bodies are about-docs entries;
see [spec-00-foundation](spec-00-foundation) through [spec-37-openui](spec-37-openui)
and the generated table in [about-sevn.bot/specs/README.md](about-sevn.bot/specs/README.md).

| # | Spec id | Scope (summary) | Parent PRD |
| --- | --- | --- | --- |
| 00 | [spec-00-foundation](spec-00-foundation) | Deliver the lowest layer every later spec assumes: a src/sevn/ package layout, uv-managed Python 3.12+ project (hatchlin | prd-00-main |
| 01 | [spec-01-system-overview](spec-01-system-overview) | Give implementers a single picture of the runtime before feature work: package boundaries under src/sevn/, allowed impor | prd-00-main |
| 02 | [spec-02-config-and-workspace](spec-02-config-and-workspace) | Provide a single, testable configuration surface before storage, tracing, proxy, and gateway work: locate sevn.json, val | prd-06-setup-and-operations |
| 03 | [spec-03-storage](spec-03-storage) | Own application persistence: connection setup (WAL, foreign keys), versioned migrations, canonical sevn.db path, optiona | prd-02-personality-and-memory |
| 04 | [spec-04-tracing](spec-04-tracing) | Provide durable trace sinks that implement TraceSink without ever throwing through emit, so instrumentation stays off th | prd-07-mission-control |
| 05 | [spec-05-llm-transports](spec-05-llm-transports) | Normalize provider-shaped JSON over async HTTP to a single egress base URL (SEVN_PROXY_URL / ProcessSettings.proxy_url), | prd-05-cost-and-providers |
| 06 | [spec-06-secrets](spec-06-secrets) | Deliver a single trust boundary for credentials: backend modules + TTL cache under src/sevn/security/, wired exclusively | prd-03-trust-and-control |
| 07 | [spec-07-egress-proxy](spec-07-egress-proxy) | Product pairing (v1). Deployment, paired daemon install, onboarding validation, and Mission Control management of the pr | prd-03-trust-and-control |
| 08 | [spec-08-sandbox](spec-08-sandbox) | Deliver a single tool-execution sandbox used by sandbox_exec, exec / safebash (when routed through the execution sandbox | prd-03-trust-and-control |
| 09 | [spec-09-security-scanner](spec-09-security-scanner) | Deliver a single scanner subsystem that runs in the gateway process so hostile content is filtered before the Triager or | prd-03-trust-and-control |
| 10 | [spec-10-schema-ontology](spec-10-schema-ontology) | Define the runtime ontology for Triager output and related labels across the agent core: canonical field names, closed e | prd-04-getting-things-done |
| 11 | [spec-11-tools-registry](spec-11-tools-registry) | Own the Layer-3 tool callables and Layer-2 framework adapters that every executor tier uses: one implementation per tool | prd-04-getting-things-done |
| 12 | [spec-12-skills-system](spec-12-skills-system) | Own everything under workspace/skills/: how skills are discovered, validated, indexed for routing (spec-10-schema-ontolo | prd-04-getting-things-done |
| 13 | [spec-13-rlm-triager](spec-13-rlm-triager) | The Triager is the routing brain (prd-04-getting-things-done §5.1–§5.2): a single, tool-less outbound generation step th | prd-04-getting-things-done |
| 14 | [spec-14-executor-tier-b](spec-14-executor-tier-b) | Tier B is the default “do work” executor for messages the Triager classifies as complexity == B (prd-04-getting-things-d | prd-04-getting-things-done |
| 15 | [spec-15-memory-lcm](spec-15-memory-lcm) | LCM is the lossless conversation memory for a workspace (prd-02-personality-and-memory §5.2–§5.4): every qualifying mess | prd-02-personality-and-memory |
| 16 | [spec-16-harness-discipline](spec-16-harness-discipline) | Harness discipline: background task logging, operator PATH augmentation, and gateway/agent harness hooks under agent/har | prd-04-getting-things-done |
| 17 | [spec-17-gateway](spec-17-gateway) | Run the long-lived gateway process that accepts channel ingress (Telegram poll/webhook, webchat WS), normalises messages | prd-01-conversational-experience |
| 18 | [spec-18-channel-telegram](spec-18-channel-telegram) | Deliver the primary daily-driver channel for personal messaging: a ChannelAdapter implementation that normalises Telegra | prd-01-conversational-experience |
| 19 | [spec-19-channel-webui](spec-19-channel-webui) | Deliver the browser conversational surface required by prd-01-conversational-experience §5.1: owner-only WebSocket chat, | prd-01-conversational-experience |
| 20 | [spec-20-voice](spec-20-voice) | Own the provider-chain facades for speech-to-text and text-to-speech so the gateway can: | prd-01-conversational-experience |
| 21 | [spec-21-executor-tier-cd](spec-21-executor-tier-cd) | Tier C/D is the planned-work executor for messages the Triager classifies as complexity == C or complexity == D (prd-04- | prd-04-getting-things-done |
| 22 | [spec-22-onboarding](spec-22-onboarding) | Deliver the merge + validation + promotion pipeline every setup path shares so sevn.json stays the single source of trut | prd-06-setup-and-operations |
| 23 | [spec-23-cli](spec-23-cli) | Deliver the primary operator and automation surface for install, upgrades, health checks, workspace + daemon lifecycle,  | prd-06-setup-and-operations |
| 24 | [spec-24-dashboard](spec-24-dashboard) | Deliver Mission Control: a same-process dashboard (prd-07-mission-control) so the owner can inspect traces, costs, provi | prd-07-mission-control |
| 25 | [spec-25-cicd-full](spec-25-cicd-full) | Grow spec-00-foundation’s minimal verify loop into a phase-strict delivery pipeline: broader CI matrices, checked-in Doc | prd-06-setup-and-operations |
| 26 | [spec-26-claude-agent](spec-26-claude-agent) | - N/A: Spec rejected — no implementation rows for v0.0.2. | prd-08-coding-companion |
| 27 | [spec-27-second-brain](spec-27-second-brain) | Deliver the Second Brain subsystem: filesystem wiki engine + agent surface so operators curate sources in raw/ and maint | prd-09-knowledge-base |
| 28 | [spec-28-code-understanding](spec-28-code-understanding) | Deliver the code-orientation stack the coding companion PRD names: five orthogonal capabilities (MYCODE, Memgraph CGR, c | prd-08-coding-companion |
| 29 | [spec-29-cursor-cloud-agent](spec-29-cursor-cloud-agent) | Let operators and agents launch, poll, and inspect Cursor Cloud Agents against any GitHub/GitLab repo when skills.cursor | prd-04-getting-things-done |
| 30 | [spec-30-non-interactive-triggers](spec-30-non-interactive-triggers) | Deliver non-interactive dispatch: external events (“something happened”) and schedules (“tick”) compile to DispatchReque | prd-11-automation-and-triggers |
| 31 | [spec-31-memory-dreaming](spec-31-memory-dreaming) | Provide scored consolidation from short-term recall signals into curated long-term prose (MEMORY.md) on a daily (configu | prd-02-personality-and-memory |
| 32 | [spec-32-memory-honcho](spec-32-memory-honcho) | Deliver an opt-in inferred profile that accumulates stable operator-facing facts (preferences, recurring context the ope | prd-02-personality-and-memory |
| 33 | [spec-33-self-improvement](spec-33-self-improvement) | Deliver src/sevn/self_improve/: ingest traces + session artefacts + explicit user feedback into trajectory_fact rows, de | prd-12-self-improvement |
| 34 | [spec-34-plugin-hooks](spec-34-plugin-hooks) | Deliver the in-process extension layer that intercepts existing tool and terminal I/O paths and registers dispatcher-lev | prd-13-extensibility |
| 35 | [spec-35-bot-evolution](spec-35-bot-evolution) | Deliver src/sevn/evolution/ and the operator-facing Evolution surface so sevn.bot can evolve its own codebase as a first | prd-07-mission-control |
| 36 | [spec-36-sub-agents](spec-36-sub-agents) | Level-1 sub-agents (tracked, concurrent, killable role runs) that may spawn level-2 workers (incl. specialists); multi q | prd-04-getting-things-done |
| 37 | [spec-37-openui](spec-37-openui) | Deliver OpenUI: explicit openui_render tool calls produce sanitised, CSP-wrapped, size-capped HTML (live or rasterised)  | prd-10-generated-ui |
