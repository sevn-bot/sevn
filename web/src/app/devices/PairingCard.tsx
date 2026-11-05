import { useEffect, useState } from "react";
import type { DeviceScope, MethodResult } from "../../client/connection.ts";
import { call } from "../../client/index.ts";
import { parsePairUri } from "../../client/pairing.ts";
import { QrCode } from "./QrCode.tsx";

type Ticket = MethodResult["pairing.start"];

const SCOPES: { value: DeviceScope; label: string }[] = [
  { value: "member", label: "member" },
  { value: "read_only", label: "read_only" },
  { value: "owner", label: "owner" },
];

/**
 * Settings → Devices (plan 0055 D9): start a one-time pairing ticket on this host and show
 * it as a QR code and a short code, with the time left before it expires (D1: 10 minutes).
 */
export function PairingCard() {
  const [scope, setScope] = useState<DeviceScope>("member");
  const [ticket, setTicket] = useState<Ticket | null>(null);
  const [error, setError] = useState("");
  const [starting, setStarting] = useState(false);

  async function start(): Promise<void> {
    setStarting(true);
    setError("");
    try {
      setTicket(await call("pairing.start", { scope }));
    } catch (caught) {
      setTicket(null);
      setError(caught instanceof Error ? caught.message : "pairing failed");
    } finally {
      setStarting(false);
    }
  }

  return (
    <section className="space-y-3 rounded border border-zinc-800 p-3">
      <h2 className="font-medium">Pair a new device</h2>
      <div className="flex flex-wrap items-end gap-3">
        <label className="block text-sm">
          Scope
          <select
            className="mt-1 block rounded bg-zinc-900 px-2 py-1"
            value={scope}
            disabled={starting}
            onChange={(event) => {
              setScope(toScope(event.target.value));
              setTicket(null);
            }}
          >
            {SCOPES.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          disabled={starting}
          className="rounded bg-zinc-100 px-3 py-1.5 text-sm font-medium text-zinc-950 disabled:opacity-40"
          onClick={() => {
            void start();
          }}
        >
          Start pairing
        </button>
      </div>
      {scope === "owner" ? (
        <p className="text-sm text-amber-300">
          An owner device can do everything you can, including pairing and
          revoking devices.
        </p>
      ) : null}
      {error !== "" ? <p className="text-sm text-red-300">{error}</p> : null}
      {ticket !== null ? <TicketView ticket={ticket} /> : null}
    </section>
  );
}

function TicketView({ ticket }: { ticket: Ticket }) {
  const address = directUrl(ticket.qr_uri);
  return (
    <div className="flex flex-wrap gap-4">
      <QrCode value={ticket.qr_uri} label="Pairing QR code" />
      <div className="space-y-2 text-sm">
        <p>
          Scan the QR code with the new device, or open sevn on it and enter the
          short code
          {address === null ? "." : " with this host's address:"}
        </p>
        {address !== null ? (
          <p className="font-mono break-all">{address}</p>
        ) : null}
        <p
          data-testid="pairing-code"
          className="font-mono text-2xl tracking-widest"
        >
          {groupCode(ticket.short_code)}
        </p>
        <Countdown expiresAt={ticket.expires_at} />
      </div>
    </div>
  );
}

function Countdown({ expiresAt }: { expiresAt: string }) {
  const deadline = Date.parse(expiresAt);
  const [now, setNow] = useState(() => Date.now());
  const left = Math.ceil((deadline - now) / 1000);
  const expired = Number.isNaN(deadline) || left <= 0;

  useEffect(() => {
    if (expired) {
      return;
    }
    const timer = setInterval(() => {
      setNow(Date.now());
    }, 1000);
    return () => {
      clearInterval(timer);
    };
  }, [expired]);

  if (expired) {
    return <p className="text-red-300">Expired</p>;
  }
  const minutes = Math.floor(left / 60);
  const seconds = String(left % 60).padStart(2, "0");
  return <p className="text-zinc-400">{`Expires in ${minutes}:${seconds}`}</p>;
}

function toScope(value: string): DeviceScope {
  return value === "owner" || value === "read_only" ? value : "member";
}

function groupCode(code: string): string {
  return code.length === 8 ? `${code.slice(0, 4)}-${code.slice(4)}` : code;
}

function directUrl(qrUri: string): string | null {
  try {
    return parsePairUri(qrUri).direct_url;
  } catch {
    return null;
  }
}
