type LaneRef = {
  id: string;
  title: string;
};

export function MoveDialog({
  agents,
  onMove,
}: {
  agents: readonly LaneRef[];
  onMove: (agentId: string) => void;
}) {
  return (
    <div role="dialog" aria-label="Move to…" className="flex flex-wrap gap-2">
      {agents.map((agent) => {
        const name = agent.title !== "" ? agent.title : agent.id;
        return (
          <button
            key={agent.id}
            type="button"
            className="rounded bg-zinc-100 px-2 py-1 text-sm font-medium text-zinc-950"
            onClick={() => {
              onMove(agent.id);
            }}
          >
            {name}
          </button>
        );
      })}
    </div>
  );
}
