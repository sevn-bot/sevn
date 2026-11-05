import { useCallback, useEffect, useRef, useState } from "react";
import {
  type Connection,
  cancelConnect,
  connect,
  type DeviceAuth,
  type Status,
} from "../client/index.ts";
import { pairDevice } from "../client/pairing.ts";
import { BotList } from "./bots/BotList.tsx";
import { Chat } from "./chat/Chat.tsx";
import { DevicesPage } from "./devices/DevicesPage.tsx";
import { BriefPage } from "./fleet/BriefPage.tsx";
import { Dashboard } from "./fleet/Dashboard.tsx";
import { SharePage } from "./fleet/SharePage.tsx";
import { Approvals } from "./hosts/Approvals.tsx";
import { type HostClient, HostClientProvider } from "./hosts/HostClient.tsx";
import { HostSidebar } from "./hosts/HostSidebar.tsx";
import { Inbox } from "./hosts/Inbox.tsx";
import {
  type HostView,
  problemText,
  profileStore,
  sameOrigin,
  useMultiHost,
} from "./hosts/useHosts.ts";
import {
  type PairedHost,
  type PairInput,
  PairingPage,
} from "./pairing/PairingPage.tsx";
import {
  agentPath,
  botPath,
  devicesPath,
  fleetPath,
  go,
  hostBotPath,
  isBriefPath,
  pairingPath,
  routeFromPath,
  shareFromPath,
} from "./routes.ts";

type ShownEvent = {
  seq: number;
  kind: string;
};

function socketUrl(): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws`;
}

/**
 * The device key this browser holds for the host that serves the page, if it paired with
 * it (plan 0055 D6). A same-origin page reached through a proxy or a container's published
 * port is not loopback (D4), so it answers the host's challenge with this key.
 */
async function ownDevice(): Promise<DeviceAuth | undefined> {
  try {
    const own = socketUrl();
    const profile = (await profileStore().list()).find((item) =>
      sameOrigin(item.direct_url, own),
    );
    if (profile === undefined) {
      return undefined;
    }
    return {
      id: profile.device_id,
      key: profile.device_key,
      hostPubkey: profile.host_pubkey,
      hostFp: profile.host_pubkey_fp,
    };
  } catch {
    return undefined;
  }
}

function remember(
  events: ShownEvent[],
  seq: number,
  kind: string,
): ShownEvent[] {
  if (events.some((event) => event.seq === seq)) {
    return events;
  }
  return [...events, { seq, kind }];
}

export default function App() {
  // A share link is for someone who is not the owner: no login and no socket.
  const share = shareFromPath(window.location.pathname);
  if (share !== null) {
    return <SharePage shareId={share.shareId} secret={share.secret} />;
  }
  return <OwnerApp />;
}

function OwnerApp() {
  const [status, setStatus] = useState<Status>("connecting");
  const ownProblem = problemText(status, null);
  const [hostId, setHostId] = useState("");
  const [forgetError, setForgetError] = useState<string | null>(null);
  const [events, setEvents] = useState<ShownEvent[]>([]);
  const [path, setPath] = useState(() => window.location.pathname);
  const connectionRef = useRef<Connection | null>(null);
  const route = routeFromPath(path);
  const [profilesVersion, setProfilesVersion] = useState(0);
  const reloadProfiles = useCallback(() => {
    setProfilesVersion((current) => current + 1);
  }, []);
  // Bumped when this browser pairs with the host that serves the page (D6): the page's own
  // connection then reconnects with that device key.
  const [ownVersion, setOwnVersion] = useState(0);
  const multiHost = useMultiHost(
    { hostId, status, url: socketUrl() },
    profilesVersion,
    reloadProfiles,
  );
  const multi = multiHost.views.length > 0;

  async function pairHost(input: PairInput): Promise<PairedHost> {
    const profile = await pairDevice({
      url: input.url,
      ticket: input.code,
      deviceName: `Browser at ${window.location.host}`,
      platform: "web",
      store: profileStore(),
      allowPlainWs: input.allowPlainWs,
      ...(input.privateNetworks === undefined
        ? {}
        : { privateNetworks: input.privateNetworks }),
      ...(input.expectedFp === undefined
        ? {}
        : { expectedFp: input.expectedFp }),
      ...(input.expectedHostId === undefined
        ? {}
        : { expectedHostId: input.expectedHostId }),
    });
    reloadProfiles();
    if (sameOrigin(profile.direct_url, socketUrl())) {
      setOwnVersion((current) => current + 1);
    }
    return { host_id: profile.host_id, name: profile.name };
  }

  useEffect(() => {
    const sync = () => {
      setPath(window.location.pathname);
    };
    window.addEventListener("popstate", sync);
    return () => {
      window.removeEventListener("popstate", sync);
    };
  }, []);

  // biome-ignore lint/correctness/useExhaustiveDependencies: ownVersion is the reconnect signal.
  useEffect(() => {
    let alive = true;
    let current: Connection | undefined;
    void ownDevice()
      .then((device) => {
        if (!alive) {
          return new Promise<Connection>(() => undefined);
        }
        return connect({
          url: socketUrl(),
          lastSeq: 0,
          ...(device === undefined ? {} : { device }),
          onStatus: (next) => {
            if (alive) {
              setStatus(next);
            }
          },
        });
      })
      .then(
        (connection) => {
          if (!alive) {
            connection.close();
            return;
          }
          current = connection;
          connectionRef.current = connection;
          connection.onEvent((event) => {
            if (!alive) {
              return;
            }
            setEvents((existing) => remember(existing, event.s, event.k));
          });
          void connection.call("system.info", {}).then(
            (info) => {
              if (alive) {
                setHostId(info.host_id);
              }
            },
            () => undefined,
          );
        },
        () => {
          if (alive) {
            // A refusal already set its status: the connection stopped and will not redial.
            setStatus((current) =>
              problemText(current, null) === undefined
                ? "reconnecting"
                : current,
            );
          }
        },
      );
    return () => {
      alive = false;
      current?.close();
      cancelConnect();
      connectionRef.current = null;
    };
  }, [ownVersion]);

  async function onPing(): Promise<void> {
    const current = connectionRef.current;
    if (current === null) {
      return;
    }
    try {
      const result = await current.call("system.ping", { note: "hi" });
      setEvents((existing) => remember(existing, result.seq, "system.ping"));
    } catch {
      // The event row is also appended when the evt frame is delivered.
    }
  }

  const page = isBriefPath(path) ? (
    <BriefPage />
  ) : path === devicesPath ? (
    <DevicesPage />
  ) : path === pairingPath ? (
    <PairingPage pair={pairHost} />
  ) : path === fleetPath ? (
    <Dashboard />
  ) : route.botId !== null &&
    route.hostId !== null &&
    route.hostId !== hostId ? (
    <RemoteChat
      hostId={route.hostId}
      botId={route.botId}
      agentId={route.agentId}
      client={multiHost.client(route.hostId)}
      name={
        multiHost.views.find((view) => view.host_id === route.hostId)?.name ??
        null
      }
    />
  ) : route.botId !== null ? (
    <Chat key={route.botId} botId={route.botId} agentId={route.agentId} />
  ) : multi ? (
    <MultiHostHome views={multiHost.views} />
  ) : (
    <>
      <Dashboard />
      <BotList />
    </>
  );

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100">
      <header className="flex flex-wrap items-baseline gap-3 border-b border-zinc-800 px-4 py-3">
        <p>{status}</p>
        {ownProblem !== undefined ? (
          <p role="alert" className="text-sm text-red-300">
            {ownProblem}
          </p>
        ) : null}
        {hostId !== "" ? <p className="font-mono text-sm">{hostId}</p> : null}
        <nav aria-label="Settings" className="ml-auto flex gap-3 text-sm">
          <button
            type="button"
            className="text-zinc-400 underline"
            onClick={() => {
              go(devicesPath);
            }}
          >
            Devices
          </button>
          <button
            type="button"
            className="text-zinc-400 underline"
            onClick={() => {
              go(pairingPath);
            }}
          >
            Add a host
          </button>
        </nav>
      </header>
      <div className={multi ? "md:flex" : undefined}>
        {multi ? (
          <aside className="border-b border-zinc-800 px-4 py-4 md:w-60 md:shrink-0 md:border-r md:border-b-0">
            <HostSidebar
              hosts={multiHost.views.map((view) => ({
                host_id: view.host_id,
                name: view.name,
                reachable: view.reachable,
                bots: view.bots,
                removable: !view.local,
                ...(view.problem === undefined
                  ? {}
                  : { problem: view.problem }),
              }))}
              onPick={(pickedHost, botId) => {
                const local = multiHost.views.find(
                  (view) => view.host_id === pickedHost,
                )?.local;
                go(botPath(local === false ? pickedHost : null, botId));
              }}
              onForget={(hostId) => {
                setForgetError(null);
                void multiHost
                  .forget(hostId)
                  .then((warning) => {
                    setForgetError(warning ?? null);
                  })
                  .catch((error: unknown) => {
                    setForgetError(
                      error instanceof Error
                        ? error.message
                        : "Could not forget host",
                    );
                  });
              }}
            />
          </aside>
        ) : null}
        <main className="min-w-0 flex-1 space-y-4 px-4 py-4">
          <button
            type="button"
            className="rounded bg-zinc-100 px-3 py-1.5 text-sm font-medium text-zinc-950 disabled:opacity-40"
            disabled={status !== "connected"}
            onClick={() => {
              void onPing();
            }}
          >
            Ping
          </button>
          {forgetError !== null ? (
            <p role="alert" className="text-red-300">
              {forgetError}
            </p>
          ) : null}
          {page}
          <ul className="space-y-1 font-mono text-sm">
            {events.map((event) => (
              <li key={event.seq}>{`event #${event.seq} — ${event.kind}`}</li>
            ))}
          </ul>
        </main>
      </div>
    </div>
  );
}

/** A bot's chat on a paired host: Chat talks to that host's connection only. */
function RemoteChat({
  hostId,
  botId,
  agentId,
  client,
  name,
}: {
  hostId: string;
  botId: string;
  agentId: string | null;
  client: HostClient | null;
  name: string | null;
}) {
  if (client === null) {
    return (
      <p className="text-sm text-zinc-400">
        {name === null ? "Connecting…" : `Connecting to ${name}…`}
      </p>
    );
  }
  return (
    <HostClientProvider client={client}>
      <Chat
        key={`${hostId}|${botId}`}
        hostId={hostId}
        botId={botId}
        agentId={agentId}
      />
    </HostClientProvider>
  );
}

/** Home with paired hosts (plan 0055 D9): one Inbox and one Approvals across hosts. */
function MultiHostHome({ views }: { views: HostView[] }) {
  const hosts = views.map((view) => ({
    host_id: view.host_id,
    name: view.name,
    available: view.available,
    waiting: view.waiting,
  }));
  const open = (hostId: string, item: { bot_id: string; agent_id: string }) => {
    const local = views.find((view) => view.host_id === hostId)?.local;
    go(
      local === false
        ? `${hostBotPath(hostId, item.bot_id)}/agents/${encodeURIComponent(item.agent_id)}`
        : agentPath(item.bot_id, item.agent_id),
    );
  };
  return (
    <>
      <div className="grid gap-4 lg:grid-cols-2">
        <Inbox hosts={hosts} onOpen={open} />
        <Approvals hosts={hosts} onOpen={open} />
      </div>
      <button
        type="button"
        className="text-sm text-zinc-400 underline"
        onClick={() => {
          go(fleetPath);
        }}
      >
        This host's dashboard
      </button>
      <BotList />
    </>
  );
}
