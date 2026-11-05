/**
 * Plan 0055 test helpers: D3 handshake bytes, vectors, and a mock direct host.
 *
 * This file is an independent reference built on WebCrypto only. It never imports
 * product code, so a test does not check the client against itself.
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { vi } from "vitest";

export type Frame = Record<string, unknown>;

export type VectorCase = {
  name: string;
  nonce: string;
  origin: string;
  origin_sha256_hex: string;
  challenge_message_hex: string;
  auth_message_hex: string;
  host_sig: string;
  device_sig: string;
};

export type Vectors = {
  host: {
    seed_hex: string;
    pubkey: string;
    pubkey_fp: string;
    host_id: string;
  };
  device: { seed_hex: string; pubkey: string };
  cases: VectorCase[];
};

export function loadVectors(): Vectors {
  const file = path.resolve(
    import.meta.dirname,
    "../../../contracts/vectors/handshake_ws.json",
  );
  return JSON.parse(readFileSync(file, "utf8")) as Vectors;
}

export function b64u(bytes: Uint8Array): string {
  let text = "";
  for (const byte of bytes) {
    text += String.fromCharCode(byte);
  }
  return btoa(text)
    .replaceAll("+", "-")
    .replaceAll("/", "_")
    .replace(/=+$/, "");
}

export function unb64u(text: string): Uint8Array {
  const padded = text.replaceAll("-", "+").replaceAll("_", "/");
  const raw = atob(padded + "=".repeat((4 - (padded.length % 4)) % 4));
  return Uint8Array.from(raw, (char) => char.charCodeAt(0));
}

export function hex(bytes: Uint8Array): string {
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join(
    "",
  );
}

export function fromHex(text: string): Uint8Array {
  const out = new Uint8Array(text.length / 2);
  for (let index = 0; index < out.length; index += 1) {
    out[index] = Number.parseInt(text.slice(index * 2, index * 2 + 2), 16);
  }
  return out;
}

function concat(...parts: Uint8Array[]): Uint8Array {
  const total = parts.reduce((sum, part) => sum + part.length, 0);
  const out = new Uint8Array(total);
  let offset = 0;
  for (const part of parts) {
    out.set(part, offset);
    offset += part.length;
  }
  return out;
}

const encoder = new TextEncoder();

async function sha256(bytes: Uint8Array): Promise<Uint8Array> {
  return new Uint8Array(await crypto.subtle.digest("SHA-256", bytes));
}

export async function challengeBytes(
  nonce: Uint8Array,
  origin: string,
): Promise<Uint8Array> {
  return concat(
    encoder.encode("sevn-v1|chal|ws|"),
    nonce,
    await sha256(encoder.encode(origin)),
  );
}

export async function authBytes(
  nonce: Uint8Array,
  origin: string,
  hostFp: string,
): Promise<Uint8Array> {
  return concat(
    encoder.encode("sevn-v1|auth|ws|"),
    nonce,
    await sha256(encoder.encode(origin)),
    encoder.encode(hostFp),
  );
}

export async function fingerprintOf(pubkey: Uint8Array): Promise<string> {
  return b64u((await sha256(pubkey)).slice(0, 16));
}

/** Import an Ed25519 seed as a non-extractable signing key (JWK `d` + `x`). */
export async function importSeed(
  seedHex: string,
  pubkey: string,
): Promise<CryptoKey> {
  return crypto.subtle.importKey(
    "jwk",
    { kty: "OKP", crv: "Ed25519", d: b64u(fromHex(seedHex)), x: pubkey },
    { name: "Ed25519" },
    false,
    ["sign"],
  );
}

export type HostKey = {
  pair: CryptoKeyPair;
  pubkey: string;
  fp: string;
};

export async function newHostKey(): Promise<HostKey> {
  const pair = (await crypto.subtle.generateKey({ name: "Ed25519" }, true, [
    "sign",
    "verify",
  ])) as CryptoKeyPair;
  const raw = new Uint8Array(
    await crypto.subtle.exportKey("raw", pair.publicKey),
  );
  return { pair, pubkey: b64u(raw), fp: await fingerprintOf(raw) };
}

/** A device key as the product must make it: Ed25519, private half not extractable. */
export async function newDeviceKey(): Promise<{
  pair: CryptoKeyPair;
  pubkey: string;
}> {
  const pair = (await crypto.subtle.generateKey({ name: "Ed25519" }, false, [
    "sign",
    "verify",
  ])) as CryptoKeyPair;
  const raw = new Uint8Array(
    await crypto.subtle.exportKey("raw", pair.publicKey),
  );
  return { pair, pubkey: b64u(raw) };
}

export type HostProfile = {
  host_id: string;
  name: string;
  host_pubkey: string;
  host_pubkey_fp: string;
  transport: "direct";
  direct_url: string;
  private_networks?: string[];
  allow_plain_ws: boolean;
  device_id: string;
  device_key: CryptoKey;
  scope: "owner" | "member" | "read_only";
};

export async function makeProfile(
  overrides: Partial<HostProfile> & { host_id: string; direct_url: string },
  host?: HostKey,
): Promise<{ profile: HostProfile; devicePubkey: string }> {
  const key = host ?? (await newHostKey());
  const device = await newDeviceKey();
  return {
    profile: {
      name: overrides.host_id,
      host_pubkey: key.pubkey,
      host_pubkey_fp: key.fp,
      transport: "direct",
      allow_plain_ws: false,
      device_id: `dev_${overrides.host_id}`,
      device_key: device.pair.privateKey,
      scope: "member",
      ...overrides,
    },
    devicePubkey: device.pubkey,
  };
}

type MockSocket = {
  on: (event: "message", handler: (data: unknown) => void) => void;
  send: (data: string) => void;
  close: (options?: { code?: number; reason?: string }) => void;
};

type MockServer = {
  on: (event: "connection", handler: (socket: MockSocket) => void) => void;
  stop: () => void;
};

type MockModule = {
  Server: new (address: string) => MockServer;
  WebSocket: unknown;
};

export async function stubSockets(): Promise<MockModule> {
  const name = "mock-socket";
  const mock = (await import(name)) as MockModule;
  vi.stubGlobal("WebSocket", mock.WebSocket);
  return mock;
}

export type DirectHost = {
  hostId: string;
  /** Every frame each connection sent, in order; one entry per connection. */
  connections: Frame[][];
  /** Close the newest connection from the host side. */
  drop: (code?: number, reason?: string) => void;
  /** Send an `evt` on the newest authenticated connection. */
  event: (seq: number, kind: string, data?: Record<string, unknown>) => void;
  stop: () => void;
};

/**
 * A mock sevn host speaking D3: `challenge` after `hello`, verifies `auth`, then `welcome`.
 * `signWith` lets a test sign the challenge with a key other than the pinned one.
 */
export async function directHost(
  mock: MockModule,
  options: {
    url: string;
    hostId: string;
    key: HostKey;
    devicePubkey: string;
    hostSeq?: number;
    signWith?: CryptoKey;
    /** Result objects by method name (default `{}`); `sync.since` has its own default. */
    replies?: Record<string, Record<string, unknown>>;
  },
): Promise<DirectHost> {
  const server = new mock.Server(options.url);
  const origin = new URL(options.url).origin;
  const connections: Frame[][] = [];
  const sockets: MockSocket[] = [];
  let ready: MockSocket | null = null;
  server.on("connection", (socket) => {
    const frames: Frame[] = [];
    connections.push(frames);
    sockets.push(socket);
    const nonce = crypto.getRandomValues(new Uint8Array(32));
    socket.on("message", (data) => {
      const frame = JSON.parse(String(data)) as Frame;
      frames.push(frame);
      void respond(socket, frame, nonce);
    });
  });

  async function respond(
    socket: MockSocket,
    frame: Frame,
    nonce: Uint8Array,
  ): Promise<void> {
    if (frame.t === "hello") {
      const signer = options.signWith ?? options.key.pair.privateKey;
      const sig = new Uint8Array(
        await crypto.subtle.sign(
          { name: "Ed25519" },
          signer,
          await challengeBytes(nonce, origin),
        ),
      );
      socket.send(
        JSON.stringify({
          t: "challenge",
          nonce: b64u(nonce),
          host: options.hostId,
          host_sig: b64u(sig),
        }),
      );
      return;
    }
    if (frame.t === "auth" && typeof frame.device_sig === "string") {
      const device = await crypto.subtle.importKey(
        "raw",
        unb64u(options.devicePubkey),
        { name: "Ed25519" },
        true,
        ["verify"],
      );
      const ok = await crypto.subtle.verify(
        { name: "Ed25519" },
        device,
        unb64u(frame.device_sig),
        await authBytes(nonce, origin, options.key.fp),
      );
      if (!ok) {
        socket.close({ code: 4001, reason: "unauthorized" });
        return;
      }
      ready = socket;
      socket.send(
        JSON.stringify({
          t: "welcome",
          proto: 1,
          host_seq: options.hostSeq ?? 0,
          caps: [],
        }),
      );
      return;
    }
    if (frame.t === "req") {
      const method = String(frame.m);
      const result =
        options.replies?.[method] ??
        (method === "sync.since"
          ? {
              host_seq: options.hostSeq ?? 0,
              next_seq: options.hostSeq ?? 0,
              more: false,
            }
          : {});
      socket.send(JSON.stringify({ t: "res", id: frame.id, r: result }));
    }
  }

  return {
    hostId: options.hostId,
    connections,
    drop(code = 1012, reason = "restart") {
      sockets.at(-1)?.close({ code, reason });
    },
    event(seq, kind, data = {}) {
      ready?.send(JSON.stringify({ t: "evt", s: seq, k: kind, d: data }));
    },
    stop() {
      server.stop();
    },
  };
}

export async function until(
  check: () => boolean,
  timeoutMs = 3000,
): Promise<void> {
  const started = Date.now();
  while (!check()) {
    if (Date.now() - started > timeoutMs) {
      throw new Error("condition not met in time");
    }
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
}
