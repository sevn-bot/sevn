import { vi } from "vitest";

const socketUrl = "ws://localhost:3000/ws";

export type Frame = Record<string, unknown>;

type Reply =
  | Record<string, unknown>
  | ((params: Record<string, unknown>, nth: number) => Record<string, unknown>);

type MockSocket = {
  on: (event: "message", handler: (data: unknown) => void) => void;
  send: (data: string) => void;
  close: () => void;
};

type MockServer = {
  on: (event: "connection", handler: (socket: MockSocket) => void) => void;
  stop: () => void;
};

export type Harness = {
  requests: Frame[];
  tick: (kind: string, data: Record<string, unknown>) => void;
  event: (kind: string, data: Record<string, unknown>) => void;
  stop: () => void;
};

export async function startHarness(
  replies: Record<string, Reply>,
): Promise<Harness> {
  const mockName = "mock-socket";
  const mock = (await import(mockName)) as {
    Server: new (address: string) => MockServer;
    WebSocket: unknown;
  };
  vi.stubGlobal("WebSocket", mock.WebSocket);
  const server = new mock.Server(socketUrl);
  const requests: Frame[] = [];
  const counts = new Map<string, number>();
  let current: MockSocket | null = null;
  let seq = 1;
  server.on("connection", (socket) => {
    current = socket;
    let welcomed = false;
    const welcome = () => {
      if (welcomed) {
        return;
      }
      welcomed = true;
      socket.send(
        JSON.stringify({ t: "welcome", proto: 1, host_seq: 0, caps: [] }),
      );
    };
    socket.on("message", (data) => {
      const frame = JSON.parse(String(data)) as Frame;
      if (frame.t === "hello") {
        setTimeout(welcome, 0);
      }
      if (frame.t === "auth") {
        welcome();
      }
      if (frame.t !== "req" || typeof frame.m !== "string") {
        return;
      }
      requests.push(frame);
      const method = frame.m;
      const nth = (counts.get(method) ?? 0) + 1;
      counts.set(method, nth);
      const params = isRecord(frame.p) ? frame.p : {};
      const reply = replies[method];
      const body =
        typeof reply === "function" ? reply(params, nth) : (reply ?? {});
      socket.send(JSON.stringify({ t: "res", id: frame.id, r: body }));
    });
  });
  const clientName = "../../src/client/index.ts";
  const client = (await import(clientName)) as {
    connect: (options: {
      url: string;
      token?: string;
    }) => Promise<{ close: () => void }>;
  };
  const connection = await client.connect({
    url: socketUrl,
    token: "test-token",
  });
  return {
    requests,
    tick(kind, data) {
      current?.send(JSON.stringify({ t: "tick", k: kind, d: data }));
    },
    event(kind, data) {
      current?.send(JSON.stringify({ t: "evt", s: seq, k: kind, d: data }));
      seq += 1;
    },
    stop() {
      connection.close();
      server.stop();
      vi.unstubAllGlobals();
    },
  };
}

export function requestParams(
  requests: Frame[],
  method: string,
): Record<string, unknown>[] {
  const found: Record<string, unknown>[] = [];
  for (const frame of requests) {
    if (frame.m === method && isRecord(frame.p)) {
      found.push(frame.p);
    }
  }
  return found;
}

type Component = (props: Record<string, unknown>) => unknown;

export async function loadBotList(): Promise<Component> {
  const modules = import.meta.glob("../../src/app/bots/BotList.tsx");
  return named(modules, "BotList");
}

export async function loadChat(): Promise<Component> {
  const modules = import.meta.glob("../../src/app/chat/Chat.tsx");
  return named(modules, "Chat");
}

export async function loadMemoriesPanel(): Promise<Component> {
  const modules = import.meta.glob("../../src/app/bots/MemoriesPanel.tsx");
  return named(modules, "MemoriesPanel");
}

export async function loadDashboard(): Promise<Component> {
  const modules = import.meta.glob("../../src/app/fleet/Dashboard.tsx");
  return named(modules, "Dashboard");
}

async function named(
  modules: Record<string, () => Promise<unknown>>,
  exportName: string,
): Promise<Component> {
  const key = Object.keys(modules)[0];
  if (key === undefined) {
    throw new Error(`${exportName} module is missing`);
  }
  const loaded = (await modules[key]()) as Record<string, unknown>;
  const component = loaded[exportName];
  if (typeof component !== "function") {
    throw new Error(`expected named export ${exportName}`);
  }
  return component as Component;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
