import {
  keepPreviousData,
  QueryClientProvider,
  useQuery,
} from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import {
  call,
  type FleetBot,
  type FleetFinished,
  type FleetOverview,
  type FleetWaiting,
} from "../../client/connection.ts";
import { createQueryClient, useEvents } from "../../client/hooks.ts";
import { ApprovalCard } from "../approvals/ApprovalCard.tsx";
import { agentPath, go } from "../routes.ts";
import { ActivityGrid } from "./ActivityGrid.tsx";
import { KpiStrip } from "./KpiStrip.tsx";
import { age, clock, olderThan, staleAfterMs, stamp } from "./time.ts";

const refreshKinds = new Set([
  "pending.created",
  "pending.resolved",
  "turn.started",
  "turn.waiting",
  "turn.finished",
  "agent.updated",
  "bot.updated",
  "bot.deleted",
]);

const pollMs = 60_000;
const headerKey = "sevn.fleet.header";

export function Dashboard() {
  const [client] = useState(() => createQueryClient());
  return (
    <QueryClientProvider client={client}>
      <DashboardView />
    </QueryClientProvider>
  );
}

function DashboardView() {
  const [botFilter, setBotFilter] = useState<string | null>(null);
  const params = botFilter === null ? {} : { bot_id: botFilter };
  const query = useQuery({
    queryKey: ["fleet.overview", params],
    queryFn: () => call("fleet.overview", params),
    placeholderData: keepPreviousData,
    refetchInterval: pollMs,
  });
  const events = useEvents();
  const seen = useRef(0);
  const { refetch } = query;

  useEffect(() => {
    if (events.length === seen.current) {
      return;
    }
    const fresh = events.slice(seen.current);
    seen.current = events.length;
    if (fresh.some((event) => refreshKinds.has(event.k))) {
      void refetch();
    }
  }, [events, refetch]);

  const data = query.data;
  const filterGone =
    botFilter !== null &&
    data !== undefined &&
    !data.bots.some((bot) => bot.id === botFilter);

  useEffect(() => {
    // A deleted bot leaves no chip to click; fall back to all bots.
    if (filterGone) {
      setBotFilter(null);
    }
  }, [filterGone]);
  if (data === undefined) {
    return (
      <section className="space-y-2">
        <h1 className="text-lg font-medium">Fleet</h1>
        <p className="text-sm text-zinc-400">
          {query.isError ? "Dashboard unavailable" : "Loading…"}
        </p>
      </section>
    );
  }
  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-lg font-medium">Fleet</h1>
        <p className="text-sm text-zinc-400">
          <span>{`Updated ${clock(data.as_of)}`}</span>
          {query.isError ? (
            <span className="ml-2 text-amber-400">refresh failed</span>
          ) : null}
        </p>
      </div>
      <FleetHeader bots={data.bots} />
      <KpiStrip kpis={data.kpis} />
      <div className="grid gap-4 md:grid-cols-2">
        <WaitingPanel overview={data} />
        <FinishedPanel
          overview={data}
          filter={botFilter}
          onFilter={setBotFilter}
        />
      </div>
      <ActivityGrid
        bots={data.bots}
        days={data.days}
        activity={data.activity}
        onPick={setBotFilter}
      />
    </section>
  );
}

function readHidden(): boolean {
  try {
    return window.localStorage.getItem(headerKey) === "hidden";
  } catch {
    return false;
  }
}

function writeHidden(hidden: boolean): void {
  try {
    if (hidden) {
      window.localStorage.setItem(headerKey, "hidden");
    } else {
      window.localStorage.removeItem(headerKey);
    }
  } catch {
    // The toggle still works for this visit.
  }
}

const statusRing: Record<FleetBot["status"], string> = {
  running: "border-emerald-400 bg-emerald-950 text-emerald-100 animate-pulse",
  waiting: "border-amber-400 bg-amber-950 text-amber-100",
  idle: "border-zinc-500 bg-zinc-900 text-zinc-200",
  quiet: "border-zinc-800 bg-zinc-950 text-zinc-500",
};

function FleetHeader({ bots }: { bots: FleetBot[] }) {
  const [hidden, setHidden] = useState(readHidden);

  function toggle(): void {
    const next = !hidden;
    setHidden(next);
    writeHidden(next);
  }

  return (
    <div className="flex items-start gap-3">
      {hidden ? null : (
        <ul className="flex max-h-24 flex-1 flex-wrap gap-2 overflow-y-auto">
          {bots.map((bot) => (
            <li key={bot.id}>
              <button
                type="button"
                aria-label={`${bot.name}: ${bot.status}`}
                title={botTitle(bot)}
                data-status={bot.status}
                className={`flex h-10 w-10 items-center justify-center rounded-full border-2 text-sm font-medium ${statusRing[bot.status]}`}
                onClick={() => {
                  go(`/bots/${encodeURIComponent(bot.id)}`);
                }}
              >
                {initials(bot)}
              </button>
            </li>
          ))}
        </ul>
      )}
      <button
        type="button"
        className="ml-auto shrink-0 rounded border border-zinc-800 px-2 py-1 text-xs text-zinc-400"
        onClick={toggle}
      >
        {hidden ? "Show header" : "Hide header"}
      </button>
    </div>
  );
}

function initials(bot: FleetBot): string {
  if (bot.avatar !== "") {
    return bot.avatar;
  }
  const name = bot.name.trim();
  return name === "" ? "?" : name.slice(0, 1).toUpperCase();
}

function botTitle(bot: FleetBot): string {
  const parts = [bot.name, bot.status];
  if (bot.open_agents > 0) {
    parts.push(`${bot.open_agents} open`);
  }
  if (bot.waiting > 0) {
    parts.push(`${bot.waiting} waiting on you`);
  }
  if (bot.paused) {
    parts.push("paused");
  }
  return parts.join(" · ");
}

function WaitingPanel({ overview }: { overview: FleetOverview }) {
  const items = overview.waiting;
  return (
    <section aria-labelledby="fleet-waiting" className="space-y-2">
      <h2 id="fleet-waiting" className="font-medium">
        {`Waiting on you (${items.length})`}
      </h2>
      {items.length === 0 ? (
        <div className="rounded border border-zinc-800 px-3 py-2 text-sm">
          <p>Nothing needs you right now</p>
          <p className="text-zinc-500">{`Checked ${clock(overview.as_of)}`}</p>
        </div>
      ) : (
        <ul className="space-y-2">
          {items.map((item) => (
            <WaitingCard key={item.id} item={item} asOf={overview.as_of} />
          ))}
        </ul>
      )}
    </section>
  );
}

function WaitingCard({ item, asOf }: { item: FleetWaiting; asOf: string }) {
  const stale = olderThan(item.created_at, asOf, staleAfterMs);
  return (
    <li
      data-stale={stale ? "true" : "false"}
      className={`space-y-2 rounded border px-3 py-2 ${stale ? "border-amber-600" : "border-zinc-800"}`}
    >
      <div className="flex flex-wrap items-baseline gap-x-2 text-sm text-zinc-400">
        <span className="text-zinc-200">{item.bot_name}</span>
        <span>{laneTitle(item.agent_title)}</span>
        <span className={stale ? "text-amber-400" : ""}>
          {`waiting ${age(item.created_at, asOf)}`}
        </span>
      </div>
      {item.kind === "approval" ? (
        <ApprovalCard
          pendingId={item.id}
          kind={item.kind}
          name={item.name}
          args={item.args}
        />
      ) : (
        <p>{item.text}</p>
      )}
      <OpenButton botId={item.bot_id} agentId={item.agent_id} />
    </li>
  );
}

function OpenButton({ botId, agentId }: { botId: string; agentId: string }) {
  return (
    <button
      type="button"
      data-open=""
      className="rounded border border-zinc-700 px-3 py-1 text-sm"
      onClick={() => {
        go(agentPath(botId, agentId));
      }}
    >
      Open
    </button>
  );
}

const statusLabel: Record<string, string> = {
  failed: "Failed",
  cancelled: "Cancelled",
  interrupted: "Interrupted",
};

function FinishedPanel({
  overview,
  filter,
  onFilter,
}: {
  overview: FleetOverview;
  filter: string | null;
  onFilter: (botId: string | null) => void;
}) {
  const rows = overview.finished;
  return (
    <section aria-labelledby="fleet-finished" className="space-y-2">
      <h2 id="fleet-finished" className="font-medium">
        Recently finished
      </h2>
      <div className="flex flex-wrap gap-1">
        <FilterChip
          label="All"
          name="All bots"
          on={filter === null}
          onClick={() => {
            onFilter(null);
          }}
        />
        {overview.bots.map((bot) => (
          <FilterChip
            key={bot.id}
            label={bot.name}
            name={`Only ${bot.name}`}
            on={filter === bot.id}
            onClick={() => {
              onFilter(bot.id);
            }}
          />
        ))}
      </div>
      {rows.length === 0 ? (
        <p className="rounded border border-zinc-800 px-3 py-2 text-sm">
          No finished turns yet
        </p>
      ) : (
        <ul className="space-y-1">
          {rows.map((row) => (
            <FinishedRow key={row.turn_id} row={row} asOf={overview.as_of} />
          ))}
        </ul>
      )}
    </section>
  );
}

function FilterChip({
  label,
  name,
  on,
  onClick,
}: {
  label: string;
  name: string;
  on: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-label={name}
      aria-pressed={on}
      className={`rounded-full border px-2 py-0.5 text-xs ${on ? "border-zinc-100 bg-zinc-100 text-zinc-950" : "border-zinc-700 text-zinc-300"}`}
      onClick={onClick}
    >
      {label}
    </button>
  );
}

function FinishedRow({ row, asOf }: { row: FleetFinished; asOf: string }) {
  const label = statusLabel[row.status];
  return (
    <li
      data-status={row.status}
      className={`rounded border px-3 py-2 text-sm ${row.status === "failed" ? "border-red-800" : "border-zinc-800"}`}
    >
      <button
        type="button"
        className="block w-full space-y-0.5 text-left"
        onClick={() => {
          go(agentPath(row.bot_id, row.agent_id));
        }}
      >
        <span className="flex flex-wrap items-baseline gap-x-2 text-zinc-400">
          <span className="text-zinc-200">{row.bot_name}</span>
          <span>{laneTitle(row.agent_title)}</span>
          <span>{stamp(row.finished_at, asOf)}</span>
          {label === undefined ? null : (
            <span
              className={
                row.status === "failed" ? "text-red-400" : "text-zinc-500"
              }
            >
              {label}
            </span>
          )}
        </span>
        {row.preview === "" ? null : (
          <span className="block truncate">{row.preview}</span>
        )}
      </button>
    </li>
  );
}

function laneTitle(title: string): string {
  return title === "" ? "Untitled task" : title;
}
