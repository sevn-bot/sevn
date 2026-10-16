import { test, vi } from "vitest";

const socketUrl = "ws://localhost:3000/ws";
const hostId = "host_example";

type Frame = Record<string, unknown>;
type MockSocket = {
  on: (event: "message", handler: (data: unknown) => void) => void;
  send: (data: string) => void;
  close: () => void;
};
type MockServer = {
  on: (event: "connection", handler: (socket: MockSocket) => void) => void;
  stop: () => void;
};

function speak(socket: MockSocket): void {
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
    if (frame.t === "req" && frame.m === "system.info") {
      socket.send(
        JSON.stringify({
          t: "res",
          id: frame.id,
          r: { host_id: hostId, version: "0.0.0", proto: 1, caps: [] },
        }),
      );
    }
    if (frame.t === "req" && frame.m === "system.ping") {
      socket.send(JSON.stringify({ t: "res", id: frame.id, r: { seq: 4 } }));
      socket.send(
        JSON.stringify({ t: "evt", s: 4, k: "system.ping", d: { note: "hi" } }),
      );
    }
    if (frame.t === "req" && frame.m === "sync.since") {
      socket.send(JSON.stringify({ t: "res", id: frame.id, r: {} }));
    }
  });
}

async function mount(): Promise<{
  server: MockServer;
  screen: {
    findByText: (
      text: string,
      options?: { exact?: boolean },
      wait?: { timeout?: number },
    ) => Promise<unknown>;
    findByRole: (
      role: string,
      options: { name: string },
    ) => Promise<{ click: () => Promise<void> }>;
    getByText: (text: string) => unknown;
  };
  cleanup: () => void;
  sockets: MockSocket[];
}> {
  const mockName = "mock-socket";
  const testingName = "@testing-library/react";
  const appName = "../../src/app/App.tsx";
  const mock = (await import(mockName)) as {
    Server: new (address: string) => MockServer;
    WebSocket: unknown;
  };
  const testing = (await import(testingName)) as {
    render: (node: unknown) => unknown;
    screen: {
      findByText: (
        text: string,
        options?: { exact?: boolean },
        wait?: { timeout?: number },
      ) => Promise<unknown>;
      findByRole: (
        role: string,
        options: { name: string },
      ) => Promise<{ click: () => Promise<void> }>;
      getByText: (text: string) => unknown;
    };
    cleanup: () => void;
  };
  const app = (await import(appName)) as { default: () => unknown };
  vi.stubGlobal("WebSocket", mock.WebSocket);
  const server = new mock.Server(socketUrl);
  const sockets: MockSocket[] = [];
  server.on("connection", (socket) => {
    sockets.push(socket);
    speak(socket);
  });
  const { createElement } = await import("react");
  testing.render(createElement(app.default));
  return { server, screen: testing.screen, cleanup: testing.cleanup, sockets };
}

test("shows connected with host id after welcome", async () => {
  const mounted = await mount();
  try {
    await mounted.screen.findByText("connected");
    await mounted.screen.findByText(hostId);
  } finally {
    mounted.cleanup();
    mounted.server.stop();
    vi.unstubAllGlobals();
  }
});

test("Ping shows the returned event seq", async () => {
  const mounted = await mount();
  try {
    await mounted.screen.findByText("connected");
    const button = await mounted.screen.findByRole("button", { name: "Ping" });
    await button.click();
    await mounted.screen.findByText("event #4 — system.ping");
  } finally {
    mounted.cleanup();
    mounted.server.stop();
    vi.unstubAllGlobals();
  }
});

test("shows reconnecting then connected after a drop", async () => {
  const mounted = await mount();
  try {
    await mounted.screen.findByText("connected");
    mounted.sockets.at(-1)?.close();
    await mounted.screen.findByText(
      "reconnecting",
      { exact: true },
      { timeout: 2000 },
    );
    await mounted.screen.findByText(
      "connected",
      { exact: true },
      { timeout: 4000 },
    );
  } finally {
    mounted.cleanup();
    mounted.server.stop();
    vi.unstubAllGlobals();
  }
});
