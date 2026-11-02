/**
 * Many hosts at once (plan 0055 D6): one direct connection per profile while the tab is
 * visible. Each host keeps its own `seq` cursor; events reach handlers tagged with their
 * host id, in that host's order, and sequences are never merged across hosts. A host that is
 * down, refused by the D7 check, or failing its handshake does not affect the others.
 */
import {
  type Connection,
  type MethodName,
  type MethodParams,
  type MethodResult,
  openConnection,
  type ProtocolEvent,
  type Status,
} from "./connection.ts";
import { DirectUrlRefused } from "./errors.ts";
import { checkDirectUrl, type HostProfile } from "./profiles.ts";

/** A connection status, `idle` before `start`/after `stop`, `refused` by the D7 check. */
export type HostStatus = Status | "idle" | "refused";

export type HostEventHandler = (hostId: string, event: ProtocolEvent) => void;

export type HostStatusHandler = (hostId: string, status: HostStatus) => void;

export type Hosts = {
  /** Dial every profile that passes the D7 check. */
  start: () => void;
  /** Close every connection; each host keeps its cursor for the next `start`. */
  stop: () => void;
  onEvent: (handler: HostEventHandler) => () => void;
  /** Called on every status change of any host. */
  onStatus: (handler: HostStatusHandler) => () => void;
  status: (hostId: string) => HostStatus;
  /** Why a host is not connected (`DirectUrlRefused`, `HostIdentityChanged`, …), if known. */
  error: (hostId: string) => Error | null;
  call: <M extends MethodName>(
    hostId: string,
    method: M,
    params: MethodParams[M],
  ) => Promise<MethodResult[M]>;
};

type Entry = {
  profile: HostProfile;
  connection: Connection | null;
  status: HostStatus;
  error: Error | null;
  lastSeq: number;
};

/** Statuses the client never leaves on its own: the user has to act (re-pair, fix the URL). */
const FINAL: ReadonlySet<HostStatus> = new Set<HostStatus>([
  "refused",
  "unauthorized",
  "incompatible",
  "identity_changed",
  "blocked",
]);

export function createHosts(options: {
  profiles: readonly HostProfile[];
}): Hosts {
  const entries = new Map<string, Entry>();
  for (const profile of options.profiles) {
    entries.set(profile.host_id, {
      profile,
      connection: null,
      status: "idle",
      error: null,
      lastSeq: 0,
    });
  }
  const handlers: HostEventHandler[] = [];
  const statusHandlers: HostStatusHandler[] = [];
  let running = false;

  function setStatus(entry: Entry, next: HostStatus): void {
    if (entry.status === next) {
      return;
    }
    entry.status = next;
    for (const handler of [...statusHandlers]) {
      handler(entry.profile.host_id, next);
    }
  }

  function open(entry: Entry): void {
    if (entry.connection !== null || FINAL.has(entry.status)) {
      return;
    }
    const profile = entry.profile;
    const hostId = profile.host_id;
    // D7 runs before any socket exists.
    const check = checkDirectUrl(profile.direct_url, {
      private_networks: profile.private_networks,
      allow_plain_ws: profile.allow_plain_ws,
    });
    if (!check.ok) {
      entry.error = new DirectUrlRefused(profile.direct_url, check.reason);
      setStatus(entry, "refused");
      return;
    }
    entry.error = null;
    const { connection, ready } = openConnection({
      url: profile.direct_url,
      lastSeq: entry.lastSeq,
      device: {
        id: profile.device_id,
        key: profile.device_key,
        hostPubkey: profile.host_pubkey,
        hostFp: profile.host_pubkey_fp,
      },
    });
    entry.connection = connection;
    connection.onStatus((next) => {
      if (entry.connection === connection) {
        setStatus(entry, next);
      }
    });
    connection.onEvent((event) => {
      if (entry.connection !== connection) {
        return;
      }
      entry.lastSeq = event.s;
      for (const handler of [...handlers]) {
        handler(hostId, event);
      }
    });
    ready.catch((reason: unknown) => {
      if (entry.connection === connection) {
        entry.error =
          reason instanceof Error ? reason : new Error(String(reason));
      }
    });
  }

  function suspend(entry: Entry): void {
    const connection = entry.connection;
    if (connection === null || FINAL.has(entry.status)) {
      return;
    }
    entry.connection = null;
    setStatus(entry, "idle");
    connection.close();
  }

  function onVisibility(): void {
    if (!running) {
      return;
    }
    const hidden = document.visibilityState === "hidden";
    for (const entry of entries.values()) {
      if (hidden) {
        suspend(entry);
      } else {
        open(entry);
      }
    }
  }

  return {
    start() {
      if (!running && typeof document !== "undefined") {
        document.addEventListener("visibilitychange", onVisibility);
      }
      running = true;
      for (const entry of entries.values()) {
        open(entry);
      }
    },
    stop() {
      if (running && typeof document !== "undefined") {
        document.removeEventListener("visibilitychange", onVisibility);
      }
      running = false;
      for (const entry of entries.values()) {
        const connection = entry.connection;
        entry.connection = null;
        entry.error = null;
        setStatus(entry, "idle");
        connection?.close();
      }
    },
    onEvent(handler) {
      handlers.push(handler);
      return () => {
        const index = handlers.indexOf(handler);
        if (index >= 0) {
          handlers.splice(index, 1);
        }
      };
    },
    onStatus(handler) {
      statusHandlers.push(handler);
      return () => {
        const index = statusHandlers.indexOf(handler);
        if (index >= 0) {
          statusHandlers.splice(index, 1);
        }
      };
    },
    status(hostId) {
      return entries.get(hostId)?.status ?? "idle";
    },
    error(hostId) {
      return entries.get(hostId)?.error ?? null;
    },
    call(hostId, method, params) {
      const entry = entries.get(hostId);
      if (entry === undefined) {
        return Promise.reject(new Error(`unknown host: ${hostId}`));
      }
      if (entry.connection === null || FINAL.has(entry.status)) {
        return Promise.reject(entry.error ?? new Error("not connected"));
      }
      return entry.connection.call(method, params);
    },
  };
}
