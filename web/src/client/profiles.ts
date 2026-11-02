/**
 * Host profiles (plan 0055 D6) and the client-side network check (D7).
 *
 * A profile pins one host: its id, public key and fingerprint, the direct URL, and this
 * browser's device id and non-extractable Ed25519 key for that host. Profiles live in the
 * IndexedDB store `sevn` / `profiles`; the CryptoKey is stored as-is (structured clone), so
 * the private key never leaves the browser's key store.
 */
import type { DirectUrlReason } from "./errors.ts";

export type { DirectUrlReason } from "./errors.ts";

export type DeviceScope = "owner" | "member" | "read_only";

export type HostProfile = {
  host_id: string;
  name: string;
  /** The host's raw Ed25519 public key (base64url); verifies `challenge.host_sig`. */
  host_pubkey: string;
  host_pubkey_fp: string;
  transport: "direct";
  direct_url: string;
  /** CIDR ranges a `ws://` URL may point into; replaces the default when present. */
  private_networks?: string[];
  allow_plain_ws: boolean;
  device_id: string;
  /** Non-extractable Ed25519 private key, one per host. */
  device_key: CryptoKey;
  scope: DeviceScope;
};

export type ProfileStore = {
  get: (hostId: string) => Promise<HostProfile | undefined>;
  put: (profile: HostProfile) => Promise<void>;
  delete: (hostId: string) => Promise<void>;
  list: () => Promise<HostProfile[]>;
};

/** Tailscale and Headscale address ranges (CGNAT v4, the Tailscale ULA v6). */
export const DEFAULT_PRIVATE_NETWORKS: readonly string[] = Object.freeze([
  "100.64.0.0/10",
  "fd7a:115c:a1e0::/48",
]);

export type DirectUrlCheck =
  | { ok: true }
  | { ok: false; reason: DirectUrlReason };

export type DirectUrlOptions = {
  private_networks?: readonly string[];
  allow_plain_ws?: boolean;
};

/**
 * D7: accept `wss://`, `ws://` to a loopback address, `ws://` to an IP inside the profile's
 * private networks, or any `ws://` when `allow_plain_ws` is on. A `ws://` hostname is
 * resolved by the browser, so it needs `allow_plain_ws`. Never throws.
 */
export function checkDirectUrl(
  url: string,
  options: DirectUrlOptions = {},
): DirectUrlCheck {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return { ok: false, reason: "scheme" };
  }
  if (parsed.protocol === "wss:") {
    return { ok: true };
  }
  if (parsed.protocol !== "ws:") {
    return { ok: false, reason: "scheme" };
  }
  const host = parsed.hostname;
  // Browsers resolve `localhost` to loopback without asking DNS.
  if (host === "localhost") {
    return { ok: true };
  }
  const address = parseAddress(host);
  if (address !== null && isLoopback(address)) {
    return { ok: true };
  }
  if (options.allow_plain_ws === true) {
    return { ok: true };
  }
  if (address === null) {
    return { ok: false, reason: "hostname_over_ws" };
  }
  const networks = options.private_networks ?? DEFAULT_PRIVATE_NETWORKS;
  for (const network of networks) {
    if (inNetwork(address, network)) {
      return { ok: true };
    }
  }
  return { ok: false, reason: "not_private" };
}

/** A profile store in memory (tests, and browsers without IndexedDB). */
export function memoryProfileStore(): ProfileStore {
  const rows = new Map<string, HostProfile>();
  return {
    get: (hostId) => Promise.resolve(rows.get(hostId)),
    put: (profile) => {
      rows.set(profile.host_id, profile);
      return Promise.resolve();
    },
    delete: (hostId) => {
      rows.delete(hostId);
      return Promise.resolve();
    },
    list: () => Promise.resolve([...rows.values()]),
  };
}

const DB_NAME = "sevn";
const DB_VERSION = 1;
const STORE = "profiles";

/** The IndexedDB profile store (`sevn` / `profiles`, keyed by `host_id`), opened on first use. */
export function openProfileStore(
  factory: IDBFactory = indexedDB,
): ProfileStore {
  let opening: Promise<IDBDatabase> | null = null;
  const database = (): Promise<IDBDatabase> => {
    opening ??= new Promise<IDBDatabase>((resolve, reject) => {
      const request = factory.open(DB_NAME, DB_VERSION);
      request.onupgradeneeded = () => {
        const db = request.result;
        if (!db.objectStoreNames.contains(STORE)) {
          db.createObjectStore(STORE, { keyPath: "host_id" });
        }
      };
      request.onsuccess = () => {
        resolve(request.result);
      };
      request.onerror = () => {
        opening = null;
        reject(request.error ?? new Error("indexedDB open failed"));
      };
    });
    return opening;
  };
  async function run<T>(
    mode: IDBTransactionMode,
    action: (store: IDBObjectStore) => IDBRequest,
  ): Promise<T> {
    const db = await database();
    return new Promise<T>((resolve, reject) => {
      const transaction = db.transaction(STORE, mode);
      const request = action(transaction.objectStore(STORE));
      transaction.oncomplete = () => {
        resolve(request.result as T);
      };
      transaction.onerror = () => {
        reject(transaction.error ?? new Error("indexedDB request failed"));
      };
      transaction.onabort = () => {
        reject(transaction.error ?? new Error("indexedDB transaction aborted"));
      };
    });
  }
  return {
    get: (hostId) =>
      run<HostProfile | undefined>("readonly", (store) => store.get(hostId)),
    put: async (profile) => {
      await run("readwrite", (store) => store.put(profile));
    },
    delete: async (hostId) => {
      await run("readwrite", (store) => store.delete(hostId));
    },
    list: () => run<HostProfile[]>("readonly", (store) => store.getAll()),
  };
}

/** Store a profile. Refuses a device key that is extractable or not an Ed25519 private key. */
export async function saveProfile(
  store: ProfileStore,
  profile: HostProfile,
): Promise<void> {
  const key = profile.device_key;
  if (key.extractable) {
    throw new Error("device_key must not be extractable");
  }
  if (key.type !== "private" || key.algorithm.name !== "Ed25519") {
    throw new Error("device_key must be an Ed25519 private key");
  }
  await store.put(profile);
}

export function loadProfile(
  store: ProfileStore,
  hostId: string,
): Promise<HostProfile | undefined> {
  return store.get(hostId);
}

export function listProfiles(store: ProfileStore): Promise<HostProfile[]> {
  return store.list();
}

/**
 * Delete a profile, revoking this device on its host first (`devices.revoke`). An
 * unreachable host does not keep the profile: the revoke is attempted once, then the
 * profile is deleted either way.
 */
export async function deleteProfile(
  store: ProfileStore,
  hostId: string,
  options: { revoke: (profile: HostProfile) => Promise<void> },
): Promise<void> {
  const profile = await store.get(hostId);
  if (profile === undefined) {
    return;
  }
  try {
    await options.revoke(profile);
  } catch {
    // The host is unreachable or refused; the owner can still revoke from the host.
  }
  await store.delete(hostId);
}

type Address = { v6: boolean; bytes: number[] };

function parseIpv4(text: string): number[] | null {
  const parts = text.split(".");
  if (parts.length !== 4) {
    return null;
  }
  const bytes: number[] = [];
  for (const part of parts) {
    if (!/^\d{1,3}$/.test(part)) {
      return null;
    }
    const value = Number(part);
    if (value > 255) {
      return null;
    }
    bytes.push(value);
  }
  return bytes;
}

function parseIpv6(input: string): number[] | null {
  let text = input.toLowerCase();
  const lastColon = text.lastIndexOf(":");
  if (lastColon < 0) {
    return null;
  }
  const tail = text.slice(lastColon + 1);
  if (tail.includes(".")) {
    const v4 = parseIpv4(tail);
    if (v4 === null) {
      return null;
    }
    const [a = 0, b = 0, c = 0, d = 0] = v4;
    const high = ((a << 8) | b).toString(16);
    const low = ((c << 8) | d).toString(16);
    text = `${text.slice(0, lastColon + 1)}${high}:${low}`;
  }
  const halves = text.split("::");
  if (halves.length > 2) {
    return null;
  }
  const groupsOf = (part: string | undefined): string[] =>
    part === undefined || part === "" ? [] : part.split(":");
  const left = groupsOf(halves[0]);
  const right = groupsOf(halves[1]);
  const compressed = halves.length === 2;
  const missing = 8 - left.length - right.length;
  if (compressed ? missing < 1 : missing !== 0) {
    return null;
  }
  const groups = [...left, ...Array<string>(missing).fill("0"), ...right];
  const bytes: number[] = [];
  for (const group of groups) {
    if (!/^[0-9a-f]{1,4}$/.test(group)) {
      return null;
    }
    const value = Number.parseInt(group, 16);
    bytes.push(value >> 8, value & 0xff);
  }
  return bytes;
}

/** An IP literal as the URL parser prints it (`[v6]` bracketed), or null for a hostname. */
function parseAddress(host: string): Address | null {
  const literal =
    host.startsWith("[") && host.endsWith("]") ? host.slice(1, -1) : host;
  if (literal.includes(":")) {
    const bytes = parseIpv6(literal);
    if (bytes === null) {
      return null;
    }
    // IPv4-mapped (::ffff:a.b.c.d) is checked as the IPv4 address it carries.
    const mapped =
      bytes.slice(0, 10).every((byte) => byte === 0) &&
      bytes[10] === 0xff &&
      bytes[11] === 0xff;
    return mapped ? { v6: false, bytes: bytes.slice(12) } : { v6: true, bytes };
  }
  const bytes = parseIpv4(literal);
  return bytes === null ? null : { v6: false, bytes };
}

function isLoopback(address: Address): boolean {
  if (!address.v6) {
    return address.bytes[0] === 127;
  }
  return address.bytes.every((byte, index) => byte === (index === 15 ? 1 : 0));
}

/** Whether `address` is inside the CIDR `network`; a malformed entry matches nothing. */
function inNetwork(address: Address, network: string): boolean {
  const [base, prefixText, ...rest] = network.trim().split("/");
  if (base === undefined || rest.length > 0) {
    return false;
  }
  const range = parseAddress(base);
  if (range === null || range.v6 !== address.v6) {
    return false;
  }
  const bits = range.bytes.length * 8;
  const prefix = prefixText === undefined ? bits : Number(prefixText);
  if (prefixText !== undefined && !/^\d{1,3}$/.test(prefixText)) {
    return false;
  }
  if (!Number.isInteger(prefix) || prefix < 0 || prefix > bits) {
    return false;
  }
  for (let bit = 0; bit < prefix; bit += 8) {
    const index = bit / 8;
    const width = Math.min(8, prefix - bit);
    const mask = (0xff << (8 - width)) & 0xff;
    if (
      ((address.bytes[index] ?? 0) & mask) !==
      ((range.bytes[index] ?? 0) & mask)
    ) {
      return false;
    }
  }
  return true;
}
