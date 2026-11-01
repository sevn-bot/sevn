import type { FleetKpi } from "../../client/connection.ts";

export function formatCount(value: number): string {
  const sign = value < 0 ? "-" : "";
  const size = Math.abs(value);
  if (size < 1000) {
    return `${sign}${Math.round(size)}`;
  }
  if (size < 1_000_000) {
    return `${sign}${trim(size / 1000)}k`;
  }
  return `${sign}${trim(size / 1_000_000)}M`;
}

function trim(value: number): string {
  return value >= 100 ? value.toFixed(0) : value.toFixed(1).replace(/\.0$/, "");
}

export function formatUsd(value: number): string {
  if (value > 0 && value < 0.01) {
    return "<$0.01";
  }
  return `$${value.toFixed(2)}`;
}

function shown(kpi: FleetKpi): string {
  if (kpi.value === null) {
    return "unavailable";
  }
  if (kpi.unit === "USD") {
    return formatUsd(kpi.value);
  }
  if (typeof kpi.limit === "number") {
    return `${formatCount(kpi.value)} / ${kpi.limit}`;
  }
  return formatCount(kpi.value);
}

function extras(kpi: FleetKpi): string[] {
  const lines: string[] = [];
  if (typeof kpi.unpriced === "number" && kpi.unpriced > 0) {
    lines.push(`${kpi.unpriced} unpriced`);
  }
  if (typeof kpi.subscription === "number" && kpi.subscription > 0) {
    lines.push(`${kpi.subscription} on subscription`);
  }
  return lines;
}

function levelBorder(level: FleetKpi["level"]): string {
  if (level === "over") {
    return "border-red-700";
  }
  if (level === "warn") {
    return "border-amber-600";
  }
  return "border-zinc-800";
}

export function KpiStrip({ kpis }: { kpis: FleetKpi[] }) {
  if (kpis.length === 0) {
    return null;
  }
  return (
    <ul className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      {kpis.map((kpi) => {
        const notes = extras(kpi);
        const title = [kpi.source, kpi.note].filter((part) => part !== "");
        return (
          <li
            key={kpi.key}
            data-testid={`kpi-${kpi.key}`}
            data-level={kpi.level ?? undefined}
            title={title.join(" · ")}
            className={`rounded border px-3 py-2 ${levelBorder(kpi.level)}`}
          >
            <p className="text-xs text-zinc-400">{kpi.label}</p>
            <p
              className={`text-lg font-medium tabular-nums ${kpi.value === null ? "text-zinc-500" : ""}`}
            >
              {shown(kpi)}
              {kpi.unit === "tokens" && kpi.value !== null ? (
                <span className="ml-1 text-xs font-normal text-zinc-400">
                  tokens
                </span>
              ) : null}
            </p>
            {typeof kpi.budget_usd === "number" ? (
              <p className="text-xs text-zinc-400">
                {`of ${formatUsd(kpi.budget_usd)} a day`}
              </p>
            ) : null}
            {notes.length > 0 ? (
              <p className="text-xs text-amber-400">{notes.join(" · ")}</p>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}
