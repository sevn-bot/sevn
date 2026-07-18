---
name: job-ops
description: Discover jobs across global + Europe boards, AI fit-score them against your resume, and optionally tailor a CV summary.
version: "0.1.0"
see_also:
  - browser
  - last30days
  - social_media_manager
egress:
  - api.adzuna.com
  - hiring.cafe
  - workingnomads.com
  - golangjobs.tech
  - supabase.co
  - jobindex.dk
  - startup.jobs
  - gradcracker.com
  - ukvisajobs.com
  - job.jobnet.dk
  - remoteok.com
  - remotive.com
  - himalayas.app
  - remote.co
  - linkedin.com
  - indeed.com
  - glassdoor.com
scripts:
  - path: scripts/search.py
    description: Run board extractors, normalize + dedupe jobs, and store them. Use --list-sources to see board ids.
    args_overview: "--query T1,T2 [--sources ids] [--country C] [--locations L] [--workplace-types remote,hybrid,onsite] [--results-wanted N] [--hours-old H] [--remote] [--list-sources]"
    abortable: true
  - path: scripts/score.py
    description: AI fit-score stored jobs (0-100 + recommendation, matched/missing keywords, tailoring tips, dealbreakers, posting legitimacy) against the operator resume using sevn's model tier.
    args_overview: "[--source id] [--limit N] [--rescore] [--dry-run]"
    abortable: true
  - path: scripts/review.py
    description: AI review of the stored resume (score + strengths/weaknesses/suggestions/missing keywords) using sevn's model tier.
    args_overview: "[--target TEXT]"
    abortable: true
  - path: scripts/tailor.py
    description: OPTIONAL (opt-in) — generate a tailored summary/headline/skills per job. Requires --enable.
    args_overview: "--enable [--source id] [--limit N] [--retailor]"
    abortable: true
  - path: scripts/cover_letter.py
    description: OPTIONAL (opt-in) — draft a text-only tailored cover letter for one job. Requires --enable.
    args_overview: "--enable --key KEY [--tone T]"
    abortable: true
  - path: scripts/interview_prep.py
    description: OPTIONAL (opt-in) — draft text-only interview prep (STAR+R stories, questions) for one job. Requires --enable.
    args_overview: "--enable --key KEY"
    abortable: true
  - path: scripts/track.py
    description: Update tracking (seen flag, status/applied/dates/notes/tags/interviews) for one stored job.
    args_overview: "--key KEY [--seen] [--unseen] [--status S] [--applied] [--applied-date D] [--due-date D] [--salary-range R] [--note N] [--tag T] [--interview I]"
    abortable: true
  - path: scripts/list_jobs.py
    description: List/filter stored jobs by source, tracking status, suitability score, and seen/new state.
    args_overview: "[--source id] [--status S] [--min-score N] [--unscored] [--new-only] [--mark-seen] [--limit N]"
    abortable: true
  - path: scripts/set_resume.py
    description: Register (or show) the operator resume/profile text used for scoring and tailoring.
    args_overview: "[--text T] [--file PATH] [--show]"
    abortable: true
---

# job-ops

Job **discovery + AI fit-scoring + optional CV tailoring**. Independent implementation
licensed **MIT** (see `LICENSE`). It covers the discovery/scoring pipeline only — no web
UI, database, email tracking, or PDF export.

Scope is **global + Europe boards only**. Region-specific non-Europe boards
(SEEK/AU-NZ, Naukri/India, WUZZUF/Egypt, Khamsat) are intentionally not included.

## Setup

```bash
uv sync --extra job-ops   # installs python-jobspy + selectolax
```

- **Adzuna** needs API creds: set `ADZUNA_APP_ID` and `ADZUNA_APP_KEY`.
- **jobspy** (LinkedIn/Indeed/Glassdoor) and browser boards need outbound network; jobspy is
  best-effort and anti-bot-sensitive.

## Boards (`--sources`)

| id | coverage | transport |
|----|----------|-----------|
| `jobspy` | LinkedIn, Indeed, Glassdoor (global) | python-jobspy |
| `adzuna` | global (needs creds) | httpx |
| `hiringcafe` | global | httpx (SSR) |
| `workingnomads` | remote, global | httpx |
| `remoteok` | remote, global | httpx (JSON API) |
| `remotive` | remote, global | httpx (JSON API) |
| `himalayas` | remote, global | httpx (JSON API) |
| `remoteco` | remote, global | own-CDP browser |
| `golangjobs` | Go roles, global | httpx |
| `startupjobs` | startups, global | own-CDP browser |
| `jobindex` | Denmark | httpx |
| `jobnet` | Denmark (public STAR board) | own-CDP browser |
| `gradcracker` | UK graduate engineering | own-CDP browser |
| `ukvisajobs` | UK visa sponsorship | own-CDP browser |

Run `search.py --list-sources` to print the live list.

## Workflow

```bash
# 1) Register your resume once (inline or from a file)
set_resume.py --file /path/to/resume.md

# 2) Discover jobs (defaults to all boards)
search.py --query "python engineer,backend developer" --country "united kingdom" \
  --sources jobspy,adzuna,hiringcafe,workingnomads --results-wanted 40

# 3) Score stored jobs against the resume
score.py --limit 20

# 4) Review the best matches
list_jobs.py --min-score 70 --limit 25

# 5) (optional) Critique the resume itself
review.py --target "python engineer, backend"

# 6) (optional) Tailor a CV summary for top matches
tailor.py --enable --source jobspy --limit 5

# 7) (optional) Draft a text-only cover letter / interview prep for one job
cover_letter.py --enable --key <dedupe_key>
interview_prep.py --enable --key <dedupe_key>

# 8) Track an application through its lifecycle
track.py --key <dedupe_key> --status applied --applied --applied-date 2026-07-05 --note "referred by X"
list_jobs.py --status applied
```

## Application tracking

`track.py` maintains an operator-managed lifecycle on each stored job: `status`
(`new`/`interested`/`applied`/`interviewing`/`offer`/`rejected`/`archived`), an
`applied` flag + `applied_date`, a `due_date`, an expected `salary_range`, and
append-only `notes`, `tags`, and `interviews` logs. `list_jobs.py --status` filters
by status. Tracking fields live in the same JSONL store and survive re-discovery.

## Drafting workflow (cover letter / interview prep)

`cover_letter.py` and `interview_prep.py` are **opt-in** (`--enable`) and target a
single job by `--key`. Output is **text-only** (plain text / Markdown) — no PDF or
LaTeX. Recommended pattern: the sevn agent drafts with these scripts, then reviews
and refines the draft with the operator before anything is sent. The skill never
submits or sends applications.

Jobs persist to `<content_root>/job-ops/jobs.jsonl`; the resume to
`<content_root>/job-ops/resume.md`. De-duplication is keyed on `(source, source_job_id | job_url)`.
Re-running `search.py` upserts rather than duplicating: a matching job is merged forward (prior
listing data, AI enrichments, and tracking are kept; populated fresh fields win).

## Seen / new jobs

Every job is stamped with `first_seen` (UTC) when first discovered and carries a `seen` flag so you
only review each posting once:

```bash
# Show only jobs you haven't seen yet, and mark the returned rows as seen
list_jobs.py --new-only --mark-seen --limit 25

# Later runs of --new-only will exclude those; re-surface one if needed
track.py --key <dedupe_key> --unseen
```

`--mark-seen` marks exactly the rows returned (respecting `--limit`/filters); `track.py --seen`/
`--unseen` toggles a single job. `seen` survives re-discovery, so a repeat `search.py` won't
re-flag an already-seen job as new.

## Scoring uses the operator's own model

`score.py` / `review.py` / `tailor.py` / `cover_letter.py` / `interview_prep.py` call **sevn's
configured tier-B model** through the egress proxy — no separate provider keys. `score.py` grades
each job on match, keyword coverage, tailoring tips, dealbreakers, and a posting-legitimacy
(ghost-job) signal. If the proxy is not reachable from the skill subprocess, the script returns a
`needs_agent_*` payload (`needs_agent_scoring` / `needs_agent_review` / `needs_agent_tailoring` /
`needs_agent_cover_letter` / `needs_agent_interview_prep`) containing a compact bundle so the
invoking tier-B agent can finish in its own turn.

## Browser boards & challenges

`startupjobs`, `gradcracker`, `ukvisajobs`, `remoteco`, and `jobnet` navigate via sevn's **own CDP
browser engine**. If a board serves a Cloudflare/anti-bot wall (or, for `jobnet`, the STAR
identity-server login), the extractor returns `challenge_required` with the URL — solve/sign in
once in a headed operator browser session, then re-run `search.py`.

## ToS / automation

Scraping job boards is the **operator's responsibility** (site ToS, rate limits, anti-bot policy).
Each board is queried through its public API or public pages; respect the individual sites' terms.
