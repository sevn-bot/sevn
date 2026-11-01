# Plan: fleet dashboards

Status: phase 1 in review (PR #11), phase 2 in review (PR #12), phase 3 in review (PR #14), phase 4 in review. Integration branch: `wave/fleet-dashboards`, cut from `wave/0020-bot-core` (PR #9). Every PR for this plan targets `wave/fleet-dashboards`, not `test` or `main`.

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

## Phase 3: questions with options

- `user.ask` takes optional `options` (up to six, ids `opt_1` on), `priority` (low, normal, high), `due_by` (ISO 8601 with a timezone) and `blocking` (default true). A bad value goes back to the model as `invalid_params`.
- `pending.answer` takes `option_id` or `text` for a question. An approval keeps `approve` and `deny`. A mismatch is `invalid_params`.
- Answering from a card closes the question like a chat answer and queues the answer on the same lane as the user's next message, with an answer chip. It does not go through routing.
- Cards sort by blocking, then priority, then age. An approval is blocking and normal priority.
- Cards show priority, due time or overdue, and not blocking.
- Cancelling a turn expires its open questions (`{"expired": true}`).

## Phase 4: routines

Built from this plan; spec §7 was not available.

- Migration `0004_routines`: `routines` (bot, name, five-field cron `schedule`, IANA `timezone`, prompt `text`, `status`, `paused_reason`, `next_run`, `last_run`) and `jobs.routine_id` and `jobs.silent`. Last outcome, last useful run and costs are read from jobs and turns, not stored.
- `domain/cron.py` evaluates the schedule on the routine's wall clock: a time daylight saving skips does not run, a repeated time runs once.
- `routines.list`, `create`, `update`, `pause`, `resume`, `cancel`. Writes are owner only, with `op_id`, and emit `routine.updated`.
- `sevn serve` checks every 30 seconds. A due routine runs on a new lane named after it, with `origin="routine"`, and emits `routine.run`. After downtime it runs once. A paused bot skips the slot. Resume starts from the next slot.
- A run is useful unless it calls the `routine.silent` tool. The prompt reminds the bot of that tool.
- Budgets: `budgets.daily_usd_per_bot` and `budgets.daily_usd_host` (USD, priced turns since 00:00 UTC). At the cap, routines pause with `paused_reason="budget"`. The spend tile shows the host budget and turns amber at 80 percent, red at 100.
- Dashboard column "Upcoming": next run, cost per run and over 30 days, last useful run, "candidate to cancel" after 14 days with nothing useful, the next 7 days' projected cost (routines with no known cost are counted apart), Pause, Resume, Cancel with a confirm, and a New routine form.
- Not done: notifications (`notify.priority`); sevn has no notification channel yet. Bots cannot create routines themselves yet. A per-bot budget warning at 80 percent is not shown yet; only the host budget level is.

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

- Is there a spec text for routines that phase 4 must match?
- Should subscription turns show tokens only, or an estimate labelled as one?
- Should coordinator panels wait for plan 0040, or start as a fixed set the coordinator can switch on and off?
