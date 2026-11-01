import { useState } from "react";
import type { FleetBot, FleetDay } from "../../client/connection.ts";
import { formatUsd } from "./KpiStrip.tsx";

type View = "turns" | "cost";

function costShade(cost: number): string {
  if (cost <= 0) {
    return "bg-zinc-900";
  }
  if (cost < 0.1) {
    return "bg-sky-900";
  }
  if (cost < 1) {
    return "bg-sky-700";
  }
  if (cost < 5) {
    return "bg-sky-500";
  }
  return "bg-sky-300";
}

function costLabel(row: FleetDay | undefined): string {
  if (row === undefined) {
    return "$0.00";
  }
  const money = formatUsd(row.cost_usd);
  return row.unpriced > 0 ? `${money}, ${row.unpriced} unpriced` : money;
}

function shade(turns: number): string {
  if (turns <= 0) {
    return "bg-zinc-900";
  }
  if (turns === 1) {
    return "bg-emerald-900";
  }
  if (turns <= 3) {
    return "bg-emerald-700";
  }
  if (turns <= 7) {
    return "bg-emerald-500";
  }
  return "bg-emerald-300";
}

function turnsLabel(turns: number): string {
  return turns === 1 ? "1 turn" : `${turns} turns`;
}

export function ActivityGrid({
  bots,
  days,
  activity,
  onPick,
}: {
  bots: FleetBot[];
  days: string[];
  activity: FleetDay[];
  onPick: (botId: string) => void;
}) {
  const [view, setView] = useState<View>("turns");
  const rows = new Map<string, FleetDay>();
  const active = new Set<string>();
  for (const row of activity) {
    rows.set(`${row.bot_id}|${row.day}`, row);
    if (row.turns > 0) {
      active.add(row.bot_id);
    }
  }
  return (
    <section aria-labelledby="fleet-activity" className="space-y-2">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="fleet-activity" className="font-medium">
          {`Activity, last ${days.length} days`}
        </h2>
        <div className="flex gap-1">
          {(["turns", "cost"] as const).map((option) => (
            <button
              key={option}
              type="button"
              aria-pressed={view === option}
              className={`rounded-full border px-2 py-0.5 text-xs ${view === option ? "border-zinc-100 bg-zinc-100 text-zinc-950" : "border-zinc-700 text-zinc-300"}`}
              onClick={() => {
                setView(option);
              }}
            >
              {option === "turns" ? "Turns" : "Cost"}
            </button>
          ))}
        </div>
      </div>
      {bots.length === 0 ? (
        <p className="text-sm text-zinc-400">No bots yet</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="border-separate border-spacing-1 text-xs">
            <thead>
              <tr>
                <th className="sr-only" scope="col">
                  Bot
                </th>
                {days.map((day) => (
                  <th
                    key={day}
                    scope="col"
                    className="w-4 font-normal text-zinc-500"
                  >
                    {day.slice(8)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {bots.map((bot) => {
                const idle = !active.has(bot.id);
                return (
                  <tr
                    key={bot.id}
                    data-bot={bot.id}
                    data-idle={idle ? "true" : "false"}
                  >
                    <th scope="row" className="pr-2 text-left font-normal">
                      <button
                        type="button"
                        className="whitespace-nowrap text-zinc-200"
                        onClick={() => {
                          onPick(bot.id);
                        }}
                      >
                        {bot.name}
                      </button>
                      {idle ? (
                        <span className="ml-2 text-zinc-500">idle</span>
                      ) : null}
                    </th>
                    {days.map((day) => {
                      const row = rows.get(`${bot.id}|${day}`);
                      const turns = row?.turns ?? 0;
                      const cost = row?.cost_usd ?? 0;
                      return (
                        <td
                          key={day}
                          title={
                            view === "turns"
                              ? `${bot.name} ${day}: ${turnsLabel(turns)}`
                              : `${bot.name} ${day}: ${costLabel(row)}`
                          }
                          data-turns={turns}
                          data-cost={cost}
                          className={`h-4 w-4 rounded-sm ${view === "turns" ? shade(turns) : costShade(cost)}`}
                        />
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
