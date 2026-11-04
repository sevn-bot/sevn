import { useState } from "react";
import {
  CspBlocked,
  DirectUrlRefused,
  HostIdentityChanged,
  Unauthorized,
} from "../../client/errors.ts";
import type { PairLink } from "../../client/pairing.ts";
import { QrScanner, scannerAvailable } from "./QrScanner.tsx";

export type PairInput = {
  url: string;
  /** The short code as typed (normalised), or the full ticket from a scanned QR. */
  code: string;
  allowPlainWs: boolean;
  /** CIDR ranges that replace the default private networks for this host (D7). */
  privateNetworks?: string[];
  /** The scanned QR's host key fingerprint, when pairing from a QR. */
  expectedFp?: string;
};

export type PairedHost = { host_id: string; name: string };

type Failure =
  | { kind: "csp"; origin: string }
  | { kind: "refused"; message: string }
  | { kind: "other"; message: string };

/**
 * Pair this browser with another host (plan 0055 D7, D8, D9): its address and short code,
 * or a scanned QR when the browser has `BarcodeDetector`.
 */
export function PairingPage({
  pair,
}: {
  pair: (input: PairInput) => Promise<PairedHost>;
}) {
  const [url, setUrl] = useState("");
  const [code, setCode] = useState("");
  // A scanned QR stays the credential for a retry (say, after the plain ws:// opt-in).
  const [scanned, setScanned] = useState<PairLink | null>(null);
  const [allowPlainWs, setAllowPlainWs] = useState(false);
  const [showPlainToggle, setShowPlainToggle] = useState(false);
  const [showNetworks, setShowNetworks] = useState(false);
  const [networks, setNetworks] = useState("");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [paired, setPaired] = useState<PairedHost | null>(null);
  const [canScan] = useState(scannerAvailable);
  const [scanning, setScanning] = useState(false);

  async function run(input: PairInput): Promise<void> {
    setBusy(true);
    setFailure(null);
    setPaired(null);
    try {
      setPaired(await pair(input));
    } catch (caught) {
      if (caught instanceof DirectUrlRefused) {
        setShowPlainToggle(true);
        if (caught.reason === "not_private") {
          setShowNetworks(true);
        }
      }
      setFailure(describe(caught));
    } finally {
      setBusy(false);
    }
  }

  function onScanned(link: PairLink): void {
    setScanning(false);
    const target = link.direct_url ?? url.trim();
    if (target === "") {
      setFailure({
        kind: "other",
        message:
          "This QR code has no host address. Enter the host address, then scan again.",
      });
      return;
    }
    setUrl(target);
    setScanned(link);
    void run({
      url: target,
      code: link.ticket,
      allowPlainWs,
      ...privateNetworks(networks),
      expectedFp: link.host_pubkey_fp,
    });
  }

  return (
    <section className="max-w-xl space-y-4">
      <h1 className="text-lg font-medium">Add a host</h1>
      <p className="text-sm text-zinc-400">
        On the other host, open Settings → Devices or run <code>sevn pair</code>
        , then enter its address and the short code here.
      </p>
      <form
        className="space-y-3"
        onSubmit={(event) => {
          event.preventDefault();
          void run({
            url: socketAddress(url),
            code: scanned?.ticket ?? normaliseCode(code),
            allowPlainWs,
            ...privateNetworks(networks),
            ...(scanned === null ? {} : { expectedFp: scanned.host_pubkey_fp }),
          });
        }}
      >
        <label className="block text-sm">
          Host address
          <input
            className="mt-1 block w-full rounded bg-zinc-900 px-2 py-1 font-mono"
            placeholder="wss://mac.tailnet.ts.net/ws"
            autoComplete="off"
            value={url}
            onChange={(event) => {
              setUrl(event.target.value);
            }}
          />
        </label>
        <label className="block text-sm">
          Short code
          <input
            className="mt-1 block w-full rounded bg-zinc-900 px-2 py-1 font-mono uppercase"
            placeholder={scanned === null ? "XXXX-XXXX" : "From the QR code"}
            autoComplete="off"
            value={code}
            onChange={(event) => {
              setScanned(null);
              setCode(event.target.value);
            }}
          />
        </label>
        {showNetworks ? (
          <label className="block text-sm">
            Private networks for this host (CIDR, comma-separated)
            <input
              className="mt-1 block w-full rounded bg-zinc-900 px-2 py-1 font-mono"
              placeholder="10.147.17.0/24"
              autoComplete="off"
              value={networks}
              onChange={(event) => {
                setNetworks(event.target.value);
              }}
            />
          </label>
        ) : null}
        {showPlainToggle ? (
          <div className="space-y-1">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={allowPlainWs}
                onChange={(event) => {
                  setAllowPlainWs(event.target.checked);
                }}
              />
              Allow plain ws:// for this host
            </label>
            <p className="text-xs text-amber-300">
              Plain ws:// is not encrypted by the browser. Turn this on only for
              an overlay network you trust (WireGuard, ZeroTier, NetBird) or
              your own LAN.
            </p>
          </div>
        ) : null}
        <div className="flex gap-2">
          <button
            type="submit"
            disabled={busy}
            className="rounded bg-zinc-100 px-3 py-1.5 text-sm font-medium text-zinc-950 disabled:opacity-40"
          >
            Pair
          </button>
          {canScan && !scanning ? (
            <button
              type="button"
              disabled={busy}
              className="rounded border border-zinc-700 px-3 py-1.5 text-sm disabled:opacity-40"
              onClick={() => {
                setFailure(null);
                setScanning(true);
              }}
            >
              Scan QR code
            </button>
          ) : null}
        </div>
      </form>
      {scanning ? (
        <QrScanner
          onLink={onScanned}
          onCancel={() => {
            setScanning(false);
          }}
          onFail={(message) => {
            setScanning(false);
            setFailure({ kind: "other", message });
          }}
        />
      ) : null}
      {busy ? <p className="text-sm text-zinc-400">Pairing…</p> : null}
      {paired !== null ? (
        <p role="status" className="text-emerald-300">
          {`Paired with ${paired.name}`}
        </p>
      ) : null}
      {failure !== null ? <FailureView failure={failure} /> : null}
    </section>
  );
}

function FailureView({ failure }: { failure: Failure }) {
  if (failure.kind === "csp") {
    return (
      <div role="alert" className="space-y-1 text-sm text-red-300">
        <p>
          This page's Content-Security-Policy blocked the connection. On the
          host that serves this page, add this line under <code>[http]</code> in{" "}
          <code>config.toml</code>, restart it, and try again:
        </p>
        <pre className="overflow-x-auto rounded bg-zinc-900 px-2 py-1 text-zinc-100">
          <code>{`connect_src = ["${failure.origin}"]`}</code>
        </pre>
      </div>
    );
  }
  return (
    <p role="alert" className="text-sm text-red-300">
      {failure.message}
    </p>
  );
}

function describe(error: unknown): Failure {
  if (error instanceof CspBlocked) {
    return { kind: "csp", origin: error.origin };
  }
  if (error instanceof DirectUrlRefused) {
    return { kind: "refused", message: error.message };
  }
  if (error instanceof Unauthorized) {
    return {
      kind: "other",
      message:
        "The host refused this code: it is wrong, already used, or expired. Start a new pairing on the host.",
    };
  }
  if (error instanceof HostIdentityChanged) {
    return { kind: "other", message: error.message };
  }
  return {
    kind: "other",
    message: error instanceof Error ? error.message : "pairing failed",
  };
}

/** A host address with no path dials the host's `/ws` endpoint. */
function socketAddress(input: string): string {
  const trimmed = input.trim();
  try {
    const parsed = new URL(trimmed);
    if (
      (parsed.protocol === "ws:" || parsed.protocol === "wss:") &&
      parsed.pathname === "/" &&
      parsed.search === ""
    ) {
      return `${parsed.origin}/ws`;
    }
  } catch {
    // Not a URL: the D7 check names the rule.
  }
  return trimmed;
}

/** The typed CIDR list, or nothing when empty (the default networks then apply). */
function privateNetworks(text: string): { privateNetworks?: string[] } {
  const list = text
    .split(/[\s,]+/)
    .map((item) => item.trim())
    .filter((item) => item !== "");
  return list.length === 0 ? {} : { privateNetworks: list };
}

/** `" k7m2-q9xr "` → `"K7M2Q9XR"`; anything else (a full ticket) is only trimmed. */
function normaliseCode(input: string): string {
  const compact = input.replace(/[\s-]/g, "");
  return compact.length === 8 ? compact.toUpperCase() : input.trim();
}
