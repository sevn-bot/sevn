# sevn.bot Skills Index

Canonical inventory of skills the agent can use. Authoritative source for the
shipped starter at ``src/sevn/data/skills/INDEX.md`` (bundled in the wheel).
At runtime each workspace copies it to ``<workspace>/skills/INDEX.md`` on
gateway boot / onboarding when missing. The workspace copy is authoritative
for user edits (see ``PROBLEMS.md`` §Priority 1.a).

**Sync invariants** (enforced by `scripts/check_skills_index.py`):

- every skill under `src/sevn/data/bundled_skills/core/<name>/SKILL.md` has a row here
- every row here resolves to a `bundled_skills/core/<name>/` directory

**Format.** One row per skill. `name` and `description` are mandatory; the function
`sevn.data.skills_index.read_skills_index()` returns `{name: description}`. Additional
columns are for human / LLM-prompt rendering and ignored by the parser.

| name | description |
|------|-------------|
| browser-harness | Thin CDP harness with extendable helpers.py for open-ended browser control. |
| canvas | Cursor Canvas and rich analytical layouts via OpenUI compose helpers (`specs/11-tools-registry.md` §3.4, `specs/37-openui.md`). |
| code_graph_rag | CGR export reader + allowlisted cgr CLI (`specs/28-code-understanding.md` §2.2). |
| computer-use | Drive a computer via trycua/cua — host cua-driver MCP passthrough plus sandbox providers (docker/cloud/lume) through the cua CLI; opt-in; macOS-only |
| conventional_commit | Draft git commit messages using Conventional Commits 1.0.0. Use when the operator asks to commit, record changes in git, or before running git commit after editing code (including the sevn.bot c... |
| cua-agent | Autonomous GUI loop via cua-agent — model drives the screen toward a goal; requires computer-use enabled and explicit per-run operator approval (HITL). |
| cursor_cloud | Delegate code+PR work to Cursor Cloud Agent; returns PR, dashboard, and artifact links. |
| defuddle | Extract clean markdown from web pages with Defuddle CLI, removing clutter and navigation before saving or analyzing sources. |
| discogs-collection | Discogs user collection — folders, items, value, and collection search; confirm-gated writes. |
| discogs-database | Discogs public catalog — search, artist/release/master/label lookups, price suggestions, marketplace stats. |
| discogs-identity | Discogs authed user profile, lists, contributions, and whoami smoke-test. |
| discogs-marketplace | Discogs marketplace — inventory search, listings CRUD, orders, messages, and fee lookup; confirm-gated writes. |
| discogs-wantlist | Discogs user wantlist browse, search, and add/remove/edit; confirm-gated writes. |
| discogs-shared | Internal shared runtime for bundled Discogs skill scripts; not a model-facing research skill. |
| email-management | Multi-account IMAP and Gmail API mail read/search/send scripts. |
| gh-issues | GitHub issue lifecycle — templated create via gh CLI, authenticated view/watch/track + cron notify, plus list/comment. |
| gh-pr | Pull request lifecycle — list, view, create, merge, close, reviewers via integration_call. |
| github-manager | Advanced GitHub operations — branches, Actions, CI/CD secrets, environments, deployments via integration_call. |
| google-workspace | Gmail, Calendar, Drive, Contacts, Sheets, and Docs via OAuth2 Google Workspace APIs. |
| graphify | Knowledge-graph orientation for code (`specs/28-code-understanding.md` §2.4). |
| json-canvas | Create and edit Obsidian JSON Canvas `.canvas` files with nodes, edges, groups, and connections. |
| job-ops | Discover jobs across global + Europe boards, AI fit-score them against your resume, and optionally tailor a CV summary (JobOps port). |
| kokoro-tts | Local Kokoro ONNX text-to-speech engine backing the voice TTS pipeline (kokoro backend). Not a model-facing research skill. |
| last30days | Research any topic across Reddit, X, YouTube, HN, Polymarket, and the web from the last 30 days. |
| lcm | Lossless context search, drill-back, and conversation index (`specs/15-memory-lcm.md`). |
| lume | Apple-Silicon VM lifecycle via the lume CLI (run/stop/ls/pull); opt-in; also a computer-use sandbox target via `cua do switch lume` |
| media_generation | MiniMax media generation — image, video (t2v/i2v/s2v/fl2v/templates), voice clone/TTS, music — via media_generator L2 specialist with lean prompt templates and trace metadata. |
| mycode | Deterministic repo scan + MYCODE.md write (`specs/28-code-understanding.md` §2.4). |
| obsidian-bases | Create and edit Obsidian Bases `.base` files with views, filters, formulas, and summaries. |
| obsidian-cli | Interact with Obsidian vaults using Obsidian CLI to read, create, search, and manage notes, tasks, and properties. |
| obsidian-markdown | Create and edit Obsidian Flavored Markdown with wikilinks, embeds, callouts, properties, and other Obsidian syntax. |
| openwiki | LLM-generated agent wiki for a codebase (LangChain OpenWiki CLI). |
| pdf | Render markdown/HTML to workspace PDFs; extract text/tables; structured load/chunk. |
| printing-press-library | Starter-pack Printing Press CLIs — ESPN, flights, movies, recipes (Go binaries on PATH). |
| roam_code | Lightweight roam-code path Q&A (`specs/28-code-understanding.md` §2.2). |
| scheduling | Cron jobs and one-shot reminders via workspace trigger store (`specs/30-non-interactive-triggers.md`). |
| social_media_manager | Browser-first social monitoring across six platforms via the social_media_manager L2 specialist; unified X ops over browser\|twexapi; TwexAPI optional on X only (spec 36). |
| second_brain | Karpathy-style raw→wiki ingest, lint, and file-back flows (`specs/27-second-brain.md`). |
| sessions_management | Gateway sessions, history, send, spawn, yield, and status (`specs/17-gateway.md`). |
| skill_management | Authoring workflows for generated skills; pairs with native skill_create and promote_generated_skill (`specs/12-skills-system.md` §2.5). |
| telegram | Telegram inline custom buttons and forum supergroup helpers (Bot API + allowlist/userbot hooks). |
| sevn-diagnostics | sevn.bot operator repair playbooks for `sevn doctor --with-agent` (gateway, secrets, proxy, models, browser, voice). |
| yt-dlp | Download video/audio and metadata with yt-dlp (YouTube, Vimeo, X, TikTok, and allowlisted hosts). |
| proton-management | Proton suite CLI (Python port) — Pass, Mail, Drive, Calendar, Contacts, attachments, groups, RSVP. |
