import { afterEach, expect, test, vi } from "vitest";
import {
  b64u,
  type Frame,
  fingerprintOf,
  type HostProfile,
  makeProfile,
  newHostKey,
  stubSockets,
  unb64u,
} from "../support/direct.ts";

/**
 * Plan 0055 D1, D6, D7, D8: the device side of pairing.
 *
 * Pinned in `web/src/client/pairing.ts`:
 * - `parsePairUri(uri)` -> `{ host_id, host_pubkey_fp, ticket, direct_url | null }`;
 *   a non-`sevn://pair` link throws "not a sevn pairing link".
 * - `pairDevice({ url, ticket, deviceName, platform?, store, expectedFp?, allowPlainWs?,
 *   privateNetworks? })` -> the saved `HostProfile`. It runs the D7 check before dialling,
 *   sends `pair.complete` as its first frame after `hello`, and stores the profile only after
 *   `paired`. Errors (`web/src/client/errors.ts`): `DirectUrlRefused(url, reason)`,
 *   `CspBlocked(origin)`, `HostIdentityChanged`, `Unauthorized`.
 */
type ProfileStore = {
  put: (profile: HostProfile) => Promise<void>;
  get: (hostId: string) => Promise<HostProfile | undefined>;
  list: () => Promise<HostProfile[]>;
};
type Pairing = {
  parsePairUri: (uri: string) => {
    host_id: string;
    host_pubkey_fp: string;
    ticket: string;
    direct_url: string | null;
  };
  pairDevice: (options: {
    url: string;
    ticket: string;
    deviceName: string;
    platform?: string;
    store: ProfileStore;
    expectedFp?: string;
    expectedHostId?: string;
    allowPlainWs?: boolean;
  }) => Promise<HostProfile>;
};

type ErrorClass = new (...args: never[]) => Error;

async function load<T>(specifier: string): Promise<T> {
  return (await import(specifier)) as T;
}

const pairingPath = "../../src/client/pairing.ts";
const profilesPath = "../../src/client/profiles.ts";
const errorsPath = "../../src/client/errors.ts";

afterEach(() => {
  vi.unstubAllGlobals();
});

async function memoryStore(): Promise<ProfileStore> {
  const profiles = await load<{ memoryProfileStore: () => ProfileStore }>(
    profilesPath,
  );
  return profiles.memoryProfileStore();
}

type PairingHost = { frames: Frame[]; stop: () => void };

async function pairingHost(
  url: string,
  reply: (frame: Frame) => Frame | "unauthorized",
): Promise<PairingHost> {
  const mock = await stubSockets();
  const server = new mock.Server(url);
  const frames: Frame[] = [];
  server.on("connection", (socket) => {
    socket.on("message", (data) => {
      const frame = JSON.parse(String(data)) as Frame;
      frames.push(frame);
      if (frame.t === "hello") {
        socket.send(
          JSON.stringify({
            t: "challenge",
            nonce: b64u(new Uint8Array(32)),
            host: "host_linux",
            host_sig: b64u(new Uint8Array(64)),
          }),
        );
        return;
      }
      if (frame.t === "pair.complete") {
        const answer = reply(frame);
        if (answer === "unauthorized") {
          socket.close({ code: 4001, reason: "unauthorized" });
          return;
        }
        socket.send(JSON.stringify(answer));
        socket.close({ code: 1000, reason: "paired" });
      }
    });
  });
  return { frames, stop: () => server.stop() };
}

test("parsePairUri reads host, fingerprint, ticket and direct URL", async () => {
  const { parsePairUri } = await load<Pairing>(pairingPath);
  const direct = encodeURIComponent("wss://linux.tailnet.ts.net/ws");
  expect(
    parsePairUri(`sevn://pair?h=host_linux&k=fp123&t=ticket-abc&d=${direct}`),
  ).toEqual({
    host_id: "host_linux",
    host_pubkey_fp: "fp123",
    ticket: "ticket-abc",
    direct_url: "wss://linux.tailnet.ts.net/ws",
  });
  expect(
    parsePairUri("sevn://pair?h=host_linux&k=fp123&t=ticket-abc").direct_url,
  ).toBeNull();
  expect(() => parsePairUri("https://evil.example/pair?t=x")).toThrow(
    "not a sevn pairing link",
  );
});

test.each(["wss://linux.tailnet.ts.net/ws", "ws://127.0.0.1:8787/ws"])(
  "pairing at %s stores a non-extractable profile (including Docker)",
  async (url) => {
    const { pairDevice } = await load<Pairing>(pairingPath);
    const key = await newHostKey();
    const host = await pairingHost(url, () => ({
      t: "paired",
      device_id: "dev_new_phone",
      host_id: "host_linux",
      host_pubkey: key.pubkey,
      scope: "member",
    }));
    const store = await memoryStore();
    try {
      const profile = await pairDevice({
        url,
        ticket: "ABCD2345",
        deviceName: "Phone",
        platform: "web",
        store,
        expectedFp: key.fp,
      });
      expect(host.frames.map((frame) => frame.t)).toEqual([
        "hello",
        "pair.complete",
      ]);
      expect(host.frames[0]?.origin).toBe(new URL(url).origin);
      const complete = host.frames[1] ?? {};
      expect(complete.ticket).toBe("ABCD2345");
      expect(complete.device_name).toBe("Phone");
      expect(complete.platform).toBe("web");
      const pubkey = String(complete.device_pubkey_ed25519);
      expect(unb64u(pubkey).length).toBe(32);
      expect(profile).toMatchObject({
        host_id: "host_linux",
        device_id: "dev_new_phone",
        scope: "member",
        transport: "direct",
        direct_url: url,
        host_pubkey: key.pubkey,
        host_pubkey_fp: await fingerprintOf(unb64u(key.pubkey)),
        allow_plain_ws: false,
      });
      expect(profile.device_key.extractable).toBe(false);
      await expect(
        crypto.subtle.exportKey("pkcs8", profile.device_key),
      ).rejects.toThrow();
      expect(await store.get("host_linux")).toEqual(profile);
    } finally {
      host.stop();
    }
  },
);

test("a paired host whose key does not match the QR fingerprint is refused", async () => {
  const { pairDevice } = await load<Pairing>(pairingPath);
  const { HostIdentityChanged } =
    await load<Record<string, ErrorClass>>(errorsPath);
  const real = await newHostKey();
  const swapped = await newHostKey();
  const url = "wss://linux.tailnet.ts.net/ws";
  const host = await pairingHost(url, () => ({
    t: "paired",
    device_id: "dev_x",
    host_id: "host_linux",
    host_pubkey: swapped.pubkey,
    scope: "owner",
  }));
  const store = await memoryStore();
  try {
    await expect(
      pairDevice({
        url,
        ticket: "ABCD2345",
        deviceName: "Phone",
        store,
        expectedFp: real.fp,
      }),
    ).rejects.toBeInstanceOf(HostIdentityChanged as ErrorClass);
    expect(await store.list()).toEqual([]);
  } finally {
    host.stop();
  }
});

test("a LAN ws:// URL is refused before any socket opens", async () => {
  const { pairDevice } = await load<Pairing>(pairingPath);
  const { DirectUrlRefused } =
    await load<Record<string, ErrorClass>>(errorsPath);
  const dialled: string[] = [];
  vi.stubGlobal(
    "WebSocket",
    class {
      constructor(url: string) {
        dialled.push(url);
        throw new Error("must not dial");
      }
    },
  );
  const store = await memoryStore();
  const error = await pairDevice({
    url: "ws://192.168.1.20:8787/ws",
    ticket: "ABCD2345",
    deviceName: "Phone",
    store,
  }).then(
    () => null,
    (reason: unknown) => reason,
  );
  expect(error).toBeInstanceOf(DirectUrlRefused as ErrorClass);
  expect((error as { reason?: string }).reason).toBe("not_private");
  expect(dialled).toEqual([]);
  expect(await store.list()).toEqual([]);
});

test("a dial blocked by CSP reports the origin to add to connect_src", async () => {
  const { pairDevice } = await load<Pairing>(pairingPath);
  const { CspBlocked } = await load<Record<string, ErrorClass>>(errorsPath);
  vi.stubGlobal(
    "WebSocket",
    class {
      constructor() {
        throw new DOMException("Refused to connect", "SecurityError");
      }
    },
  );
  const store = await memoryStore();
  const error = await pairDevice({
    url: "wss://linux.tailnet.ts.net/ws",
    ticket: "ABCD2345",
    deviceName: "Phone",
    store,
  }).then(
    () => null,
    (reason: unknown) => reason,
  );
  expect(error).toBeInstanceOf(CspBlocked as ErrorClass);
  expect((error as { origin?: string }).origin).toBe(
    "wss://linux.tailnet.ts.net",
  );
});

test("a refused ticket rejects Unauthorized and stores nothing", async () => {
  const { pairDevice } = await load<Pairing>(pairingPath);
  const { Unauthorized } = await load<Record<string, ErrorClass>>(errorsPath);
  const url = "wss://linux.tailnet.ts.net/ws";
  const host = await pairingHost(url, () => "unauthorized");
  const store = await memoryStore();
  try {
    await expect(
      pairDevice({ url, ticket: "WRONG000", deviceName: "Phone", store }),
    ).rejects.toBeInstanceOf(Unauthorized as ErrorClass);
    expect(await store.list()).toEqual([]);
  } finally {
    host.stop();
  }
});

test("the paired host id must match the QR even when the fingerprint matches", async () => {
  const { pairDevice } = await load<Pairing>(pairingPath);
  const key = await newHostKey();
  const url = "wss://linux.tailnet.ts.net/ws";
  const host = await pairingHost(url, () => ({
    t: "paired",
    device_id: "dev_new",
    host_id: "host_wrong",
    host_pubkey: key.pubkey,
    scope: "member",
  }));
  const store = await memoryStore();
  try {
    await expect(
      pairDevice({
        url,
        ticket: "ABCD2345",
        deviceName: "Phone",
        store,
        expectedFp: key.fp,
        expectedHostId: "host_linux",
      }),
    ).rejects.toThrow("Host identity changed");
    expect(await store.list()).toEqual([]);
  } finally {
    host.stop();
  }
});

test.each(["origin", "key"])(
  "pairing cannot overwrite a known host id with a different %s",
  async (changed) => {
    const { pairDevice } = await load<Pairing>(pairingPath);
    const key = await newHostKey();
    const { profile } = await makeProfile(
      { host_id: "host_linux", direct_url: "wss://known.example/ws" },
      key,
    );
    const url =
      changed === "origin" ? "wss://other.example/ws" : profile.direct_url;
    const returned = changed === "key" ? await newHostKey() : key;
    const host = await pairingHost(url, () => ({
      t: "paired",
      device_id: "dev_new",
      host_id: profile.host_id,
      host_pubkey: returned.pubkey,
      scope: "owner",
    }));
    const store = await memoryStore();
    await store.put(profile);
    try {
      await expect(
        pairDevice({ url, ticket: "ABCD2345", deviceName: "Phone", store }),
      ).rejects.toMatchObject({
        name: "HostIdentityChanged",
        message:
          "Host identity conflicts with an existing profile; forget that profile before replacing it",
      });
      expect(await store.list()).toEqual([profile]);
    } finally {
      host.stop();
    }
  },
);

test.each([
  "ws://localhost:8787/ws",
  "ws://127.0.0.1/ws",
  "ws://[::1]/ws",
  "wss://[::ffff:127.0.0.1]/ws",
])(
  "a native loopback pairing refusal at %s explains how to log in",
  async (url) => {
    const mock = await stubSockets();
    const server = new mock.Server(url);
    server.on("connection", (socket) => {
      socket.on("message", (data) => {
        if ((JSON.parse(String(data)) as Frame).t === "pair.complete") {
          socket.close({ code: 1002, reason: "protocol error" });
        }
      });
    });
    try {
      const pairing = await load<Pairing>(pairingPath);
      const store = await memoryStore();
      await expect(
        pairing.pairDevice({
          url,
          ticket: "code",
          deviceName: "Browser",
          store,
        }),
      ).rejects.toThrow("sevn serve --open");
      expect(await store.list()).toEqual([]);
    } finally {
      server.stop();
    }
  },
);
