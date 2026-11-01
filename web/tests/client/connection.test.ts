import { expect, test, vi } from "vitest";

const url = "ws://127.0.0.1:9876/ws";

type Frame = Record<string, unknown>;

type Connection = {
  call: (method: string, params: Record<string, unknown>) => Promise<unknown>;
  onEvent: (
    handler: (event: {
      s: number;
      k: string;
      d: Record<string, unknown>;
    }) => void,
  ) => void;
  close: () => void;
};

type Connect = (options: {
  url: string;
  token?: string;
  lastSeq?: number;
}) => Promise<Connection>;

type MockSocket = {
  on: (event: "message", handler: (data: unknown) => void) => void;
  send: (data: string) => void;
  close: (options?: {
    code?: number;
    reason?: string;
    wasClean?: boolean;
  }) => void;
};

type MockServer = {
  on: (event: "connection", handler: (socket: MockSocket) => void) => void;
  stop: () => void;
};

function frameOf(data: unknown): Frame {
  return JSON.parse(String(data)) as Frame;
}

async function loadClient(): Promise<{ connect: Connect }> {
  const specifier = "../../src/client/index.ts";
  return import(specifier);
}

async function loadErrors(): Promise<{
  ProtocolError: new (...args: never[]) => Error & { code: string };
  Unauthorized: new (...args: never[]) => Error;
}> {
  const specifier = "../../src/client/errors.ts";
  return import(specifier);
}

async function loadMock(): Promise<{
  Server: new (address: string) => MockServer;
  WebSocket: unknown;
}> {
  const specifier = "mock-socket";
  return import(specifier);
}

function welcome(hostSeq = 0): string {
  return JSON.stringify({
    t: "welcome",
    proto: 1,
    host_seq: hostSeq,
    caps: [],
  });
}

test("connect sends hello with last_seq and resolves on welcome", async () => {
  const { connect } = await loadClient();
  const { Server, WebSocket } = await loadMock();
  vi.stubGlobal("WebSocket", WebSocket);
  const server = new Server(url);
  const inbox: Frame[] = [];
  let socket: MockSocket | undefined;
  server.on("connection", (next) => {
    socket = next;
    next.on("message", (data) => {
      inbox.push(frameOf(data));
    });
  });
  try {
    let settled = false;
    const pending = connect({ url, token: "tok", lastSeq: 7 }).then(
      (connection) => {
        settled = true;
        return connection;
      },
      (error: unknown) => {
        settled = true;
        throw error;
      },
    );
    await vi.waitFor(() => {
      if (!inbox.some((frame) => frame.t === "auth")) {
        throw new Error("waiting for auth");
      }
    });
    const hello = inbox.find((frame) => frame.t === "hello");
    const auth = inbox.find((frame) => frame.t === "auth");
    expect(hello?.proto).toEqual([1, 1]);
    expect(hello?.last_seq).toBe(7);
    expect(hello?.client).toBe("web");
    expect(auth?.token).toBe("tok");
    await Promise.resolve();
    expect(settled).toBe(false);
    socket?.send(welcome());
    await pending;
  } finally {
    server.stop();
    vi.unstubAllGlobals();
  }
});

test("call correlates responses by id", async () => {
  const { connect } = await loadClient();
  const { Server, WebSocket } = await loadMock();
  vi.stubGlobal("WebSocket", WebSocket);
  const server = new Server(url);
  const requests: Frame[] = [];
  let socket: MockSocket | undefined;
  server.on("connection", (next) => {
    socket = next;
    next.on("message", (data) => {
      const frame = frameOf(data);
      if (frame.t === "hello") {
        next.send(welcome());
      }
      if (frame.t === "req") {
        requests.push(frame);
      }
    });
  });
  try {
    const connection = await connect({ url, token: "tok", lastSeq: 0 });
    const info = connection.call("system.info", {});
    const ping = connection.call("system.ping", { note: "n" });
    await vi.waitFor(() => {
      if (requests.length < 2) {
        throw new Error("waiting for calls");
      }
    });
    const pingReq = requests.find((frame) => frame.m === "system.ping");
    const infoReq = requests.find((frame) => frame.m === "system.info");
    const pingParams = pingReq?.p as { op_id?: string };
    expect(typeof pingParams.op_id).toBe("string");
    expect(pingParams.op_id?.length).toBeGreaterThan(0);
    socket?.send(JSON.stringify({ t: "res", id: pingReq?.id, r: { seq: 9 } }));
    socket?.send(
      JSON.stringify({
        t: "res",
        id: infoReq?.id,
        r: { host_id: "host_a", version: "0.0.0", proto: 1, caps: [] },
      }),
    );
    await expect(ping).resolves.toEqual({ seq: 9 });
    await expect(info).resolves.toMatchObject({ host_id: "host_a" });
  } finally {
    server.stop();
    vi.unstubAllGlobals();
  }
});

test("call rejects with ProtocolError carrying code and message", async () => {
  const { connect } = await loadClient();
  const { ProtocolError } = await loadErrors();
  const { Server, WebSocket } = await loadMock();
  vi.stubGlobal("WebSocket", WebSocket);
  const server = new Server(url);
  server.on("connection", (socket) => {
    socket.on("message", (data) => {
      const frame = frameOf(data);
      if (frame.t === "hello") {
        socket.send(welcome());
      }
      if (frame.t === "req") {
        socket.send(
          JSON.stringify({
            t: "res",
            id: frame.id,
            e: { code: "method_not_found", message: "missing" },
          }),
        );
      }
    });
  });
  try {
    const connection = await connect({ url, token: "tok", lastSeq: 0 });
    const error = await connection.call("missing.method", {}).then(
      () => {
        throw new Error("expected ProtocolError");
      },
      (caught: unknown) => caught,
    );
    expect(error).toBeInstanceOf(ProtocolError);
    expect((error as { code: string; message: string }).code).toBe(
      "method_not_found",
    );
    expect((error as { message: string }).message).toBe("missing");
  } finally {
    server.stop();
    vi.unstubAllGlobals();
  }
});

test("events arrive in seq order and duplicates are dropped", async () => {
  const { connect } = await loadClient();
  const { Server, WebSocket } = await loadMock();
  vi.stubGlobal("WebSocket", WebSocket);
  const server = new Server(url);
  let socket: MockSocket | undefined;
  server.on("connection", (next) => {
    socket = next;
    next.on("message", (data) => {
      if (frameOf(data).t === "hello") {
        next.send(welcome(0));
      }
    });
  });
  try {
    const connection = await connect({ url, token: "tok", lastSeq: 0 });
    const seen: number[] = [];
    connection.onEvent((event) => {
      seen.push(event.s);
    });
    for (const seq of [2, 1, 3, 2]) {
      socket?.send(
        JSON.stringify({
          t: "evt",
          s: seq,
          k: "system.ping",
          d: { note: "n" },
        }),
      );
    }
    await vi.waitFor(() => {
      if (seen.join(",") !== "1,2,3") {
        throw new Error(`seen ${seen.join(",")}`);
      }
    });
  } finally {
    server.stop();
    vi.unstubAllGlobals();
  }
});

test("reconnect calls sync.since with the last seen seq", async () => {
  const { connect } = await loadClient();
  const { Server, WebSocket } = await loadMock();
  vi.stubGlobal("WebSocket", WebSocket);
  const server = new Server(url);
  const hellos: Frame[] = [];
  const syncs: Frame[] = [];
  let generation = 0;
  server.on("connection", (socket) => {
    generation += 1;
    const current = generation;
    socket.on("message", (data) => {
      const frame = frameOf(data);
      if (frame.t === "hello") {
        hellos.push(frame);
        socket.send(welcome(current === 1 ? 0 : 5));
      }
      if (frame.t === "auth" && current === 1) {
        for (const seq of [1, 2, 3, 4, 5]) {
          socket.send(
            JSON.stringify({ t: "evt", s: seq, k: "system.ping", d: {} }),
          );
        }
        socket.close();
      }
      if (frame.t === "req" && frame.m === "sync.since") {
        syncs.push(frame);
      }
    });
  });
  try {
    const connection = await connect({ url, token: "tok", lastSeq: 0 });
    await vi.waitFor(() => {
      const seq = (syncs.at(-1)?.p as { seq?: number } | undefined)?.seq;
      if (seq !== 5) {
        throw new Error("waiting for sync.since");
      }
    });
    expect(hellos.at(-1)?.last_seq).toBe(5);
    connection.close();
  } finally {
    server.stop();
    vi.unstubAllGlobals();
  }
});

test("a reconnect from a zero cursor replays what happened offline", async () => {
  const { connect } = await loadClient();
  const { Server, WebSocket } = await loadMock();
  vi.stubGlobal("WebSocket", WebSocket);
  const server = new Server(url);
  const syncs: Frame[] = [];
  let generation = 0;
  server.on("connection", (socket) => {
    generation += 1;
    const current = generation;
    socket.on("message", (data) => {
      const frame = frameOf(data);
      if (frame.t === "hello") {
        // Empty host first; events 1-3 happen while the client is offline.
        socket.send(welcome(current === 1 ? 0 : 3));
      }
      if (frame.t === "req" && frame.m === "sync.since") {
        syncs.push(frame);
        socket.send(
          JSON.stringify({ t: "res", id: frame.id, r: { events: [] } }),
        );
        if (current === 1) {
          socket.close();
        }
      }
    });
  });
  try {
    const connection = await connect({ url, token: "tok", lastSeq: 0 });
    await vi.waitFor(() => {
      if (syncs.length < 2) {
        throw new Error("waiting for the reconnect sync");
      }
    });
    const seqs = syncs.map((frame) => (frame.p as { seq?: number }).seq);
    expect(seqs.slice(0, 2)).toEqual([0, 0]);
    connection.close();
  } finally {
    server.stop();
    vi.unstubAllGlobals();
  }
});

test("close 4001 surfaces Unauthorized and does not retry", async () => {
  const { connect } = await loadClient();
  const { Unauthorized } = await loadErrors();
  const { Server, WebSocket } = await loadMock();
  vi.stubGlobal("WebSocket", WebSocket);
  const server = new Server(url);
  let connections = 0;
  server.on("connection", (socket) => {
    connections += 1;
    socket.on("message", (data) => {
      if (frameOf(data).t === "hello") {
        socket.close({ code: 4001, reason: "unauthorized", wasClean: false });
      }
    });
  });
  try {
    const error = await connect({ url, token: "tok", lastSeq: 0 }).then(
      () => {
        throw new Error("expected Unauthorized");
      },
      (caught: unknown) => caught,
    );
    expect(error).toBeInstanceOf(Unauthorized);
    await new Promise((resolve) => setTimeout(resolve, 700));
    expect(connections).toBe(1);
  } finally {
    server.stop();
    vi.unstubAllGlobals();
  }
});

test("slow-consumer reconnect replays from the delivered cursor", async () => {
  const { connect } = await loadClient();
  const { Server, WebSocket } = await loadMock();
  vi.stubGlobal("WebSocket", WebSocket);
  const server = new Server(url);
  const hellos: Frame[] = [];
  const syncs: Frame[] = [];
  let generation = 0;
  server.on("connection", (socket) => {
    const current = ++generation;
    socket.on("message", (data) => {
      const frame = frameOf(data);
      if (frame.t === "hello") {
        hellos.push(frame);
        socket.send(welcome(100));
      }
      if (frame.t === "req" && frame.m === "sync.since") {
        syncs.push(frame);
        if (current === 1) {
          socket.close({ code: 4008, reason: "slow", wasClean: false });
        } else {
          socket.send(
            JSON.stringify({ t: "res", id: frame.id, r: { events: [] } }),
          );
        }
      }
    });
  });
  try {
    const connection = await connect({ url, token: "tok", lastSeq: 7 });
    await vi.waitFor(() => {
      expect(syncs.length).toBeGreaterThanOrEqual(2);
    });
    expect(hellos.slice(0, 2).map((frame) => frame.last_seq)).toEqual([7, 7]);
    expect(
      syncs.slice(0, 2).map((frame) => (frame.p as { seq: number }).seq),
    ).toEqual([7, 7]);
    connection.close();
  } finally {
    server.stop();
    vi.unstubAllGlobals();
  }
});

test("welcome timeouts retry until the host becomes available", async () => {
  const { connect } = await loadClient();
  const { Server, WebSocket } = await loadMock();
  vi.stubGlobal("WebSocket", WebSocket);
  vi.useFakeTimers();
  const server = new Server(url);
  let attempts = 0;
  server.on("connection", (socket) => {
    const attempt = ++attempts;
    socket.on("message", (data) => {
      const frame = frameOf(data);
      if (frame.t === "hello" && attempt >= 3) socket.send(welcome());
      if (frame.t === "req")
        socket.send(
          JSON.stringify({ t: "res", id: frame.id, r: { events: [] } }),
        );
    });
  });
  try {
    const ready = connect({ url });
    await vi.advanceTimersByTimeAsync(33_000);
    const connection = await ready;
    expect(attempts).toBe(3);
    const reply = connection.call("sync.since", { seq: 0 });
    await vi.advanceTimersByTimeAsync(20);
    await expect(reply).resolves.toEqual({ events: [] });
    connection.close();
    await vi.advanceTimersByTimeAsync(60_000);
    expect(attempts).toBe(3);
  } finally {
    server.stop();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  }
});
