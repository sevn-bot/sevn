import type { MetricStatus } from "../../client/connection.ts";
import { formatCount } from "./KpiStrip.tsx";
import { clock } from "./time.ts";

export type MetricTile = {
  key: string;
  label: string;
  value: number | null;
  unit: string;
  source: string;
  as_of: string;
  status: MetricStatus;
  delta_24h: number | null;
  reports?: { bot_name: string; value: number | null }[];
};

const exact = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });

/** Compact from 1,000 up; below that, up to two decimals so 48.2% stays 48.2. */
export function formatMetric(value: number): string {
  return Math.abs(value) >= 1000 ? formatCount(value) : exact.format(value);
}

export function formatDelta(delta: number): string {
  return `${delta > 0 ? "+" : ""}${formatMetric(delta)} in 24h`;
}

const border: Record<MetricStatus, string> = {
  ok: "border-zinc-800",
  stale: "border-amber-700",
  error: "border-red-800",
  conflict: "border-amber-600",
};

/** Bot-reported metrics: value, change, time, and the source on hover. */
export function MetricTiles({ metrics }: { metrics: MetricTile[] }) {
  if (metrics.length === 0) {
    return null;
  }
  return (
    <ul className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      {metrics.map((metric) => (
        <li
          key={metric.key}
          data-testid={`metric-${metric.key}`}
          data-status={metric.status}
          title={`${metric.value === null ? "unavailable" : exact.format(metric.value)} ${metric.unit} · ${metric.source} · as of ${metric.as_of}`}
          className={`rounded border px-3 py-2 ${border[metric.status]}`}
        >
          <p className="text-xs text-zinc-400">{metric.label}</p>
          <p
            className={`text-lg font-medium tabular-nums ${metric.value === null ? "text-zinc-500" : ""}`}
          >
            {metric.value === null ? "unavailable" : formatMetric(metric.value)}
            {metric.value !== null && metric.unit !== "" ? (
              <span className="ml-1 text-xs font-normal text-zinc-400">
                {metric.unit}
              </span>
            ) : null}
          </p>
          <p className="text-xs text-zinc-500">
            {metric.delta_24h !== null ? (
              <span
                className={`mr-2 ${metric.delta_24h < 0 ? "text-red-400" : "text-emerald-400"}`}
              >
                {formatDelta(metric.delta_24h)}
              </span>
            ) : null}
            <span>{`as of ${clock(metric.as_of)}`}</span>
            {metric.status === "stale" ? (
              <span className="ml-2 text-amber-400">stale</span>
            ) : null}
          </p>
          {metric.status === "conflict" ? (
            <p className="text-xs text-amber-400">
              {"bots disagree: "}
              {(metric.reports ?? [])
                .map(
                  (report) =>
                    `${report.bot_name} ${report.value === null ? "unavailable" : exact.format(report.value)}`,
                )
                .join(" · ")}
            </p>
          ) : null}
        </li>
      ))}
    </ul>
  );
}
