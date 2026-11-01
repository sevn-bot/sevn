import { useState } from "react";
import {
  call,
  type FleetBot,
  type FleetOverview,
  type FleetRoutine,
} from "../../client/connection.ts";
import { formatUsd } from "./KpiStrip.tsx";
import { age } from "./time.ts";

const dayMs = 24 * 60 * 60 * 1000;

function soon(item: FleetRoutine, asOf: string): boolean {
  if (item.status !== "active" || item.next_run === null) {
    return item.status === "paused";
  }
  return Date.parse(item.next_run) - Date.parse(asOf) <= dayMs;
}

export function UpcomingPanel({ overview }: { overview: FleetOverview }) {
  const [all, setAll] = useState(false);
  const items = overview.upcoming;
  const shown = all
    ? items
    : items.filter((item) => soon(item, overview.as_of));
  return (
    <section aria-labelledby="fleet-upcoming" className="space-y-2">
      <h2 id="fleet-upcoming" className="font-medium">
        Upcoming
      </h2>
      {items.length === 0 ? (
        <p className="rounded border border-zinc-800 px-3 py-2 text-sm">
          No routines
        </p>
      ) : (
        <ul className="space-y-1">
          {shown.map((item) => (
            <RoutineRow key={item.id} item={item} asOf={overview.as_of} />
          ))}
        </ul>
      )}
      {!all && shown.length < items.length ? (
        <button
          type="button"
          className="text-sm text-zinc-400 underline"
          onClick={() => {
            setAll(true);
          }}
        >
          {`Show all (${items.length})`}
        </button>
      ) : null}
      {items.length > 0 ? <Projection overview={overview} /> : null}
      <NewRoutine bots={overview.bots} />
    </section>
  );
}

function Projection({ overview }: { overview: FleetOverview }) {
  const unpriced = overview.projection_unpriced;
  return (
    <p data-testid="projection" className="text-sm text-zinc-400">
      {`Next 7 days: about ${formatUsd(overview.projection_7d_usd)}`}
      {unpriced > 0 ? (
        <span className="ml-2 text-amber-400">
          {`${unpriced} ${unpriced === 1 ? "routine" : "routines"} unpriced`}
        </span>
      ) : null}
    </p>
  );
}

function costLine(item: FleetRoutine): string {
  const parts: string[] = [];
  if (item.cost_per_run_usd !== null) {
    parts.push(`${formatUsd(item.cost_per_run_usd)}/run`);
    parts.push(`${formatUsd(item.cost_30d_usd)} in 30 days`);
  } else if (item.runs_30d === 0) {
    parts.push("no runs yet");
  } else {
    parts.push("cost unknown");
  }
  if (item.unpriced_runs_30d > 0) {
    parts.push(`${item.unpriced_runs_30d} unpriced`);
  }
  return parts.join(" · ");
}

function usefulLine(item: FleetRoutine, asOf: string): string {
  if (item.last_useful_at !== null) {
    return `useful ${age(item.last_useful_at, asOf)} ago`;
  }
  return item.runs_30d > 0 ? "nothing useful in 30 days" : "";
}

function whenLine(item: FleetRoutine, asOf: string): string {
  if (item.status === "paused") {
    return item.paused_reason === "budget" ? "paused by budget" : "paused";
  }
  if (item.next_run === null) {
    return "";
  }
  return `next in ${age(asOf, item.next_run)}`;
}

function RoutineRow({ item, asOf }: { item: FleetRoutine; asOf: string }) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const useful = usefulLine(item, asOf);

  async function act(
    method: "routines.pause" | "routines.resume" | "routines.cancel",
  ) {
    setBusy(true);
    setFailed(false);
    try {
      await call(method, { routine_id: item.id });
      setConfirming(false);
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <li
      data-routine={item.id}
      data-status={item.status}
      data-candidate={item.candidate_to_cancel ? "true" : "false"}
      className={`space-y-1 rounded border px-3 py-2 text-sm ${item.candidate_to_cancel ? "border-amber-700" : "border-zinc-800"}`}
    >
      <div className="flex flex-wrap items-baseline gap-x-2">
        <span className="text-zinc-200">{item.name}</span>
        <span className="text-zinc-400">{item.bot_name}</span>
        <span
          className={
            item.status === "paused" ? "text-amber-400" : "text-zinc-400"
          }
        >
          {whenLine(item, asOf)}
        </span>
        {item.candidate_to_cancel ? (
          <span className="text-amber-400">candidate to cancel</span>
        ) : null}
      </div>
      <p className="font-mono text-xs text-zinc-500">
        {`${item.schedule} ${item.timezone}`}
      </p>
      <p className="text-zinc-400">
        {costLine(item)}
        {useful !== "" ? ` · ${useful}` : ""}
      </p>
      <div className="flex flex-wrap gap-2 pt-1">
        {item.status === "paused" ? (
          <button
            type="button"
            disabled={busy}
            className="rounded border border-zinc-700 px-2 py-0.5 text-xs disabled:opacity-40"
            onClick={() => {
              void act("routines.resume");
            }}
          >
            Resume
          </button>
        ) : (
          <button
            type="button"
            disabled={busy}
            className="rounded border border-zinc-700 px-2 py-0.5 text-xs disabled:opacity-40"
            onClick={() => {
              void act("routines.pause");
            }}
          >
            Pause
          </button>
        )}
        {confirming ? (
          <>
            <button
              type="button"
              disabled={busy}
              className="rounded bg-red-700 px-2 py-0.5 text-xs text-white disabled:opacity-40"
              onClick={() => {
                void act("routines.cancel");
              }}
            >
              Yes, cancel
            </button>
            <button
              type="button"
              className="rounded border border-zinc-700 px-2 py-0.5 text-xs"
              onClick={() => {
                setConfirming(false);
              }}
            >
              Keep it
            </button>
          </>
        ) : (
          <button
            type="button"
            className="rounded border border-zinc-700 px-2 py-0.5 text-xs"
            onClick={() => {
              setConfirming(true);
            }}
          >
            Cancel
          </button>
        )}
      </div>
      {failed ? <p className="text-red-400">Could not change it</p> : null}
    </li>
  );
}

function defaultZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

function NewRoutine({ bots }: { bots: FleetBot[] }) {
  const [botId, setBotId] = useState("");
  const [name, setName] = useState("");
  const [schedule, setSchedule] = useState("0 9 * * 1-5");
  const [timezone, setTimezone] = useState(defaultZone);
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const chosen = botId !== "" ? botId : (bots[0]?.id ?? "");

  async function create() {
    setBusy(true);
    setError("");
    try {
      await call("routines.create", {
        bot_id: chosen,
        name,
        schedule,
        timezone,
        text,
      });
      setName("");
      setText("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "could not create");
    } finally {
      setBusy(false);
    }
  }

  if (bots.length === 0) {
    return null;
  }
  const field = "mt-1 block w-full rounded bg-zinc-900 px-2 py-1 text-sm";
  return (
    <details className="rounded border border-zinc-800 px-3 py-2 text-sm">
      <summary>New routine</summary>
      <form
        className="space-y-2 pt-2"
        onSubmit={(event) => {
          event.preventDefault();
          void create();
        }}
      >
        <label className="block">
          Bot
          <select
            className={field}
            value={chosen}
            onChange={(event) => {
              setBotId(event.target.value);
            }}
          >
            {bots.map((bot) => (
              <option key={bot.id} value={bot.id}>
                {bot.name}
              </option>
            ))}
          </select>
        </label>
        <label className="block">
          Name
          <input
            className={field}
            value={name}
            onChange={(event) => {
              setName(event.target.value);
            }}
          />
        </label>
        <label className="block">
          Schedule
          <input
            className={`${field} font-mono`}
            value={schedule}
            onChange={(event) => {
              setSchedule(event.target.value);
            }}
          />
        </label>
        <label className="block">
          Timezone
          <input
            className={field}
            value={timezone}
            onChange={(event) => {
              setTimezone(event.target.value);
            }}
          />
        </label>
        <label className="block">
          Prompt
          <textarea
            className={field}
            rows={3}
            value={text}
            onChange={(event) => {
              setText(event.target.value);
            }}
          />
        </label>
        <p className="text-xs text-zinc-500">
          Five-field cron: minute hour day month weekday.
        </p>
        <button
          type="submit"
          disabled={busy || name.trim() === "" || text.trim() === ""}
          className="rounded bg-zinc-100 px-3 py-1 text-sm font-medium text-zinc-950 disabled:opacity-40"
        >
          Create routine
        </button>
        {error !== "" ? <p className="text-red-400">{error}</p> : null}
      </form>
    </details>
  );
}
