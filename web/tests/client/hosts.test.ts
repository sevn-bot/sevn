import { afterEach, expect, test, vi } from "vitest";
import {
  type DirectHost,
  directHost,
  type HostProfile,
  makeProfile,
  newHostKey,
  stubSockets,
  until,
} from "../support/direct.ts";

/**
 * Plan 0055 D6: one connection per profile, events ordered per host by `seq`.
 *
 * Pinned in `web/src/client/hosts.ts`:
 * `createHosts({ profiles })` -> `{ start(), stop(), onEvent(handler), status(hostId),
 * call(hostId, method, params) }`; `onEvent` handlers get `(hostId, { s, k, d })` and
 * return an unsubscribe function; `status(hostId) === "connected"` once welcomed.
 * A profile that fails the D7 check never opens a socket.
 */
type Event = { s: number; k: string; d: Record<string, unknown> };
type Hosts = {
  start: () => void;
  stop: () => void;
  onEvent: (handler: (hostId: string, event: Event) => void) => () => void;
  status: (hostId: string) => string;
  call: (
    hostId: string,
    method: string,
    params: Record<string, unknown>,
  ) => Promise<unknown>;
};

async function loadHosts(): Promise<{
  createHosts: (options: { profiles: HostProfile[] }) => Hosts;
}> {
  const specifier = "../../src/client/hosts.ts";
  return import(specifier);
}

const running: DirectHost[] = [];

afterEach(() => {
  for (const host of running.splice(0)) {
    host.stop();
  }
  vi.unstubAllGlobals();
});

async function twoHosts(mock: Awaited<ReturnType<typeof stubSockets>>) {
  const keyA = await newHostKey();
  const keyB = await newHostKey();
  const urlA = "ws://100.101.102.1:8787/ws";
  const urlB = "wss://linux.tailnet.ts.net/ws";
  const a = await makeProfile({ host_id: "host_a", direct_url: urlA }, keyA);
  const b = await makeProfile({ host_id: "host_b", direct_url: urlB }, keyB);
  const hostA = await directHost(mock, {
    url: urlA,
    hostId: "host_a",
    key: keyA,
    devicePubkey: a.devicePubkey,
    hostSeq: 6,
  });
  const hostB = await directHost(mock, {
    url: urlB,
    hostId: "host_b",
    key: keyB,
    devicePubkey: b.devicePubkey,
    hostSeq: 0,
  });
  running.push(hostA, hostB);
  return { a: a.profile, b: b.profile, hostA, hostB };
}

test("events are ordered per host and never merged across hosts", async () => {
  const mock = await stubSockets();
  const { a, b, hostA, hostB } = await twoHosts(mock);
  const { createHosts } = await loadHosts();
  const hosts = createHosts({ profiles: [a, b] });
  const seen: Record<string, number[]> = { host_a: [], host_b: [] };
  hosts.onEvent((hostId, event) => {
    seen[hostId]?.push(event.s);
  });
  hosts.start();
  try {
    await until(
      () =>
        hosts.status("host_a") === "connected" &&
        hosts.status("host_b") === "connected",
    );
    hostA.event(7, "system.ping");
    hostB.event(1, "system.ping");
    hostA.event(8, "system.ping");
    hostB.event(2, "system.ping");
    await until(() => seen.host_a?.length === 2 && seen.host_b?.length === 2);
    expect(seen).toEqual({ host_a: [7, 8], host_b: [1, 2] });
    // B reconnects from B's own cursor, not A's.
    hostB.drop();
    await until(
      () => hostB.connections[1]?.some((frame) => frame.t === "hello") === true,
      4000,
    );
    const hello = hostB.connections[1]?.find((frame) => frame.t === "hello");
    expect(hello?.last_seq).toBe(2);
    const helloA = hostA.connections[0]?.find((frame) => frame.t === "hello");
    expect(helloA?.device).toBe(a.device_id);
  } finally {
    hosts.stop();
  }
});

test("a request goes to the host it names", async () => {
  const mock = await stubSockets();
  const { a, b, hostA, hostB } = await twoHosts(mock);
  const { createHosts } = await loadHosts();
  const hosts = createHosts({ profiles: [a, b] });
  hosts.start();
  try {
    await until(() => hosts.status("host_b") === "connected");
    await hosts.call("host_b", "bots.list", {});
    const sentTo = (host: DirectHost) =>
      host.connections.flat().filter((frame) => frame.m === "bots.list");
    expect(sentTo(hostB).length).toBe(1);
    expect(sentTo(hostA).length).toBe(0);
  } finally {
    hosts.stop();
  }
});

test("one host down does not stop the others; a refused URL never dials", async () => {
  const mock = await stubSockets();
  const dialled: string[] = [];
  const Base = mock.WebSocket as new (url: string) => object;
  class Recording extends Base {
    constructor(url: string) {
      super(url);
      dialled.push(url);
    }
  }
  const { a, b, hostA, hostB } = await twoHosts(mock);
  vi.stubGlobal("WebSocket", Recording);
  const down = await makeProfile({
    host_id: "host_down",
    direct_url: "ws://100.101.102.9:8787/ws",
  });
  const lan = await makeProfile({
    host_id: "host_lan",
    direct_url: "ws://192.168.1.20:8787/ws",
  });
  const { createHosts } = await loadHosts();
  const hosts = createHosts({
    profiles: [down.profile, a, lan.profile, b],
  });
  const seen: string[] = [];
  hosts.onEvent((hostId, event) => {
    seen.push(`${hostId}:${event.s}`);
  });
  hosts.start();
  try {
    await until(
      () =>
        hosts.status("host_a") === "connected" &&
        hosts.status("host_b") === "connected",
    );
    hostA.event(7, "system.ping");
    hostB.event(1, "system.ping");
    await until(() => seen.length === 2);
    expect(seen.sort()).toEqual(["host_a:7", "host_b:1"]);
    expect(hosts.status("host_down")).not.toBe("connected");
    expect(hosts.status("host_lan")).not.toBe("connected");
    expect(dialled).not.toContain("ws://192.168.1.20:8787/ws");
    expect(dialled).toContain("ws://100.101.102.9:8787/ws");
  } finally {
    hosts.stop();
  }
});
