import type { FleetBot, FleetDay } from "../../client/connection.ts";

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
  const counts = new Map<string, number>();
  const active = new Set<string>();
  for (const row of activity) {
    counts.set(`${row.bot_id}|${row.day}`, row.turns);
    if (row.turns > 0) {
      active.add(row.bot_id);
    }
  }
  return (
    <section aria-labelledby="fleet-activity" className="space-y-2">
      <h2 id="fleet-activity" className="font-medium">
        {`Activity, last ${days.length} days`}
      </h2>
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
                      const turns = counts.get(`${bot.id}|${day}`) ?? 0;
                      return (
                        <td
                          key={day}
                          title={`${bot.name} ${day}: ${turnsLabel(turns)}`}
                          data-turns={turns}
                          className={`h-4 w-4 rounded-sm ${shade(turns)}`}
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
