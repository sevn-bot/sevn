/**
 * The app's view of many hosts (plan 0055 D6, D9): the host that serves this page (its
 * same-origin session needs no pairing) plus one direct connection per paired profile.
 * Each host's bots and waiting items are fetched from that host and kept apart, labelled
 * with the host they came from.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import {
  call,
  type FleetWaiting,
  type HostClient,
  type MethodResult,
  onEvent,
  type ProtocolEvent,
  type Status,
} from "../../client/connection.ts";
import {
  createHosts,
  type HostStatus,
  type Hosts,
} from "../../client/hosts.ts";
import {
  deleteProfile,
  type HostProfile,
  memoryProfileStore,
  openProfileStore,
  type ProfileStore,
} from "../../client/profiles.ts";

export type HostView = {
  host_id: string;
  name: string;
  /** True for the host that serves this page. */
  local: boolean;
  reachable: boolean;
  /** Fleet data answered (false while unreachable or when `fleet.overview` failed). */
  available: boolean;
  bots: { id: string; name: string }[];
  waiting: FleetWaiting[];
  problem?: string;
};

type HostData = {
  bots: { id: string; name: string }[];
  waiting: FleetWaiting[];
  fleetOk: boolean;
};

const REFRESH_KINDS = new Set([
  "pending.created",
  "pending.resolved",
  "turn.waiting",
  "turn.finished",
  "bot.updated",
  "bot.deleted",
]);
const POLL_MS = 30_000;

let shared: ProfileStore | null = null;

/** The browser's profile store: IndexedDB when the browser has it, else memory. */
export function profileStore(): ProfileStore {
  if (shared === null) {
    shared =
      typeof indexedDB === "undefined"
        ? memoryProfileStore()
        : openProfileStore(indexedDB);
  }
  return shared;
}

/** Whether two WebSocket URLs have the same origin (a malformed URL matches nothing). */
export function sameOrigin(left: string, right: string): boolean {
  try {
    return new URL(left).origin === new URL(right).origin;
  } catch {
    return false;
  }
}

export type MultiHost = {
  /** Paired profiles other than the serving host. */
  remotes: HostProfile[];
  views: HostView[];
  forget: (hostId: string) => Promise<void>;
  /** A paired host's client, once its connection has been up at least once; else null. */
  client: (hostId: string) => HostClient | null;
};

/**
 * @param local the serving host's id (empty until `system.info` answers), status and URL.
 * @param version bump to reload profiles (after a pairing).
 */
export function useMultiHost(
  local: { hostId: string; status: Status; url: string },
  version: number,
  reload: () => void,
): MultiHost {
  const [profiles, setProfiles] = useState<HostProfile[]>([]);
  const [statuses, setStatuses] = useState<Record<string, HostStatus>>({});
  const [data, setData] = useState<Record<string, HostData>>({});
  const hostsRef = useRef<Hosts | null>(null);
  const [hosts, setHosts] = useState<Hosts | null>(null);
  const [opened, setOpened] = useState<ReadonlySet<string>>(new Set());

  // biome-ignore lint/correctness/useExhaustiveDependencies: version is the reload signal.
  useEffect(() => {
    let alive = true;
    profileStore()
      .list()
      .then(
        (list) => {
          if (alive) {
            setProfiles(list);
          }
        },
        () => undefined,
      );
    return () => {
      alive = false;
    };
  }, [version]);

  // The serving host's own profile (same origin) is used by the page's own connection.
  const remotes = profiles.filter(
    (profile) =>
      profile.host_id !== local.hostId &&
      !sameOrigin(profile.direct_url, local.url),
  );
  const remoteKey = remotes
    .map((profile) => `${profile.host_id}|${profile.device_id}`)
    .join(",");

  // biome-ignore lint/correctness/useExhaustiveDependencies: remoteKey stands for remotes.
  useEffect(() => {
    if (remotes.length === 0) {
      return;
    }
    let alive = true;
    const hosts = createHosts({ profiles: remotes });
    hostsRef.current = hosts;
    setHosts(hosts);
    setOpened(new Set());
    const refresh = (hostId: string): void => {
      void fetchHost(
        () => hosts.call(hostId, "bots.list", {}),
        () => hosts.call(hostId, "fleet.overview", {}),
      ).then((next) => {
        if (alive) {
          setData((current) => ({ ...current, [hostId]: next }));
        }
      });
    };
    const offStatus = hosts.onStatus((hostId, next) => {
      if (!alive) {
        return;
      }
      setStatuses((current) => ({ ...current, [hostId]: next }));
      if (next === "connected") {
        setOpened((current) =>
          current.has(hostId) ? current : new Set([...current, hostId]),
        );
        refresh(hostId);
      }
    });
    const offEvent = hosts.onEvent((hostId, event) => {
      if (REFRESH_KINDS.has(event.k)) {
        refresh(hostId);
      }
    });
    const timer = setInterval(() => {
      for (const profile of remotes) {
        if (hosts.status(profile.host_id) === "connected") {
          refresh(profile.host_id);
        }
      }
    }, POLL_MS);
    hosts.start();
    return () => {
      alive = false;
      clearInterval(timer);
      offStatus();
      offEvent();
      hosts.stop();
      if (hostsRef.current === hosts) {
        hostsRef.current = null;
      }
      setHosts((current) => (current === hosts ? null : current));
    };
  }, [remoteKey]);

  const localId = local.hostId;
  const localConnected = local.status === "connected";
  const multi = remotes.length > 0;
  useEffect(() => {
    if (!multi || !localConnected || localId === "") {
      return;
    }
    let alive = true;
    const refresh = (): void => {
      void fetchHost(
        () => call("bots.list", {}),
        () => call("fleet.overview", {}),
      ).then((next) => {
        if (alive) {
          setData((current) => ({ ...current, [localId]: next }));
        }
      });
    };
    refresh();
    const off = onEvent((event: ProtocolEvent) => {
      if (REFRESH_KINDS.has(event.k)) {
        refresh();
      }
    });
    const timer = setInterval(refresh, POLL_MS);
    return () => {
      alive = false;
      off();
      clearInterval(timer);
    };
  }, [multi, localConnected, localId]);

  const forget = useCallback(
    async (hostId: string): Promise<void> => {
      await deleteProfile(profileStore(), hostId, {
        revoke: async (profile) => {
          const hosts = hostsRef.current;
          if (hosts === null) {
            throw new Error("not connected");
          }
          await hosts.call(hostId, "devices.revoke", {
            id: profile.device_id,
          });
        },
      });
      reload();
    },
    [reload],
  );

  const views: HostView[] = [];
  if (multi) {
    const own = data[localId];
    views.push({
      host_id: localId === "" ? "local" : localId,
      name: "This host",
      local: true,
      reachable: localConnected,
      available: localConnected && own?.fleetOk !== false,
      bots: own?.bots ?? [],
      waiting: own?.waiting ?? [],
    });
    for (const profile of remotes) {
      const status = statuses[profile.host_id] ?? "idle";
      const reachable = status === "connected";
      const known = data[profile.host_id];
      const view: HostView = {
        host_id: profile.host_id,
        name: profile.name,
        local: false,
        reachable,
        available: reachable && known?.fleetOk !== false,
        bots: known?.bots ?? [],
        waiting: known?.waiting ?? [],
      };
      const problem = problemText(
        status,
        hostsRef.current?.error(profile.host_id),
      );
      if (problem !== undefined) {
        view.problem = problem;
      }
      views.push(view);
    }
  }
  const client = useCallback(
    (hostId: string): HostClient | null =>
      hosts !== null && opened.has(hostId) ? hosts.client(hostId) : null,
    [hosts, opened],
  );

  return { remotes, views, forget, client };
}

async function fetchHost(
  listBots: () => Promise<MethodResult["bots.list"]>,
  overview: () => Promise<{ waiting: FleetWaiting[] }>,
): Promise<HostData> {
  const [bots, fleet] = await Promise.allSettled([listBots(), overview()]);
  return {
    bots:
      bots.status === "fulfilled"
        ? bots.value.bots.map((bot) => ({ id: bot.id, name: bot.name }))
        : [],
    waiting: fleet.status === "fulfilled" ? fleet.value.waiting : [],
    fleetOk: fleet.status === "fulfilled",
  };
}

const HOST_IDENTITY_CHANGED = "Host identity changed — re-pair to continue";
const ALLOWED_HOSTS_HINT =
  "The host may also not list this address in http.allowed_hosts.";

function problemText(
  status: HostStatus,
  error: Error | null | undefined,
): string | undefined {
  switch (status) {
    case "identity_changed":
      // A host that does not list the dialled address in http.allowed_hosts answers with an
      // unsigned decoy challenge, which looks exactly like a changed host key (WV A1).
      return `${error?.message ?? HOST_IDENTITY_CHANGED}. ${ALLOWED_HOSTS_HINT}`;
    case "refused":
    case "blocked":
      return error?.message ?? status;
    case "unauthorized":
      return "This device is no longer paired with this host";
    case "incompatible":
      return error?.message ?? "Incompatible host";
    default:
      return undefined;
  }
}
