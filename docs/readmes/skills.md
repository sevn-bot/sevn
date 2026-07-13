<!-- generated: do not edit by hand; run `sevn readme update skills` -->
# Skills system

> **Summary.** Curated inventory of bundled and workspace skills, loaders, and subprocess runners.

## Bundled skills

| Name | Path | Summary |
|------|------|---------|
| `browser-harness` | [`../../src/sevn/data/bundled_skills/core/browser-harness/SKILL.md`](../../src/sevn/data/bundled_skills/core/browser-harness/SKILL.md) | Thin CDP harness with extendable helpers.py for open-ended browser control. |
| `canvas` | [`../../src/sevn/data/bundled_skills/core/canvas/SKILL.md`](../../src/sevn/data/bundled_skills/core/canvas/SKILL.md) | Cursor Canvas and rich analytical layouts via OpenUI compose helpers ('about-sevn.bot/specs/11-tools-registry.md' §3.4, 'about-sevn.bot/specs/29-openui.md'). |
| `code_graph_rag` | [`../../src/sevn/data/bundled_skills/core/code_graph_rag/SKILL.md`](../../src/sevn/data/bundled_skills/core/code_graph_rag/SKILL.md) | CGR export reader + allowlisted cgr CLI ('about-sevn.bot/specs/28-code-understanding.md' §2.2). |
| `computer-use` | [`../../src/sevn/data/bundled_skills/core/computer-use/SKILL.md`](../../src/sevn/data/bundled_skills/core/computer-use/SKILL.md) | >- Drive a computer via trycua/cua — host cua-driver MCP passthrough plus sandbox providers (docker/cloud/lume) through the cua CLI; opt-in; macOS-only |
| `conventional_commit` | [`../../src/sevn/data/bundled_skills/core/conventional_commit/SKILL.md`](../../src/sevn/data/bundled_skills/core/conventional_commit/SKILL.md) | >- Draft git commit messages using Conventional Commits 1.0.0. |
| `cua-agent` | [`../../src/sevn/data/bundled_skills/core/cua-agent/SKILL.md`](../../src/sevn/data/bundled_skills/core/cua-agent/SKILL.md) | >- Autonomous GUI loop via cua-agent — model drives the screen toward a goal; requires computer-use enabled and explicit per-run operator approval (HITL). |
| `cursor_cloud` | [`../../src/sevn/data/bundled_skills/core/cursor_cloud/SKILL.md`](../../src/sevn/data/bundled_skills/core/cursor_cloud/SKILL.md) | Delegate code+PR work to Cursor Cloud Agent; returns PR, dashboard, and artifact links. |
| `email-management` | [`../../src/sevn/data/bundled_skills/core/email-management/SKILL.md`](../../src/sevn/data/bundled_skills/core/email-management/SKILL.md) | Multi-account IMAP and Gmail API mail read/search/send scripts. |
| `facebook-use` | [`../../src/sevn/data/bundled_skills/core/facebook-use/SKILL.md`](../../src/sevn/data/bundled_skills/core/facebook-use/SKILL.md) | Facebook workflows via a logged-in browser profile or CDP attach (feed read, search). |
| `gh-issues` | [`../../src/sevn/data/bundled_skills/core/gh-issues/SKILL.md`](../../src/sevn/data/bundled_skills/core/gh-issues/SKILL.md) | GitHub issue lifecycle — list, view, create, comment via integration_call. |
| `gh-pr` | [`../../src/sevn/data/bundled_skills/core/gh-pr/SKILL.md`](../../src/sevn/data/bundled_skills/core/gh-pr/SKILL.md) | Pull request lifecycle — list, view, create, merge, close, reviewers via integration_call. |
| `github-manager` | [`../../src/sevn/data/bundled_skills/core/github-manager/SKILL.md`](../../src/sevn/data/bundled_skills/core/github-manager/SKILL.md) | Advanced GitHub operations — branches, Actions, CI/CD secrets, environments, deployments via integration_call. |
| `graphify` | [`../../src/sevn/data/bundled_skills/core/graphify/SKILL.md`](../../src/sevn/data/bundled_skills/core/graphify/SKILL.md) | Knowledge-graph orientation for code ('about-sevn.bot/specs/28-code-understanding.md' §2.4). |
| `job-ops` | [`../../src/sevn/data/bundled_skills/core/job-ops/SKILL.md`](../../src/sevn/data/bundled_skills/core/job-ops/SKILL.md) | Discover jobs across global + Europe boards, AI fit-score them against your resume, and optionally tailor a CV summary. |
| `kokoro-tts` | [`../../src/sevn/data/bundled_skills/core/kokoro-tts/SKILL.md`](../../src/sevn/data/bundled_skills/core/kokoro-tts/SKILL.md) | Local Kokoro ONNX text-to-speech engine backing the voice TTS pipeline (kokoro backend). |
| `last30days` | [`../../src/sevn/data/bundled_skills/core/last30days/SKILL.md`](../../src/sevn/data/bundled_skills/core/last30days/SKILL.md) | Research any topic across Reddit, X, YouTube, HN, Polymarket, and the web from the last 30 days — must run the research engine, not web-only summary. |
| `lcm` | [`../../src/sevn/data/bundled_skills/core/lcm/SKILL.md`](../../src/sevn/data/bundled_skills/core/lcm/SKILL.md) | Lossless context search, drill-back, and conversation index ('about-sevn.bot/specs/15-memory-lcm.md'). |
| `linkedin-use` | [`../../src/sevn/data/bundled_skills/core/linkedin-use/SKILL.md`](../../src/sevn/data/bundled_skills/core/linkedin-use/SKILL.md) | LinkedIn staff/company/connection scraping via logged-in browser + Voyager API (StaffSpy port). |
| `lume` | [`../../src/sevn/data/bundled_skills/core/lume/SKILL.md`](../../src/sevn/data/bundled_skills/core/lume/SKILL.md) | >- Apple-Silicon VM lifecycle via the lume CLI (run/stop/ls/pull); opt-in; also a computer-use sandbox target via 'cua do switch lume' |
| `media_generation` | [`../../src/sevn/data/bundled_skills/core/media_generation/SKILL.md`](../../src/sevn/data/bundled_skills/core/media_generation/SKILL.md) | Generate images, video, and music via the MiniMax-backed media_generator specialist (spec 36 D8). |
| `mycode` | [`../../src/sevn/data/bundled_skills/core/mycode/SKILL.md`](../../src/sevn/data/bundled_skills/core/mycode/SKILL.md) | Deterministic repo scan + MYCODE.md write ('about-sevn.bot/specs/28-code-understanding.md' §2.4). |
| `openwiki` | [`../../src/sevn/data/bundled_skills/core/openwiki/SKILL.md`](../../src/sevn/data/bundled_skills/core/openwiki/SKILL.md) | LLM-generated agent wiki for a codebase (LangChain OpenWiki CLI). |
| `pdf` | [`../../src/sevn/data/bundled_skills/core/pdf/SKILL.md`](../../src/sevn/data/bundled_skills/core/pdf/SKILL.md) | Render markdown/HTML to workspace PDFs; extract text/tables; structured load/chunk. |
| `playwright-browser` | [`../../src/sevn/data/bundled_skills/core/playwright-browser/SKILL.md`](../../src/sevn/data/bundled_skills/core/playwright-browser/SKILL.md) | Web automation with CDP-first Playwright scripts (navigate, screenshot, click, extract text). |
| `printing-press-library` | [`../../src/sevn/data/bundled_skills/core/printing-press-library/SKILL.md`](../../src/sevn/data/bundled_skills/core/printing-press-library/SKILL.md) | Starter-pack Printing Press CLIs — ESPN, flights, movies, recipes (Go binaries on PATH). |
| `roam_code` | [`../../src/sevn/data/bundled_skills/core/roam_code/SKILL.md`](../../src/sevn/data/bundled_skills/core/roam_code/SKILL.md) | Lightweight roam-code path Q&A ('about-sevn.bot/specs/28-code-understanding.md' §2.2). |
| `scheduling` | [`../../src/sevn/data/bundled_skills/core/scheduling/SKILL.md`](../../src/sevn/data/bundled_skills/core/scheduling/SKILL.md) | Cron jobs and one-shot reminders via workspace trigger store ('about-sevn.bot/specs/30-non-interactive-triggers.md'). |
| `second_brain` | [`../../src/sevn/data/bundled_skills/core/second_brain/SKILL.md`](../../src/sevn/data/bundled_skills/core/second_brain/SKILL.md) | Karpathy-style raw→wiki ingest, lint, and file-back flows ('about-sevn.bot/specs/27-second-brain.md'). |
| `sessions_management` | [`../../src/sevn/data/bundled_skills/core/sessions_management/SKILL.md`](../../src/sevn/data/bundled_skills/core/sessions_management/SKILL.md) | Gateway sessions, history, send, spawn, yield, and status ('about-sevn.bot/specs/17-gateway.md'). |
| `sevn-diagnostics` | [`../../src/sevn/data/bundled_skills/core/sevn-diagnostics/SKILL.md`](../../src/sevn/data/bundled_skills/core/sevn-diagnostics/SKILL.md) | >- sevn.bot operator repair playbooks for 'sevn doctor --with-agent': gateway token, secrets store unlock, proxy health, model auth, browser/CDP, and voice backends. |
| `skill_management` | [`../../src/sevn/data/bundled_skills/core/skill_management/SKILL.md`](../../src/sevn/data/bundled_skills/core/skill_management/SKILL.md) | Authoring workflows for generated skills; pairs with native skill_create and promote_generated_skill ('about-sevn.bot/specs/12-skills-system.md' §2.5). |
| `telegram` | [`../../src/sevn/data/bundled_skills/core/telegram/SKILL.md`](../../src/sevn/data/bundled_skills/core/telegram/SKILL.md) | Telegram inline custom buttons and forum supergroup helpers (Bot API + allowlist/userbot hooks). |
| `telegram_test` | [`../../src/sevn/data/bundled_skills/core/telegram_test/SKILL.md`](../../src/sevn/data/bundled_skills/core/telegram_test/SKILL.md) | >- Run host-side Playwright Telegram E2E (sevn telegram-test) while building sevn.bot. |
| `x-use` | [`../../src/sevn/data/bundled_skills/core/x-use/SKILL.md`](../../src/sevn/data/bundled_skills/core/x-use/SKILL.md) | X (Twitter) workflows via a logged-in browser profile or CDP attach (timeline, search). |
| `yt-dlp` | [`../../src/sevn/data/bundled_skills/core/yt-dlp/SKILL.md`](../../src/sevn/data/bundled_skills/core/yt-dlp/SKILL.md) | Download video/audio and metadata with yt-dlp (YouTube, Vimeo, X, TikTok, and allowlisted hosts). |

## Runtime loaders

| Name | Path | Summary |
|------|------|---------|
| `__init__` | [`../../src/sevn/skills/__init__.py`](../../src/sevn/skills/__init__.py) | Workspace skills subsystem ('about-sevn.bot/specs/12-skills-system.md'). |
| `browser_gc` | [`../../src/sevn/skills/browser_gc.py`](../../src/sevn/skills/browser_gc.py) | Best-effort cleanup for session-scoped browser profiles and registries. |
| `browser_session` | [`../../src/sevn/skills/browser_session.py`](../../src/sevn/skills/browser_session.py) | Session-scoped browser lifecycle — profile, CDP, registry, spawn/attach/close. |
| `capabilities` | [`../../src/sevn/skills/capabilities.py`](../../src/sevn/skills/capabilities.py) | ''capabilities[]'' rows for ''load_skill'' payloads (''about-sevn.bot/specs/12-skills-system.md'' §2.3). |
| `computer_use` | [`../../src/sevn/skills/computer_use.py`](../../src/sevn/skills/computer_use.py) | Computer-use skill gates and Cua Driver MCP passthrough ('the design docs' §17). |
| `cua_agent` | [`../../src/sevn/skills/cua_agent.py`](../../src/sevn/skills/cua_agent.py) | Cua Agent skill gates and per-run approval ('the design docs' §17a). |
| `cua_doctor_check` | [`../../src/sevn/skills/cua_doctor_check.py`](../../src/sevn/skills/cua_doctor_check.py) | Cua computer-use skill doctor probes ('the design docs' W0.5 / W6). |
| `cursor_cloud` | [`../../src/sevn/skills/cursor_cloud.py`](../../src/sevn/skills/cursor_cloud.py) | Opt-in gate for bundled ''cursor_cloud'' core skill ('about-sevn.bot/specs/29-cursor-cloud-agent.md'). |
| `email_management` | [`../../src/sevn/skills/email_management.py`](../../src/sevn/skills/email_management.py) | Multi-account IMAP/API helpers for the bundled ''email-management'' skill. |
| `entrypoints` | [`../../src/sevn/skills/entrypoints.py`](../../src/sevn/skills/entrypoints.py) | Reserved setuptools entry-point row for ''sevn.skills'' ('about-sevn.bot/specs/12-skills-system.md' §2.1). |
| `errors` | [`../../src/sevn/skills/errors.py`](../../src/sevn/skills/errors.py) | Skill execution failures -> tool envelope codes (''about-sevn.bot/specs/11-tools-registry.md'' §3.1). |
| `index` | [`../../src/sevn/skills/index.py`](../../src/sevn/skills/index.py) | Executor / Triager index lines for skills ('about-sevn.bot/specs/12-skills-system.md' §2.3 narrative). |
| `lume` | [`../../src/sevn/skills/lume.py`](../../src/sevn/skills/lume.py) | Lume VM lifecycle skill gates ('the design docs' §17b). |
| `manager` | [`../../src/sevn/skills/manager.py`](../../src/sevn/skills/manager.py) | Skills registry: scan, validate, ''load_skill'' payloads, subprocess runners ('about-sevn.bot/specs/12'). |
| `manifest` | [`../../src/sevn/skills/manifest.py`](../../src/sevn/skills/manifest.py) | Parse ''SKILL.md'' YAML frontmatter + runnable fence metadata (specs 12 §3.1-§3.3). |
| `models` | [`../../src/sevn/skills/models.py`](../../src/sevn/skills/models.py) | On-disk skill records (manifest + filesystem provenance). |
| `openwiki` | [`../../src/sevn/skills/openwiki.py`](../../src/sevn/skills/openwiki.py) | Opt-in gate for bundled ''openwiki'' core skill. |
| `openwiki_doctor_check` | [`../../src/sevn/skills/openwiki_doctor_check.py`](../../src/sevn/skills/openwiki_doctor_check.py) | OpenWiki skill doctor probes when ''skills.openwiki.enabled'' is true. |
| `openwiki_install` | [`../../src/sevn/skills/openwiki_install.py`](../../src/sevn/skills/openwiki_install.py) | Install helpers for the LangChain OpenWiki npm CLI. |
| `openwiki_secrets` | [`../../src/sevn/skills/openwiki_secrets.py`](../../src/sevn/skills/openwiki_secrets.py) | Resolve ''skills.openwiki'' credential refs into subprocess env vars. |
| `security_scan` | [`../../src/sevn/skills/security_scan.py`](../../src/sevn/skills/security_scan.py) | SkillSpector wrapper for workspace skill security scans ('about-sevn.bot/specs/09-security-scanner.md'). |
| `social_browser` | [`../../src/sevn/skills/social_browser.py`](../../src/sevn/skills/social_browser.py) | Session-bound logged-in browser helpers for ''x-use'' and ''facebook-use'' skills. |
