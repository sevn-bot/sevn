import type { MethodResult } from "../../client/connection.ts";

type ListedAgent = MethodResult["agents.list"]["agents"][number];

export type LaneAgent = {
  id: string;
  title: string;
  status: string;
  ahead?: number;
};

export function toLane(agent: ListedAgent): LaneAgent {
  return {
    id: agent.id,
    title: agent.title,
    status: agent.status,
    ahead: readAhead(agent),
  };
}

export function Lanes({ agents }: { agents: readonly LaneAgent[] }) {
  const others = Math.max(agents.length - 1, 0);
  return (
    <div className="space-y-2">
      {agents.map((agent) => (
        <details
          key={agent.id}
          open
          className="rounded border border-zinc-800 px-3 py-2"
        >
          <summary>{agent.title !== "" ? agent.title : agent.id}</summary>
          <p className="text-sm text-zinc-400">{agent.status}</p>
          <p className="text-sm text-zinc-400">{`siblings: ${others}`}</p>
          {typeof agent.ahead === "number" ? (
            <p className="text-sm text-zinc-400">{`queued: ${agent.ahead} ahead`}</p>
          ) : null}
        </details>
      ))}
    </div>
  );
}

function readAhead(agent: ListedAgent): number | undefined {
  const extra: unknown = agent;
  if (typeof extra !== "object" || extra === null || !("ahead" in extra)) {
    return undefined;
  }
  const value: unknown = extra.ahead;
  return typeof value === "number" ? value : undefined;
}
