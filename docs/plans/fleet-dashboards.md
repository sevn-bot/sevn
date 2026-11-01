# Plan: fleet dashboards

Status: phase 1 in review (PR #11), phase 2 in review. Integration branch: `wave/fleet-dashboards`, cut from `wave/0020-bot-core` (PR #9). Every PR for this plan targets `wave/fleet-dashboards`, not `test` or `main`.

Source: the "Agent Fleet Dashboards" playbook, which restates ideas from Alex Finn's video on running a fleet of about 20 agents. This plan maps those ideas onto sevn.

## Goal

One page shows the owner what needs them, what the bots finished, what is about to run, and what it costs. Bots do not ping. The page stays current while it is open.

## Words

The playbook and sevn use some words differently.

| Playbook | sevn |
|---|---|
| agent | bot |
| task, conversation | agent (one lane and its thread) |
| scheduled job | routine (`routine.run` is reserved) |
| decision | pending request (`approval` or `question`) |
| coordinator | one bot marked as coordinator (phase 5) |

A sevn job is one queued message. It is not a scheduled job.

## Principles

- The host already runs every turn, so bots do not emit their own events. Dashboards read the host tables.
- The `events` outbox is pruned. It is the live signal, not history. Dashboards query `turns`, `jobs`, `agents` and `pending_requests`.
- Every panel shows the time it was read. A value the host cannot read is shown as unavailable, never guessed.
- Cost is shown only when it is known. A turn on a subscription login is shown as subscription, not as dollars.
- Write actions (answer, pause, cancel) use the existing owner scope and `op_id`.

## Phase 1: main dashboard from existing data

No new tables.

Host:

- `fleet.overview`, read-only, in `api/fleet.py` with `domain/fleet.py`. It returns:
  - `as_of`
  - `bots`: each bot's id, name, title, avatar, paused flag, and a status from its agents (`running` beats `waiting` beats `idle`; otherwise `quiet`), with counts of open agents and waiting requests.
  - `waiting`: every pending request with status `waiting`, oldest first, with bot and agent names, kind, the question or tool name, and age.
  - `finished`: the last 20 turns that ended `done`, `failed` or `cancelled`, newest first, with bot, agent title, first line of the reply, and finish time.
  - `activity`: turns finished per bot per UTC day for the last 14 days.

Web:

- The dashboard is the page at `/`. The bot list moves below it.
- Header: one avatar per bot. It is lit when the bot has a running agent and marked when it is waiting on the owner. A toggle hides the header and the choice is kept in local storage.
- "Waiting on you": approval cards answer in place. Question cards open the agent's thread. Requests older than 24 hours are highlighted. The empty state is "Nothing needs you right now".
- "Recently finished": failed and cancelled turns are marked. One click filters by bot.
- Activity: bots by days, shaded by turns finished. Bots with no turns in the window are marked idle.
- "Updated HH:MM" from `as_of`.
- Live: `pending.created`, `pending.resolved`, `turn.finished`, `turn.waiting`, `agent.updated` and `bot.updated` refresh the overview.
- `/bots/:bot/agents/:agent` opens the bot chat on that agent, so every card can link to its thread.

Done when:

- Every waiting request on the host is listed. Answering an approval removes its card on the next refresh.
- A failed turn appears in "Recently finished" and is marked.
- The heat map covers 14 days and counts match the `turns` table.
- Host tests cover ordering, limits, the 14-day window and bot status. Web tests cover the empty state, the stale highlight and the filter.

## Phase 2: usage and cost

- One usage shape for both runtimes (`runtime/usage.py`): `requests`, `tool_calls`, `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens`, `cost_usd` (or null), `cost_source` and `estimated_usd`.
- `cost_source` is `price_table`, `local`, `subscription` or `unknown`.
- Pydantic AI: each model response is priced on its own usage with `genai-prices`, because some prices are tiered by request size. A model with no price makes the turn `unknown`, with `cost_usd` null, never a partial sum. Ollama is `local` at 0.
- Claude: a turn on the user's own login is `subscription` with `cost_usd` null. The SDK's `total_cost_usd` is kept as `estimated_usd`.
- A resumed or auto-approved turn adds up the usage of each of its runs.
- KPI strip: spend today (priced turns only, with unpriced and subscription counts beside it), tokens today, waiting requests, running turns against `runtime.max_running_turns`. Each tile names its source. A missing value reads unavailable.
- The heat map can switch to cost.
- Not done yet: router spend. `decision_log` has no usage or bot id, so jev, the LLM step and the Claude CLI step are not counted. The spend tile says so. This needs a column on `decision_log` and usage from each decider.
- No migration: the usage shape lives in the existing `turns.usage` JSON column.

## Phase 3: questions with options

- `user.ask` (from bot core) takes optional `options`, `priority`, `due_by` and `blocking`.
- `pending.answer` accepts an `option_id` or text for a question. Approvals keep `approve` and `deny`.
- Cards sort by blocking, then priority, then age.
- A question closes as expired when its turn is cancelled, as approvals do now.
- No migration: `options`, `priority`, `due_by` and `blocking` live in the existing `pending_requests.payload` JSON column, and the answer in `pending_requests.answer`.

## Phase 4: routines on the dashboard

**Depends on plan 0050 (routines, webhooks, notifications), which builds routines.** This phase builds no routine model, scheduler or migration of its own. The spec text is §5 (Routines), Appendix A.1 (`Routine`, `RoutineRun`, `Budget`) and Appendix A.7, which spec 0001 draft 6 extends with useful runs and budgets. §7 only defines the `routine.silent` decision point.

Owned by 0050, in its migration `0006_routines.py`. This phase does not create them:

- `routines`: cron, interval, once and webhook triggers, `tz`, `next_run_at`, `missed_policy` (`run_once` | `skip`), `continue_agent_id`.
- `routine_runs`: `job_id`, `agent_id`, `scheduled_for`, `status`, `silent`.
- The scheduler and missed-run handling (0050 D3–D4), and `routine.run` / `routine.failed`.
- Silent runs: `routine.no_update`, or jev `routine.silent` (0050 D5).
- Notifications through `notify.priority` (0050 D7).

Fields that spec draft 6 adds, also in 0050's `0006_routines.py`:

- `routines.last_run_at`, `routines.last_useful_at`, and `routines.paused_reason` (`user` | `budget` | null).
- `routine_runs.useful`, which is `status = done` and not `silent`, and `routine_runs.cost_usd`, which is the sum of the run's `turns.usage.cost_usd` and is null when any of them is unknown.
- The `budgets` table: `scope` (`host` | `bot`), `bot_id`, `period` (`day` | `month`), `limit_usd`, `warn_at` (default 0.8).

If 0050 merges before draft 6 is applied to it, these fields go into a follow-up migration that 0050's owner numbers under K-MIG. This plan still owns no migration.

This phase builds:

- `fleet.overview` gains `upcoming`. For each enabled routine: its next run, cost per run (the median `routine_runs.cost_usd` over the last 10 runs, or null), 30-day cost, the last useful run, a "candidate to cancel" flag (enabled 14 days or more with no useful run), and a 7-day projection (cost per run × runs due in 7 days, or null). Each value carries `as_of`, and an unknown value is null, never guessed.
- The dashboard's "Upcoming" column, with Pause and Cancel buttons:
  - **Pause** calls 0050's `routines.update` with `enabled = false, paused_reason = "user"`. **Resume** sets `enabled = true` and clears `paused_reason`.
  - **Cancel** calls 0050's `routines.delete`, after a confirm.
  - Both are owner-only and take an `op_id`. This phase adds no routine methods of its own. 0050 names `routines.create` and the bot tools `routine.update` / `routine.delete`, but not the owner-side update and delete methods. If its `api/routines.py` names them differently, use those names.
- Budgets:
  - `budgets.list` and `budgets.set` (owner only, with `op_id`).
  - Spend is counted from `turns.usage.cost_usd` where `cost_source` is not `subscription` or `unknown`.
  - At 80 percent: a `notify.priority` warning.
  - At 100 percent: the scope's routines pause with `paused_reason = "budget"` (routine runs only). They resume at the next period or when the owner resumes them. User-started work is never blocked; it only shows the breach.
- Notifications follow 0050's `notify.priority`. This phase adds three triggers: a blocking question near its `due_by`, a failed run that needs action (`routine.failed`), and a budget warning or breach.

Done when:

- "Upcoming" lists every enabled routine from 0050's tables, and Pause / Cancel act through 0050's methods.
- A routine with 14 days of silent runs is flagged as a candidate to cancel.
- Crossing 100 percent of a bot budget pauses that bot's routines with `paused_reason = "budget"`, and user messages to the bot still run.
- Host tests cover the cost-per-run median, the null rules for unknown cost, the 14-day flag and the budget pause. They run against fixture rows in 0050's tables.

## Phase 5: coordinator

Depends on bot-to-bot delegation (`route.owner`, `delegate.needed`) and A2UI (plan 0040).

- One bot is the coordinator.
- A command bar on the dashboard sends `messages.send` to it. Read-only sessions do not see it.
- The coordinator adds panels as A2UI surfaces (`ui.surface`). Each definition is versioned so a change can be undone. A dashboard index lists them with a pin flag.
- Proposal: the coordinator asks each bot what it owns, what it waits on the owner for, which numbers matter, which routines could stop, and what must never be shared. It proposes up to five dashboards and builds none until the owner picks.

## Phase 6: optional

- `report_metric` tool and a `metrics` table with `source`, `as_of`, status and a freshness budget.
- Host panel: Ollama reachable, models loaded, queue depth.
- A morning brief as a routine whose output is a surface.
- Read-only share links on the existing `read_only` scope.

## Open questions

- ~~Is there a spec text for routines that phase 4 must match?~~ Yes: spec §5, Appendix A.1 and A.7, and plan 0050. Phase 4 builds on them (see above).
- Should subscription turns show tokens only, or an estimate labelled as one?
- Should coordinator panels wait for plan 0040, or start as a fixed set the coordinator can switch on and off?
