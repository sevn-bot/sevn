/**
 * The device side of pairing (plan 0055 D1, D6, D7, D8).
 *
 * A device reads a `sevn://pair` link (QR) or takes a host address plus a short code, makes
 * its own non-extractable Ed25519 key for that host, and proves the one-time ticket over a
 * direct WebSocket: `hello`, then `pair.complete`. The host answers `paired` and closes; the
 * profile is stored only then, and the device reconnects with the D3 handshake.
 */
import {
  CspBlocked,
  DirectUrlRefused,
  HostIdentityChanged,
  Unauthorized,
} from "./errors.ts";
import { exportPublicKey, fingerprint, generateDeviceKey } from "./keys.ts";
import {
  checkDirectUrl,
  type DeviceScope,
  type HostProfile,
  type ProfileStore,
  saveProfile,
} from "./profiles.ts";

export type PairLink = {
  host_id: string;
  host_pubkey_fp: string;
  ticket: string;
  direct_url: string | null;
};

const NOT_A_LINK = "not a sevn pairing link";

/** Read `sevn://pair?h=<host_id>&k=<host_pubkey_fp>&t=<ticket>[&d=<direct_url>]`. */
export function parsePairUri(uri: string): PairLink {
  let parsed: URL;
  try {
    parsed = new URL(uri.trim());
  } catch {
    throw new Error(NOT_A_LINK);
  }
  // `sevn:` is not a special scheme, so `pair` is the host of an opaque-host URL.
  if (parsed.protocol !== "sevn:" || parsed.hostname !== "pair") {
    throw new Error(NOT_A_LINK);
  }
  const params = parsed.searchParams;
  const hostId = params.get("h");
  const fp = params.get("k");
  const ticket = params.get("t");
  if (hostId === null || fp === null || ticket === null) {
    throw new Error(NOT_A_LINK);
  }
  if (hostId === "" || fp === "" || ticket === "") {
    throw new Error(NOT_A_LINK);
  }
  const direct = params.get("d");
  return {
    host_id: hostId,
    host_pubkey_fp: fp,
    ticket,
    direct_url: direct === null || direct === "" ? null : direct,
  };
}

export type PairOptions = {
  /** The host's direct WebSocket URL (`wss://mac.tailnet.ts.net/ws`). */
  url: string;
  /** The full ticket from the QR, or the 8-character short code. */
  ticket: string;
  deviceName: string;
  platform?: string;
  store: ProfileStore;
  /** The QR's `k=`: the paired host's key must have this fingerprint. */
  expectedFp?: string;
  /** The QR's `h=`: the paired host must have this identity. */
  expectedHostId?: string;
  allowPlainWs?: boolean;
  privateNetworks?: string[];
  /** How long to wait for `paired` (default 15 s). */
  timeoutMs?: number;
};

const SCOPES: ReadonlySet<string> = new Set(["owner", "member", "read_only"]);
const DEFAULT_TIMEOUT_MS = 15_000;

type PairedFrame = {
  device_id: string;
  host_id: string;
  host_pubkey: string;
  scope: DeviceScope;
};

/**
 * Pair this browser with a host and store the profile. Runs the D7 check before any socket
 * opens. Rejects `DirectUrlRefused`, `CspBlocked`, `Unauthorized` (ticket refused),
 * `HostIdentityChanged` (the host key does not match `expectedFp`), or an `Error`.
 */
export async function pairDevice(options: PairOptions): Promise<HostProfile> {
  const url = options.url.trim();
  const check = checkDirectUrl(url, {
    private_networks: options.privateNetworks,
    allow_plain_ws: options.allowPlainWs,
  });
  if (!check.ok) {
    throw new DirectUrlRefused(url, check.reason);
  }
  if (globalThis.crypto?.subtle === undefined) {
    // WebCrypto exists only in a secure context: https://, or http://localhost / 127.0.0.1.
    throw new Error(
      "this page is not a secure context: open it over https:// or on localhost to pair",
    );
  }
  const keys = await generateDeviceKey();
  const devicePubkey = await exportPublicKey(keys.publicKey);
  const paired = await exchange(url, {
    ticket: options.ticket,
    device_pubkey_ed25519: devicePubkey,
    device_name: options.deviceName,
    platform: options.platform ?? "web",
    timeoutMs: options.timeoutMs ?? DEFAULT_TIMEOUT_MS,
  });
  const hostFp = await fingerprint(paired.host_pubkey).catch(() => null);
  if (
    hostFp === null ||
    (options.expectedFp !== undefined && hostFp !== options.expectedFp) ||
    (options.expectedHostId !== undefined &&
      paired.host_id !== options.expectedHostId)
  ) {
    throw new HostIdentityChanged();
  }
  const profile: HostProfile = {
    host_id: paired.host_id,
    name: hostName(url),
    host_pubkey: paired.host_pubkey,
    host_pubkey_fp: hostFp,
    transport: "direct",
    direct_url: url,
    allow_plain_ws: options.allowPlainWs === true,
    device_id: paired.device_id,
    device_key: keys.privateKey,
    scope: paired.scope,
  };
  if (options.privateNetworks !== undefined) {
    profile.private_networks = [...options.privateNetworks];
  }
  await saveProfile(options.store, profile);
  return profile;
}

type Complete = {
  ticket: string;
  device_pubkey_ed25519: string;
  device_name: string;
  platform: string;
  timeoutMs: number;
};

function exchange(url: string, complete: Complete): Promise<PairedFrame> {
  const origin = originOf(url);
  return new Promise<PairedFrame>((resolve, reject) => {
    let settled = false;
    let socket: WebSocket | null = null;
    const onViolation = (event: Event): void => {
      // Browsers that do not throw from the constructor report the connect-src block here.
      const blocked = (event as SecurityPolicyViolationEvent).blockedURI;
      if (typeof blocked === "string" && blocked.startsWith(origin)) {
        finish(new CspBlocked(origin));
      }
    };
    const timer = setTimeout(() => {
      finish(new Error("pairing timed out: the host did not answer"));
    }, complete.timeoutMs);
    const finish = (outcome: PairedFrame | Error): void => {
      if (settled) {
        return;
      }
      settled = true;
      clearTimeout(timer);
      if (typeof document !== "undefined") {
        document.removeEventListener("securitypolicyviolation", onViolation);
      }
      if (outcome instanceof Error) {
        if (
          socket !== null &&
          socket.readyState !== WebSocket.CLOSING &&
          socket.readyState !== WebSocket.CLOSED
        ) {
          socket.close();
        }
        reject(outcome);
        return;
      }
      resolve(outcome);
    };
    if (typeof document !== "undefined") {
      document.addEventListener("securitypolicyviolation", onViolation);
    }
    try {
      socket = new WebSocket(url);
    } catch (error) {
      finish(
        error instanceof DOMException && error.name === "SecurityError"
          ? new CspBlocked(origin)
          : error instanceof Error
            ? error
            : new Error(String(error)),
      );
      return;
    }
    const opened = socket;
    opened.addEventListener("open", () => {
      opened.send(
        JSON.stringify({
          t: "hello",
          proto: [1, 1],
          client: "web",
          device: "dev_pairing",
          origin,
          last_seq: 0,
          caps: [],
        }),
      );
      // D1: `pair.complete` is the first frame after `hello`.
      opened.send(
        JSON.stringify({
          t: "pair.complete",
          ticket: complete.ticket,
          device_pubkey_ed25519: complete.device_pubkey_ed25519,
          device_name: complete.device_name,
          platform: complete.platform,
        }),
      );
    });
    opened.addEventListener("message", (event) => {
      const frame = parseFrame(event);
      if (frame === null || frame.t !== "paired") {
        return;
      }
      const paired = pairedFrame(frame);
      finish(paired ?? new Error("the host sent a malformed paired frame"));
    });
    opened.addEventListener("close", (event) => {
      const code = "code" in event ? (event as CloseEvent).code : 1005;
      finish(
        code === 4001
          ? new Unauthorized("the host refused this pairing code")
          : new Error("pairing failed: the connection closed"),
      );
    });
  });
}

function pairedFrame(frame: Record<string, unknown>): PairedFrame | null {
  const { device_id, host_id, host_pubkey, scope } = frame;
  if (
    typeof device_id !== "string" ||
    typeof host_id !== "string" ||
    typeof host_pubkey !== "string" ||
    typeof scope !== "string" ||
    !SCOPES.has(scope)
  ) {
    return null;
  }
  return { device_id, host_id, host_pubkey, scope: scope as DeviceScope };
}

function parseFrame(event: Event): Record<string, unknown> | null {
  const data = "data" in event ? (event as MessageEvent).data : null;
  if (typeof data !== "string") {
    return null;
  }
  try {
    const parsed: unknown = JSON.parse(data);
    return typeof parsed === "object" &&
      parsed !== null &&
      !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : null;
  } catch {
    return null;
  }
}

function originOf(url: string): string {
  try {
    return new URL(url).origin;
  } catch {
    return url;
  }
}

function hostName(url: string): string {
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}
