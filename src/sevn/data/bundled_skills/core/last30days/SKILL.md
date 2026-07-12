---
name: last30days
description: Research any topic across Reddit, X, YouTube, HN, Polymarket, and the web from the last 30 days — must run the research engine, not web-only summary.
version: "3.3.2"
see_also:
  - yt-dlp
  - x-use
  - serp
  - web_search
  - get_page_content
max_wall_seconds: 900
egress:
  - reddit.com
  - redd.it
  - old.reddit.com
  - news.ycombinator.com
  - polymarket.com
  - github.com
  - api.github.com
  - x.com
  - twitter.com
  - twimg.com
  - youtube.com
  - youtu.be
  - googlevideo.com
  - ytimg.com
  - tiktok.com
  - tiktokcdn.com
  - instagram.com
  - cdninstagram.com
  - threads.net
  - bsky.app
  - api.scrapecreators.com
  - openrouter.ai
  - search.brave.com
  - api.search.brave.com
scripts:
  - path: scripts/research.py
    description: Run the last30days v3 multi-source research engine (Reddit, HN, Polymarket, GitHub, optional X/YouTube/TikTok).
    args_overview: "--topic TEXT [--emit compact|md|html] [--plan PATH] [--x-handle HANDLE] [--github-user USER] [--subreddits LIST] [--dry-run]"
    abortable: true
  - path: scripts/briefing.py
    description: Watchlist briefing JSON (requires topics in ~/.local/share/last30days/research.db).
  - path: scripts/filter_raw.py
    description: Filter a saved raw last30days markdown file by item date (default last 24h).
    args_overview: "--path PATH [--since-hours N | --since-date YYYY-MM-DD]"
    abortable: false
  - path: scripts/daily_digest.py
    description: Cron entry — watchlist run-one then new-only briefing JSON (URL dedup; no repeat shares).
    args_overview: "run --topic TEXT"
    abortable: true
  - path: scripts/evaluate_search_quality.py
    description: Upstream search-quality evaluator vendored from last30days-skill.
  - path: scripts/last30days.py
    description: Upstream research engine entrypoint invoked by research.py wrapper.
  - path: scripts/store.py
    description: Upstream memory/store helper vendored from last30days-skill.
  - path: scripts/watchlist.py
    description: Upstream watchlist helper vendored from last30days-skill.
---
# sevn.bot execution model

You are inside the **last30days** bundled skill. Follow this harness — not generic web research.

1. **`load_skill("last30days")`** — menu intro only; read **`references/contract.md`** before research/synthesis.
2. **Pre-flight** with **`serp`** (prefer, no key) or **`web_search`** (Brave key) for handle/repo/subreddit resolution (Steps 0.45–0.55 below).
3. **Write** query-plan JSON to the workspace with native **`write`** when `--plan` is required.
4. **`run_skill_script(skill_name="last30days", script_path="research", args=[...])`** — read **`data.stdout`** for engine output (compact/md). Never call upstream `last30days.py` directly; the wrapper emits the sevn JSON envelope.
5. **Supplement** with **`serp`** / **`web_search`** after the engine (Step 2.5), not instead of it.
6. **Synthesize** per the LAWs in **`references/contract.md`** (badge, `What I learned:`, KEY PATTERNS, engine footer). Do not append a trailing `Sources:` block.

**Paths:** `SEVN_SKILL_DIR` is injected by the skill runner. Research files default to **`$SEVN_WORKSPACE/out/last30days/`** via the wrapper (`LAST30DAYS_MEMORY_DIR`).

## Briefing vs research (do not conflate)

| User intent | Script | On empty watchlist |
|-------------|--------|---------------------|
| “briefing”, “top links from watchlist”, “morning digest” (interactive) | **`scripts/briefing.py generate`** | **Stop** — script exits `NO_TOPICS` / `NO_ENABLED`; do **not** retry via worktree, `process`, or bash |
| **Daily cron / scheduled digest** (new items only) | **`scripts/daily_digest.py run --topic "…"`** | Fail with `NOT_FOUND` if topic missing — offer `watchlist.py add` |
| Ad hoc “run last30days on {topic}” (full report file) | **`scripts/research.py`** | N/A — needs `--topic` |

**Nothing calls the watchlist automatically.** The `schedule` field on `watchlist.py add` is metadata only inside sevn — **sevn cron** (or you) must invoke `daily_digest.py` or `watchlist.py run-one`.

**Daily cron wiring (preferred):** one job, one script, new-only delivery:

```text
run_skill_script(skill="last30days", script="scripts/daily_digest.py",
  argv=["run", "--topic", "Agentic AI eval loops"])
```

- **`status: ok`** — synthesize a concise Telegram briefing from `data.topics[].findings` / `data.top_finding` (use `source_url`).
- **`status: no_new`** — one line: research ran, nothing new today (`total_updated` may be > 0).
- **Do not** also run `research.py` or `briefing.py generate` on the same cron fire — duplicates work and can re-share old items.

**Briefing hard stop (interactive):** call **`run_skill_script(..., briefing.py, ["generate"])` once**. If the envelope is `ok:false` with code `NO_TOPICS` or `NO_ENABLED`, explain that watchlist DB is empty and offer `watchlist.py add` — **never** burn rounds re-running the same script or alternate paths.

**Schedules question:** for “what is scheduled?” call **`scheduling` → cron_list`** *and* **`watchlist.py list`** — they are different stores.

## Post-research date filters (no sandbox loops)

After **`research.py`** writes raw markdown under **`out/last30days/`**, filter by recency with **`run_skill_script(..., filter_raw.py, ["--path", "out/last30days/<file>.md", "--since-hours", "24"])`**. Use **`read`** / **`search_in_file`** for spot checks. **Do not** use **`run_code`** with `import os`, `pathlib`, or shell grep/sed/awk over workspace files — CodeMode sandbox friction wastes turns.

**Dependencies (operator):** Python 3.12+ and **node** on PATH for X (Bird client). Optional: `gh`, `yt-dlp` (`uv sync --extra yt-dlp`), API keys in `~/.config/last30days/.env` (ScrapeCreators, OpenRouter, Brave, X cookies). Reddit/HN/Polymarket/GitHub work without keys.

**Upstream:** [mvanhorn/last30days-skill](https://github.com/mvanhorn/last30days-skill) (MIT). Refresh vendored engine with `scripts/sync_last30days_upstream.sh`.

---

# Skill contract (progressive load)

The full research contract (LAWs, badge rules, synthesis steps) lives in **`references/contract.md`**.

Before any research run or synthesis:

1. **`read`** `skills/core/last30days/references/contract.md` with `limit`/`offset`, or **`search_in_file`** for specific LAW/step text.
2. Do **not** improvise research output without reading the contract.

For operational checks only, the execution model above plus **`list_registry`** and **`run_skill_script`** `--dry-run` is sufficient.
