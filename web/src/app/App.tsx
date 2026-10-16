import { useEffect, useRef, useState } from "react";
import { type Connection, connect } from "../client/index.ts";

type Status = "connecting" | "connected" | "reconnecting";

type ShownEvent = {
  seq: number;
  kind: string;
};

function socketUrl(): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws`;
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
  const [status, setStatus] = useState<Status>("connecting");
  const [hostId, setHostId] = useState("");
  const [events, setEvents] = useState<ShownEvent[]>([]);
  const connectionRef = useRef<Connection | null>(null);

  useEffect(() => {
    let alive = true;
    let current: Connection | undefined;
    void connect({ url: socketUrl(), lastSeq: 0 }).then(
      (connection) => {
        if (!alive) {
          connection.close();
          return;
        }
        current = connection;
        connectionRef.current = connection;
        connection.onStatus((next) => {
          if (alive) {
            setStatus(next);
          }
        });
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
          setStatus("reconnecting");
        }
      },
    );
    return () => {
      alive = false;
      current?.close();
      connectionRef.current = null;
    };
  }, []);

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

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100">
      <header className="flex items-baseline gap-3 border-b border-zinc-800 px-4 py-3">
        <p>{status}</p>
        {hostId !== "" ? <p className="font-mono text-sm">{hostId}</p> : null}
      </header>
      <main className="space-y-4 px-4 py-4">
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
        <ul className="space-y-1 font-mono text-sm">
          {events.map((event) => (
            <li key={event.seq}>{`event #${event.seq} — ${event.kind}`}</li>
          ))}
        </ul>
      </main>
    </div>
  );
}
