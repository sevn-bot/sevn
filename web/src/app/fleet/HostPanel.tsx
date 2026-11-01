import type { FleetHost } from "../../client/connection.ts";
import { clock } from "./time.ts";

function gigabytes(bytes: number): string {
  return `${(bytes / 1_000_000_000).toFixed(1)} GB`;
}

export function HostPanel({ host }: { host: FleetHost }) {
  const { ollama } = host;
  const state = !ollama.configured
    ? "off"
    : ollama.reachable === true
      ? "ok"
      : "down";
  return (
    <section
      aria-labelledby="fleet-host"
      data-testid="host-panel"
      data-ollama={state}
      className="space-y-1 rounded border border-zinc-800 px-3 py-2 text-sm"
    >
      <h2 id="fleet-host" className="font-medium">
        Host
      </h2>
      <p className="text-zinc-400">
        {`${host.queued_jobs} queued · ${host.running_turns} / ${host.max_running_turns} running · sevn ${host.version}`}
      </p>
      {state === "off" ? (
        <p className="text-zinc-500">Ollama not set up</p>
      ) : state === "down" ? (
        <p className="text-red-400">{`Ollama ${ollama.error ?? "unreachable"}`}</p>
      ) : (
        <>
          <p>
            <span className="text-emerald-400">Ollama reachable</span>
            <span className="text-zinc-400">{` · ${ollama.models.length} models`}</span>
          </p>
          {ollama.loaded.length > 0 ? (
            <p className="text-zinc-400">
              {"Loaded: "}
              {ollama.loaded
                .map((model) =>
                  model.vram_bytes === null
                    ? model.name
                    : `${model.name} (${gigabytes(model.vram_bytes)})`,
                )
                .join(", ")}
            </p>
          ) : (
            <p className="text-zinc-500">No model loaded</p>
          )}
        </>
      )}
      <p className="text-xs text-zinc-500">
        {`checked ${clock(ollama.checked_at ?? host.as_of)}`}
      </p>
    </section>
  );
}
