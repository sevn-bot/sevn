import type { FleetWaiting } from "../../client/connection.ts";

export type WaitingHost = {
  host_id: string;
  name: string;
  /** False when the host does not answer: its items are unknown, not empty. */
  available: boolean;
  waiting: FleetWaiting[];
  /** False when this window cannot open the host's agents (default true). */
  openable?: boolean;
};

/** Every host's waiting items in one list, newest first, each labelled with its host. */
export function WaitingList({
  title,
  empty,
  hosts,
  include,
  onOpen,
}: {
  title: string;
  empty: string;
  hosts: WaitingHost[];
  include: (item: FleetWaiting) => boolean;
  onOpen?: (hostId: string, item: FleetWaiting) => void;
}) {
  const rows = hosts
    .flatMap((host) =>
      host.available
        ? host.waiting.filter(include).map((item) => ({ host, item }))
        : [],
    )
    .sort((left, right) =>
      right.item.created_at.localeCompare(left.item.created_at),
    );
  const down = hosts.filter((host) => !host.available);
  return (
    <div className="space-y-2">
      <h2 className="font-medium">{`${title} (${rows.length})`}</h2>
      {down.map((host) => (
        <p key={host.host_id} className="text-sm text-amber-300">
          {`${host.name} unavailable`}
        </p>
      ))}
      {rows.length === 0 ? (
        <p className="text-sm text-zinc-400">{empty}</p>
      ) : (
        <ul className="space-y-2">
          {rows.map(({ host, item }) => (
            <li
              key={`${host.host_id}|${item.id}`}
              className="space-y-0.5 rounded border border-zinc-800 px-3 py-2 text-sm"
            >
              <p className="flex flex-wrap gap-x-2 text-xs text-zinc-400">
                <span className="rounded bg-zinc-800 px-1.5 text-zinc-200">
                  {host.name}
                </span>
                <span>{item.bot_name}</span>
                <span>{item.agent_title}</span>
              </p>
              {onOpen === undefined || host.openable === false ? (
                <p>{item.text}</p>
              ) : (
                <button
                  type="button"
                  className="text-left"
                  onClick={() => {
                    onOpen(host.host_id, item);
                  }}
                >
                  {item.text}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
