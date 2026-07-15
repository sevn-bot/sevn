<!-- generated: do not edit by hand; run `sevn readme update skills` -->
# Skills system

> **Summary.** Curated inventory of bundled and workspace skills, loaders, and subprocess runners.

## Bundled skills

| Name | Path | Summary |
|------|------|---------|
| `browser-harness` | [`../../src/sevn/data/bundled_skills/core/browser-harness/SKILL.md`](../../src/sevn/data/bundled_skills/core/browser-harness/SKILL.md) | Thin CDP harness with extendable helpers.py for open-ended browser control. |
| `canvas` | [`../../src/sevn/data/bundled_skills/core/canvas/SKILL.md`](../../src/sevn/data/bundled_skills/core/canvas/SKILL.md) | Cursor Canvas and rich analytical layouts via OpenUI compose helpers (about-sevn.bot/specs/11-tools-registry.md §3.4, about-sevn.bot/specs/37-openui.md). |
| `code_graph_rag` | [`../../src/sevn/data/bundled_skills/core/code_graph_rag/SKILL.md`](../../src/sevn/data/bundled_skills/core/code_graph_rag/SKILL.md) | CGR export reader + allowlisted cgr CLI (about-sevn.bot/specs/28-code-understanding.md §2.2). |
| `computer-use` | [`../../src/sevn/data/bundled_skills/core/computer-use/SKILL.md`](../../src/sevn/data/bundled_skills/core/computer-use/SKILL.md) | Drive a computer via trycua/cua — host cua-driver MCP passthrough plus sandbox providers (docker/cloud/lume) through the cua CLI; opt-in; macOS-only |
| `conventional_commit` | [`../../src/sevn/data/bundled_skills/core/conventional_commit/SKILL.md`](../../src/sevn/data/bundled_skills/core/conventional_commit/SKILL.md) | Draft git commit messages using Conventional Commits 1.0.0. Use when the operator asks to commit, record changes in git, or before running git commit after editing code (including the sevn.bot checkout). |
| `cua-agent` | [`../../src/sevn/data/bundled_skills/core/cua-agent/SKILL.md`](../../src/sevn/data/bundled_skills/core/cua-agent/SKILL.md) | Autonomous GUI loop via cua-agent — model drives the screen toward a goal; requires computer-use enabled and explicit per-run operator approval (HITL). |
| `cursor_cloud` | [`../../src/sevn/data/bundled_skills/core/cursor_cloud/SKILL.md`](../../src/sevn/data/bundled_skills/core/cursor_cloud/SKILL.md) | Delegate code+PR work to Cursor Cloud Agent; returns PR, dashboard, and artifact links. |
| `email-management` | [`../../src/sevn/data/bundled_skills/core/email-management/SKILL.md`](../../src/sevn/data/bundled_skills/core/email-management/SKILL.md) | Multi-account IMAP and Gmail API mail read/search/send scripts. |
| `facebook-use` | [`../../src/sevn/data/bundled_skills/core/facebook-use/SKILL.md`](../../src/sevn/data/bundled_skills/core/facebook-use/SKILL.md) | Facebook workflows via a logged-in browser profile or CDP attach (feed read, search). |
| `gh-issues` | [`../../src/sevn/data/bundled_skills/core/gh-issues/SKILL.md`](../../src/sevn/data/bundled_skills/core/gh-issues/SKILL.md) | GitHub issue lifecycle — list, view, create, comment via integration_call. |
| `gh-pr` | [`../../src/sevn/data/bundled_skills/core/gh-pr/SKILL.md`](../../src/sevn/data/bundled_skills/core/gh-pr/SKILL.md) | Pull request lifecycle — list, view, create, merge, close, reviewers via integration_call. |
| `github-manager` | [`../../src/sevn/data/bundled_skills/core/github-manager/SKILL.md`](../../src/sevn/data/bundled_skills/core/github-manager/SKILL.md) | Advanced GitHub operations — branches, Actions, CI/CD secrets, environments, deployments via integration_call. |
| `graphify` | [`../../src/sevn/data/bundled_skills/core/graphify/SKILL.md`](../../src/sevn/data/bundled_skills/core/graphify/SKILL.md) | Knowledge-graph orientation for code (about-sevn.bot/specs/28-code-understanding.md §2.4). |
| `job-ops` | [`../../src/sevn/data/bundled_skills/core/job-ops/SKILL.md`](../../src/sevn/data/bundled_skills/core/job-ops/SKILL.md) | Discover jobs across global + Europe boards, AI fit-score them against your resume, and optionally tailor a CV summary. |
| `kokoro-tts` | [`../../src/sevn/data/bundled_skills/core/kokoro-tts/SKILL.md`](../../src/sevn/data/bundled_skills/core/kokoro-tts/SKILL.md) | Local Kokoro ONNX text-to-speech engine backing the voice TTS pipeline (kokoro backend). Not a model-facing research skill. |
| `last30days` | [`../../src/sevn/data/bundled_skills/core/last30days/SKILL.md`](../../src/sevn/data/bundled_skills/core/last30days/SKILL.md) | Research any topic across Reddit, X, YouTube, HN, Polymarket, and the web from the last 30 days — must run the research engine, not web-only summary. |
| `lcm` | [`../../src/sevn/data/bundled_skills/core/lcm/SKILL.md`](../../src/sevn/data/bundled_skills/core/lcm/SKILL.md) | Lossless context search, drill-back, and conversation index (about-sevn.bot/specs/15-memory-lcm.md). |
| `linkedin-use` | [`../../src/sevn/data/bundled_skills/core/linkedin-use/SKILL.md`](../../src/sevn/data/bundled_skills/core/linkedin-use/SKILL.md) | LinkedIn staff/company/connection scraping via logged-in browser + Voyager API (StaffSpy port). |
| `lume` | [`../../src/sevn/data/bundled_skills/core/lume/SKILL.md`](../../src/sevn/data/bundled_skills/core/lume/SKILL.md) | Apple-Silicon VM lifecycle via the lume CLI (run/stop/ls/pull); opt-in; also a computer-use sandbox target via cua do switch lume |
| `media_generation` | [`../../src/sevn/data/bundled_skills/core/media_generation/SKILL.md`](../../src/sevn/data/bundled_skills/core/media_generation/SKILL.md) | Generate images, video, and music via the MiniMax-backed media_generator specialist (spec 36 D8). |
| `mycode` | [`../../src/sevn/data/bundled_skills/core/mycode/SKILL.md`](../../src/sevn/data/bundled_skills/core/mycode/SKILL.md) | Deterministic repo scan + MYCODE.md write (about-sevn.bot/specs/28-code-understanding.md §2.4). |
| `openwiki` | [`../../src/sevn/data/bundled_skills/core/openwiki/SKILL.md`](../../src/sevn/data/bundled_skills/core/openwiki/SKILL.md) | LLM-generated agent wiki for a codebase (LangChain OpenWiki CLI). |
| `pdf` | [`../../src/sevn/data/bundled_skills/core/pdf/SKILL.md`](../../src/sevn/data/bundled_skills/core/pdf/SKILL.md) | Render markdown/HTML to workspace PDFs; extract text/tables; structured load/chunk. |
| `playwright-browser` | [`../../src/sevn/data/bundled_skills/core/playwright-browser/SKILL.md`](../../src/sevn/data/bundled_skills/core/playwright-browser/SKILL.md) | Web automation with CDP-first Playwright scripts (navigate, screenshot, click, extract text). |
| `printing-press-library` | [`../../src/sevn/data/bundled_skills/core/printing-press-library/SKILL.md`](../../src/sevn/data/bundled_skills/core/printing-press-library/SKILL.md) | Starter-pack Printing Press CLIs — ESPN, flights, movies, recipes (Go binaries on PATH). |
| `roam_code` | [`../../src/sevn/data/bundled_skills/core/roam_code/SKILL.md`](../../src/sevn/data/bundled_skills/core/roam_code/SKILL.md) | Lightweight roam-code path Q&A (about-sevn.bot/specs/28-code-understanding.md §2.2). |
| `scheduling` | [`../../src/sevn/data/bundled_skills/core/scheduling/SKILL.md`](../../src/sevn/data/bundled_skills/core/scheduling/SKILL.md) | Cron jobs and one-shot reminders via workspace trigger store (about-sevn.bot/specs/30-non-interactive-triggers.md). |
| `second_brain` | [`../../src/sevn/data/bundled_skills/core/second_brain/SKILL.md`](../../src/sevn/data/bundled_skills/core/second_brain/SKILL.md) | Karpathy-style raw→wiki ingest, lint, and file-back flows (about-sevn.bot/specs/27-second-brain.md). |
| `sessions_management` | [`../../src/sevn/data/bundled_skills/core/sessions_management/SKILL.md`](../../src/sevn/data/bundled_skills/core/sessions_management/SKILL.md) | Gateway sessions, history, send, spawn, yield, and status (about-sevn.bot/specs/17-gateway.md). |
| `sevn-diagnostics` | [`../../src/sevn/data/bundled_skills/core/sevn-diagnostics/SKILL.md`](../../src/sevn/data/bundled_skills/core/sevn-diagnostics/SKILL.md) | sevn.bot operator repair playbooks for sevn doctor --with-agent: gateway token, secrets store unlock, proxy health, model auth, browser/CDP, and voice backends. Uses the bundled solutions catalog — do not duplicate remediation text here. |
| `skill_management` | [`../../src/sevn/data/bundled_skills/core/skill_management/SKILL.md`](../../src/sevn/data/bundled_skills/core/skill_management/SKILL.md) | Authoring workflows for generated skills; pairs with native skill_create and promote_generated_skill (about-sevn.bot/specs/12-skills-system.md §2.5). |
| `social_media_manager` | [`../../src/sevn/data/bundled_skills/core/social_media_manager/SKILL.md`](../../src/sevn/data/bundled_skills/core/social_media_manager/SKILL.md) | Browser-first social monitoring across six platforms via CDP browser; TwexAPI optional on X only. |
| `telegram` | [`../../src/sevn/data/bundled_skills/core/telegram/SKILL.md`](../../src/sevn/data/bundled_skills/core/telegram/SKILL.md) | Telegram inline custom buttons and forum supergroup helpers (Bot API + allowlist/userbot hooks). |
| `telegram_test` | [`../../src/sevn/data/bundled_skills/core/telegram_test/SKILL.md`](../../src/sevn/data/bundled_skills/core/telegram_test/SKILL.md) | Run host-side Playwright Telegram E2E (sevn telegram-test) while building sevn.bot. Use after gateway/menu/session/diagnostics changes. Not in gateway container. |
| `x-use` | [`../../src/sevn/data/bundled_skills/core/x-use/SKILL.md`](../../src/sevn/data/bundled_skills/core/x-use/SKILL.md) | X (Twitter) workflows via a logged-in browser profile or CDP attach (timeline, search). |
| `yt-dlp` | [`../../src/sevn/data/bundled_skills/core/yt-dlp/SKILL.md`](../../src/sevn/data/bundled_skills/core/yt-dlp/SKILL.md) | Download video/audio and metadata with yt-dlp (YouTube, Vimeo, X, TikTok, and allowlisted hosts). |

## Runtime loaders

| Name | Path | Summary |
|------|------|---------|
| `__init__` | [`../../src/sevn/skills/__init__.py`](../../src/sevn/skills/__init__.py) | Module `src/sevn/skills/__init__.py`. |
| `browser_gc` | [`../../src/sevn/skills/browser_gc.py`](../../src/sevn/skills/browser_gc.py) | Module `src/sevn/skills/browser_gc.py`. |
| `browser_session` | [`../../src/sevn/skills/browser_session.py`](../../src/sevn/skills/browser_session.py) | Module `src/sevn/skills/browser_session.py`. |
| `capabilities` | [`../../src/sevn/skills/capabilities.py`](../../src/sevn/skills/capabilities.py) | Module `src/sevn/skills/capabilities.py`. |
| `computer_use` | [`../../src/sevn/skills/computer_use.py`](../../src/sevn/skills/computer_use.py) | Module `src/sevn/skills/computer_use.py`. |
| `cua_agent` | [`../../src/sevn/skills/cua_agent.py`](../../src/sevn/skills/cua_agent.py) | Module `src/sevn/skills/cua_agent.py`. |
| `cua_doctor_check` | [`../../src/sevn/skills/cua_doctor_check.py`](../../src/sevn/skills/cua_doctor_check.py) | Module `src/sevn/skills/cua_doctor_check.py`. |
| `cursor_cloud` | [`../../src/sevn/skills/cursor_cloud.py`](../../src/sevn/skills/cursor_cloud.py) | Module `src/sevn/skills/cursor_cloud.py`. |
| `email_management` | [`../../src/sevn/skills/email_management.py`](../../src/sevn/skills/email_management.py) | Module `src/sevn/skills/email_management.py`. |
| `entrypoints` | [`../../src/sevn/skills/entrypoints.py`](../../src/sevn/skills/entrypoints.py) | Module `src/sevn/skills/entrypoints.py`. |
| `errors` | [`../../src/sevn/skills/errors.py`](../../src/sevn/skills/errors.py) | Module `src/sevn/skills/errors.py`. |
| `index` | [`../../src/sevn/skills/index.py`](../../src/sevn/skills/index.py) | Module `src/sevn/skills/index.py`. |
| `lume` | [`../../src/sevn/skills/lume.py`](../../src/sevn/skills/lume.py) | Module `src/sevn/skills/lume.py`. |
| `manager` | [`../../src/sevn/skills/manager.py`](../../src/sevn/skills/manager.py) | Module `src/sevn/skills/manager.py`. |
| `manifest` | [`../../src/sevn/skills/manifest.py`](../../src/sevn/skills/manifest.py) | Module `src/sevn/skills/manifest.py`. |
| `models` | [`../../src/sevn/skills/models.py`](../../src/sevn/skills/models.py) | Module `src/sevn/skills/models.py`. |
| `openwiki` | [`../../src/sevn/skills/openwiki.py`](../../src/sevn/skills/openwiki.py) | Module `src/sevn/skills/openwiki.py`. |
| `openwiki_doctor_check` | [`../../src/sevn/skills/openwiki_doctor_check.py`](../../src/sevn/skills/openwiki_doctor_check.py) | Module `src/sevn/skills/openwiki_doctor_check.py`. |
| `openwiki_install` | [`../../src/sevn/skills/openwiki_install.py`](../../src/sevn/skills/openwiki_install.py) | Module `src/sevn/skills/openwiki_install.py`. |
| `openwiki_secrets` | [`../../src/sevn/skills/openwiki_secrets.py`](../../src/sevn/skills/openwiki_secrets.py) | Module `src/sevn/skills/openwiki_secrets.py`. |
| `security_scan` | [`../../src/sevn/skills/security_scan.py`](../../src/sevn/skills/security_scan.py) | Module `src/sevn/skills/security_scan.py`. |
| `social_browser` | [`../../src/sevn/skills/social_browser.py`](../../src/sevn/skills/social_browser.py) | Module `src/sevn/skills/social_browser.py`. |
| `social_media_manager` | [`../../src/sevn/skills/social_media_manager.py`](../../src/sevn/skills/social_media_manager.py) | Module `src/sevn/skills/social_media_manager.py`. |
