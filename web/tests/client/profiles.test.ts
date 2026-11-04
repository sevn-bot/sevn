import { afterEach, expect, test, vi } from "vitest";
import {
  directHost,
  type HostProfile,
  makeProfile,
  newHostKey,
  stubSockets,
} from "../support/direct.ts";

/**
 * Plan 0055 D6: host profiles, device keys and the pinned host key.
 *
 * Pinned in `web/src/client/profiles.ts`:
 * - `type ProfileStore = { get(hostId), put(profile), delete(hostId), list() }` (all async);
 *   `memoryProfileStore()` for tests, `openProfileStore()` = IndexedDB `sevn` / `profiles`.
 * - `saveProfile(store, profile)` refuses an extractable `device_key` (message names "extractable").
 * - `loadProfile(store, hostId)`, `listProfiles(store)`.
 * - `deleteProfile(store, hostId, { revoke })`: calls `revoke(profile)` first, deletes even
 *   when the host is unreachable (`revoke` rejects).
 * Pinned in `web/src/client/keys.ts`: `generateDeviceKey(): Promise<CryptoKeyPair>`.
 * Pinned in `web/src/client/connection.ts`: `connect({ url, lastSeq?, device })` with
 * `device = { id, key, hostPubkey, hostFp }`; a bad `host_sig` rejects `HostIdentityChanged`
 * (`web/src/client/errors.ts`), message "Host identity changed — re-pair to continue".
 */
type ProfileStore = {
  get: (hostId: string) => Promise<HostProfile | undefined>;
  put: (profile: HostProfile) => Promise<void>;
  delete: (hostId: string) => Promise<void>;
  list: () => Promise<HostProfile[]>;
};

type Profiles = {
  memoryProfileStore: () => ProfileStore;
  saveProfile: (store: ProfileStore, profile: HostProfile) => Promise<void>;
  loadProfile: (
    store: ProfileStore,
    hostId: string,
  ) => Promise<HostProfile | undefined>;
  listProfiles: (store: ProfileStore) => Promise<HostProfile[]>;
  deleteProfile: (
    store: ProfileStore,
    hostId: string,
    options: { revoke: (profile: HostProfile) => Promise<void> },
  ) => Promise<void>;
};

type Keys = { generateDeviceKey: () => Promise<CryptoKeyPair> };

type Connect = (options: {
  url: string;
  lastSeq?: number;
  device?: { id: string; key: CryptoKey; hostPubkey: string; hostFp: string };
}) => Promise<{ close: () => void }>;

async function load<T>(specifier: string): Promise<T> {
  return (await import(specifier)) as T;
}

const profilesPath = "../../src/client/profiles.ts";
const keysPath = "../../src/client/keys.ts";
const clientPath = "../../src/client/index.ts";
const errorsPath = "../../src/client/errors.ts";

afterEach(() => {
  vi.unstubAllGlobals();
});

test("profiles store and load with every D6 field", async () => {
  const profiles = await load<Profiles>(profilesPath);
  const store = profiles.memoryProfileStore();
  const { profile: mac } = await makeProfile({
    host_id: "host_mac",
    name: "Mac mini",
    direct_url: "wss://mac.tailnet.ts.net/ws",
    scope: "owner",
  });
  const { profile: linux } = await makeProfile({
    host_id: "host_linux",
    name: "Omarchy",
    direct_url: "ws://100.101.102.103:8787/ws",
    private_networks: ["100.64.0.0/10"],
  });
  await profiles.saveProfile(store, mac);
  await profiles.saveProfile(store, linux);
  const loaded = await profiles.loadProfile(store, "host_mac");
  expect(loaded).toEqual(mac);
  expect(loaded?.device_key).toBe(mac.device_key);
  const listed = await profiles.listProfiles(store);
  expect(listed.map((item) => item.host_id).sort()).toEqual([
    "host_linux",
    "host_mac",
  ]);
  expect(await profiles.loadProfile(store, "host_missing")).toBeUndefined();
});

test("device keys are Ed25519 and the private key never exports", async () => {
  const keys = await load<Keys>(keysPath);
  const pair = await keys.generateDeviceKey();
  expect(pair.privateKey.algorithm.name).toBe("Ed25519");
  expect(pair.privateKey.extractable).toBe(false);
  for (const format of ["pkcs8", "jwk", "raw"] as const) {
    await expect(
      crypto.subtle.exportKey(format, pair.privateKey),
    ).rejects.toThrow();
  }
  const raw = new Uint8Array(
    await crypto.subtle.exportKey("raw", pair.publicKey),
  );
  expect(raw.length).toBe(32);
  const signature = await crypto.subtle.sign(
    { name: "Ed25519" },
    pair.privateKey,
    new Uint8Array([1, 2, 3]),
  );
  expect(signature.byteLength).toBe(64);
  const other = await keys.generateDeviceKey();
  expect(
    new Uint8Array(await crypto.subtle.exportKey("raw", other.publicKey)),
  ).not.toEqual(raw);
});

test("a profile with an extractable device key is refused", async () => {
  const profiles = await load<Profiles>(profilesPath);
  const store = profiles.memoryProfileStore();
  const extractable = (await crypto.subtle.generateKey(
    { name: "Ed25519" },
    true,
    ["sign", "verify"],
  )) as CryptoKeyPair;
  const { profile } = await makeProfile({
    host_id: "host_mac",
    direct_url: "wss://mac.tailnet.ts.net/ws",
    device_key: extractable.privateKey,
  });
  await expect(profiles.saveProfile(store, profile)).rejects.toThrow(
    /extractable/,
  );
  expect(await store.list()).toEqual([]);
});

test("a challenge signed by another host key is a hard error with no auth sent", async () => {
  const mock = await stubSockets();
  const { connect } = await load<{ connect: Connect }>(clientPath);
  const { HostIdentityChanged } = await load<{
    HostIdentityChanged: new () => Error;
  }>(errorsPath);
  const pinned = await newHostKey();
  const impostor = await newHostKey();
  const url = "ws://100.101.102.103:8787/ws";
  const { profile, devicePubkey } = await makeProfile(
    { host_id: "host_linux", direct_url: url },
    pinned,
  );
  const host = await directHost(mock, {
    url,
    hostId: "host_linux",
    key: pinned,
    devicePubkey,
    signWith: impostor.pair.privateKey,
  });
  try {
    const attempt = connect({
      url,
      device: {
        id: profile.device_id,
        key: profile.device_key,
        hostPubkey: profile.host_pubkey,
        hostFp: profile.host_pubkey_fp,
      },
    });
    const error = await attempt.then(
      () => null,
      (reason: unknown) => reason,
    );
    expect(error).toBeInstanceOf(HostIdentityChanged);
    expect((error as Error).message).toBe(
      "Host identity changed — re-pair to continue",
    );
    const sent = host.connections.flat();
    expect(sent.some((frame) => frame.t === "auth")).toBe(false);
    await new Promise((resolve) => setTimeout(resolve, 1200));
    // A hard error: no silent re-pin and no reconnect loop.
    expect(host.connections.length).toBe(1);
  } finally {
    host.stop();
  }
});

test("connect answers the challenge with the device key and the dialled origin", async () => {
  const mock = await stubSockets();
  const { connect } = await load<{ connect: Connect }>(clientPath);
  const key = await newHostKey();
  const url = "ws://100.101.102.103:8787/ws";
  const { profile, devicePubkey } = await makeProfile(
    { host_id: "host_linux", direct_url: url },
    key,
  );
  const host = await directHost(mock, {
    url,
    hostId: "host_linux",
    key,
    devicePubkey,
  });
  try {
    const connection = await connect({
      url,
      device: {
        id: profile.device_id,
        key: profile.device_key,
        hostPubkey: profile.host_pubkey,
        hostFp: profile.host_pubkey_fp,
      },
    });
    const frames = host.connections[0] ?? [];
    const hello = frames.find((frame) => frame.t === "hello");
    expect(hello?.device).toBe(profile.device_id);
    expect(hello?.origin).toBe("ws://100.101.102.103:8787");
    const auth = frames.find((frame) => frame.t === "auth");
    expect(typeof auth?.device_sig).toBe("string");
    expect(auth && "token" in auth).toBe(false);
    connection.close();
  } finally {
    host.stop();
  }
});

test("deleting a profile revokes the device on that host first", async () => {
  const profiles = await load<Profiles>(profilesPath);
  const store = profiles.memoryProfileStore();
  const { profile } = await makeProfile({
    host_id: "host_linux",
    direct_url: "wss://linux.tailnet.ts.net/ws",
  });
  await profiles.saveProfile(store, profile);
  const order: string[] = [];
  await profiles.deleteProfile(store, "host_linux", {
    revoke: async (target) => {
      order.push(`revoke:${target.device_id}`);
      expect(await store.get("host_linux")).toBeDefined();
    },
  });
  order.push("deleted");
  expect(order).toEqual([`revoke:${profile.device_id}`, "deleted"]);
  expect(await store.get("host_linux")).toBeUndefined();
});

test("deleting a profile of an unreachable host still deletes it", async () => {
  const profiles = await load<Profiles>(profilesPath);
  const store = profiles.memoryProfileStore();
  const { profile } = await makeProfile({
    host_id: "host_gone",
    direct_url: "wss://gone.tailnet.ts.net/ws",
  });
  await profiles.saveProfile(store, profile);
  let tried = 0;
  await profiles.deleteProfile(store, "host_gone", {
    revoke: () => {
      tried += 1;
      return Promise.reject(new Error("not connected"));
    },
  });
  expect(tried).toBe(1);
  expect(await store.get("host_gone")).toBeUndefined();
});

test("a device connection refuses a welcome that skipped the challenge", async () => {
  const mock = await stubSockets();
  const { connect } = await load<{ connect: Connect }>(clientPath);
  const url = "ws://100.101.102.103:8787/ws";
  const { profile } = await makeProfile({
    host_id: "host_linux",
    direct_url: url,
  });
  const server = new mock.Server(url);
  server.on("connection", (socket) => {
    socket.on("message", (data) => {
      if ((JSON.parse(String(data)) as { t?: string }).t === "hello") {
        socket.send(
          JSON.stringify({ t: "welcome", proto: 1, host_seq: 0, caps: [] }),
        );
      }
    });
  });
  try {
    await expect(
      connect({
        url,
        device: {
          id: profile.device_id,
          key: profile.device_key,
          hostPubkey: profile.host_pubkey,
          hostFp: profile.host_pubkey_fp,
        },
      }),
    ).rejects.toThrow("Host identity changed");
  } finally {
    server.stop();
  }
});
