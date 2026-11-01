import { useEffect, useState } from "react";
import type { FleetBot, SharedFleet } from "../../client/connection.ts";
import { ActivityGrid } from "./ActivityGrid.tsx";
import { formatUsd, KpiStrip } from "./KpiStrip.tsx";
import { MetricTiles } from "./MetricTiles.tsx";
import { age, clock } from "./time.ts";

const pollMs = 60_000;

type Loaded =
  | { state: "loading" }
  | { state: "invalid" }
  | { state: "error" }
  | { state: "ready"; data: SharedFleet };

/**
 * A read-only view for someone who is not the owner. It fetches a redacted
 * snapshot over plain HTTP and never opens the owner's protocol socket.
 */
export function SharePage({
  shareId,
  secret,
}: {
  shareId: string;
  secret: string;
}) {
  const [loaded, setLoaded] = useState<Loaded>({ state: "loading" });

  useEffect(() => {
    let alive = true;
    const url = `/share/${encodeURIComponent(shareId)}/${encodeURIComponent(secret)}/data`;
    async function load() {
      try {
        const response = await fetch(url, {
          cache: "no-store",
          credentials: "omit",
        });
        if (!alive) {
          return;
        }
        if (response.status === 404) {
          setLoaded({ state: "invalid" });
          return;
        }
        if (!response.ok) {
          setLoaded((current) =>
            current.state === "ready" ? current : { state: "error" },
          );
          return;
        }
        const data = (await response.json()) as SharedFleet;
        if (alive) {
          setLoaded({ state: "ready", data });
        }
      } catch {
        if (alive) {
          setLoaded((current) =>
            current.state === "ready" ? current : { state: "error" },
          );
        }
      }
    }
    void load();
    const timer = window.setInterval(() => {
      void load();
    }, pollMs);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [shareId, secret]);

  return (
    <div className="min-h-screen bg-zinc-950 px-4 py-4 text-zinc-100">
      {loaded.state === "ready" ? (
        <SharedView data={loaded.data} />
      ) : (
        <p className="text-sm text-zinc-400">
          {loaded.state === "invalid"
            ? "This link is not valid or has expired"
            : loaded.state === "error"
              ? "The dashboard is unavailable right now"
              : "Loading…"}
        </p>
      )}
    </div>
  );
}

function SharedView({ data }: { data: SharedFleet }) {
  const bots: FleetBot[] = data.bots.map((bot) => ({
    id: bot.id,
    name: bot.name,
    title: "",
    avatar: "",
    paused: false,
    status: bot.status as FleetBot["status"],
    open_agents: 0,
    waiting: 0,
  }));
  return (
    <section className="mx-auto max-w-5xl space-y-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h1 className="text-lg font-medium">{data.label}</h1>
          <p className="text-sm text-zinc-400">
            {data.scope_bot_name === null
              ? "All bots"
              : `${data.scope_bot_name} only`}
          </p>
        </div>
        <p className="text-sm text-zinc-400">
          {`Read-only · updated ${clock(data.as_of)} · expires in ${age(data.as_of, data.expires_at)}`}
        </p>
      </div>
      <KpiStrip kpis={data.kpis} />
      <MetricTiles metrics={data.metrics} />
      <div className="flex flex-wrap gap-4 text-sm">
        <p>{`${data.waiting} waiting on the owner`}</p>
        <p>{`${data.finished_24h.done} finished in 24 hours`}</p>
        {data.finished_24h.failed > 0 ? (
          <p className="text-red-400">{`${data.finished_24h.failed} failed`}</p>
        ) : null}
      </div>
      <ul className="flex flex-wrap gap-2 text-sm">
        {data.bots.map((bot) => (
          <li key={bot.id} className="rounded border border-zinc-800 px-2 py-1">
            {bot.name}
            <span className="ml-2 text-zinc-400">{bot.status}</span>
          </li>
        ))}
      </ul>
      {data.upcoming.length > 0 ? (
        <section className="space-y-1">
          <h2 className="font-medium">Upcoming</h2>
          <ul className="space-y-1 text-sm">
            {data.upcoming.map((item) => (
              <li
                key={`${item.bot_name}:${item.name}`}
                className="rounded border border-zinc-800 px-3 py-2"
              >
                <span>{item.name}</span>
                <span className="ml-2 text-zinc-400">{item.bot_name}</span>
                <span className="ml-2 text-zinc-400">
                  {item.status === "paused"
                    ? "paused"
                    : item.next_run !== null
                      ? `next in ${age(data.as_of, item.next_run)}`
                      : ""}
                </span>
                {item.cost_per_run_usd !== null ? (
                  <span className="ml-2 text-zinc-400">
                    {`${formatUsd(item.cost_per_run_usd)}/run`}
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
          {data.projection_7d_usd !== null ? (
            <p className="text-sm text-zinc-400">
              {`Next 7 days: about ${formatUsd(data.projection_7d_usd)}`}
            </p>
          ) : null}
        </section>
      ) : null}
      <ActivityGrid
        bots={bots}
        days={data.days}
        activity={data.activity}
        onPick={() => undefined}
      />
    </section>
  );
}
