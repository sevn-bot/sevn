export type SidebarHost = {
  host_id: string;
  name: string;
  reachable: boolean;
  bots: { id: string; name: string }[];
  /** Why the host is not reachable, when known (identity changed, refused URL, …). */
  problem?: string;
  /** Set for paired hosts: forget this host (revokes this device there first). */
  removable?: boolean;
};

/**
 * Bots grouped by host (plan 0055 D9), each host with a reachability dot. Presentational:
 * the caller owns the connections.
 */
export function HostSidebar({
  hosts,
  onPick,
  onForget,
}: {
  hosts: SidebarHost[];
  onPick?: (hostId: string, botId: string) => void;
  onForget?: (hostId: string) => void;
}) {
  return (
    <nav aria-label="Hosts" className="space-y-4">
      {hosts.map((host) => (
        <section
          key={host.host_id}
          aria-label={host.name}
          className="space-y-1"
        >
          <div className="flex items-center gap-2">
            <span
              role="img"
              aria-label={host.reachable ? "reachable" : "unreachable"}
              title={host.reachable ? "reachable" : "unreachable"}
              className={`inline-block h-2 w-2 shrink-0 rounded-full ${host.reachable ? "bg-emerald-400" : "bg-zinc-600"}`}
            />
            <h2 className="truncate text-sm font-medium">{host.name}</h2>
            {host.removable === true && onForget !== undefined ? (
              <button
                type="button"
                className="ml-auto text-xs text-zinc-500 underline"
                onClick={() => {
                  onForget(host.host_id);
                }}
              >
                Forget
              </button>
            ) : null}
          </div>
          {host.problem !== undefined ? (
            <p className="text-xs text-amber-300">{host.problem}</p>
          ) : null}
          {host.bots.length === 0 ? (
            <p className="pl-4 text-xs text-zinc-500">No bots</p>
          ) : (
            <ul className="space-y-0.5 pl-4 text-sm">
              {host.bots.map((bot) => (
                <li key={bot.id}>
                  {onPick === undefined ? (
                    <span>{bot.name}</span>
                  ) : (
                    <button
                      type="button"
                      className="text-left"
                      onClick={() => {
                        onPick(host.host_id, bot.id);
                      }}
                    >
                      {bot.name}
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
      ))}
    </nav>
  );
}
