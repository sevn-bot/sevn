import { QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import type { FleetBrief } from "../../client/connection.ts";
import { createQueryClient, useCall } from "../../client/hooks.ts";
import { agentPath, go } from "../routes.ts";
import { formatUsd, KpiStrip } from "./KpiStrip.tsx";
import { MetricTiles } from "./MetricTiles.tsx";
import { age, clock } from "./time.ts";

/** The 60-second morning page. Built by the host each time it is opened. */
export function BriefPage() {
  const [client] = useState(() => createQueryClient());
  return (
    <QueryClientProvider client={client}>
      <BriefView />
    </QueryClientProvider>
  );
}

function BriefView() {
  const query = useCall("fleet.brief", {});
  const brief = query.data;
  return (
    <section className="mx-auto max-w-3xl space-y-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-lg font-medium">Daily brief</h1>
        <div className="flex items-baseline gap-3 text-sm text-zinc-400">
          {brief !== undefined ? (
            <p>{`Built ${clock(brief.built_at)}`}</p>
          ) : null}
          <button
            type="button"
            className="underline"
            onClick={() => {
              void query.refetch();
            }}
          >
            Rebuild
          </button>
          <button
            type="button"
            className="underline"
            onClick={() => {
              go("/");
            }}
          >
            Dashboard
          </button>
        </div>
      </div>
      {brief === undefined ? (
        <p className="text-sm text-zinc-400">
          {query.isError ? "The brief is unavailable" : "Building…"}
        </p>
      ) : (
        <BriefBody brief={brief} />
      )}
    </section>
  );
}

function Block({
  title,
  testId,
  children,
}: {
  title: string;
  testId: string;
  children: React.ReactNode;
}) {
  return (
    <section data-testid={testId} className="space-y-1">
      <h2 className="font-medium">{title}</h2>
      {children}
    </section>
  );
}

function BriefBody({ brief }: { brief: FleetBrief }) {
  return (
    <>
      <KpiStrip kpis={brief.kpis} />
      <Block title="Broken" testId="brief-broken">
        {brief.broken.length === 0 ? (
          <p className="text-sm text-zinc-400">Nothing is broken</p>
        ) : (
          <ul className="list-disc space-y-0.5 pl-5 text-sm text-red-300">
            {brief.broken.map((issue) => (
              <li key={`${issue.kind}:${issue.text}`}>{issue.text}</li>
            ))}
          </ul>
        )}
      </Block>
      <Block title="Needs you" testId="brief-decisions">
        {brief.decisions.length === 0 ? (
          <p className="text-sm text-zinc-400">Nothing needs you</p>
        ) : (
          <>
            <ul className="space-y-1 text-sm">
              {brief.decisions.map((item) => (
                <li key={item.id}>
                  <button
                    type="button"
                    className="text-left"
                    onClick={() => {
                      go(agentPath(item.bot_id, item.agent_id));
                    }}
                  >
                    <span className="text-zinc-400">{`${item.bot_name}: `}</span>
                    {item.text}
                  </button>
                </li>
              ))}
            </ul>
            <p className="text-xs text-zinc-500">
              {`Showing ${brief.decisions.length} of ${brief.decisions_total}`}
            </p>
          </>
        )}
      </Block>
      <Block title="Last 24 hours" testId="brief-finished">
        <p className="text-sm">
          {`${brief.finished_done} done`}
          {brief.finished_failed > 0 ? (
            <span className="text-red-400">{` · ${brief.finished_failed} failed`}</span>
          ) : null}
        </p>
        <ul className="space-y-0.5 text-sm text-zinc-300">
          {brief.finished_top.map((item) => (
            <li key={item.turn_id}>
              <span className="text-zinc-400">{`${item.bot_name}: `}</span>
              {item.preview}
            </li>
          ))}
        </ul>
      </Block>
      <Block title="Today" testId="brief-today">
        {brief.routines_today.length === 0 ? (
          <p className="text-sm text-zinc-400">
            No routines in the next 24 hours
          </p>
        ) : (
          <>
            <ul className="space-y-0.5 text-sm">
              {brief.routines_today.map((item) => (
                <li key={item.id}>
                  {item.name}
                  <span className="text-zinc-400">
                    {` · ${item.bot_name} · ${item.runs} ${item.runs === 1 ? "run" : "runs"}`}
                    {item.next_run !== null
                      ? ` · next in ${age(brief.built_at, item.next_run)}`
                      : ""}
                  </span>
                </li>
              ))}
            </ul>
            <p className="text-xs text-zinc-500">
              {`About ${formatUsd(brief.routines_today_usd)} in the next 24 hours`}
              {brief.routines_today_unpriced > 0
                ? `, ${brief.routines_today_unpriced} unpriced`
                : ""}
            </p>
          </>
        )}
      </Block>
      <Block title="Metrics" testId="brief-metrics">
        {brief.metric_changes.length === 0 ? (
          <p className="text-sm text-zinc-400">No changes</p>
        ) : (
          <MetricTiles metrics={brief.metric_changes} />
        )}
      </Block>
    </>
  );
}
