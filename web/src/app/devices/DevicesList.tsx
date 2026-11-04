import { QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import type { DeviceRecord } from "../../client/connection.ts";
import { createQueryClient, useCall } from "../../client/hooks.ts";
import { call } from "../../client/index.ts";

/** Settings → Devices (plan 0055 D9): the devices paired with this host, with revoke (D2). */
export function DevicesList() {
  const [client] = useState(() => createQueryClient());
  return (
    <QueryClientProvider client={client}>
      <DevicesListView />
    </QueryClientProvider>
  );
}

function DevicesListView() {
  const list = useCall("devices.list", {});
  // Absent on the host's own loopback session, which is not a paired device.
  const self = useCall("devices.self", {});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const devices = list.data?.devices ?? [];

  async function revoke(device: DeviceRecord): Promise<void> {
    setBusy(device.id);
    setError("");
    try {
      await call("devices.revoke", { id: device.id });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "revoke failed");
    } finally {
      setBusy(null);
      void list.refetch();
    }
  }

  return (
    <section className="space-y-2">
      <h2 className="font-medium">Paired devices</h2>
      {list.isError ? (
        <p className="text-sm text-red-300">Devices unavailable</p>
      ) : list.isPending ? (
        <p className="text-sm text-zinc-400">Loading…</p>
      ) : devices.length === 0 ? (
        <p className="text-sm text-zinc-400">No paired devices</p>
      ) : (
        <ul className="space-y-2">
          {devices.map((device) => (
            <li
              key={device.id}
              className="flex flex-wrap items-baseline gap-x-3 gap-y-1 rounded border border-zinc-800 px-3 py-2 text-sm"
            >
              <span className="font-medium">{device.name}</span>
              <span className="text-zinc-400">{device.platform}</span>
              <span className="text-zinc-400">{device.scope}</span>
              <span className="text-zinc-500">
                {device.last_seen === null
                  ? "never connected"
                  : `last seen ${new Date(device.last_seen).toLocaleString()}`}
              </span>
              {device.revoked_at !== null ? (
                <span className="ml-auto text-red-300">revoked</span>
              ) : device.id === self.data?.id ? (
                // This key is the browser's only way in: revoking it locks this browser out.
                <span className="ml-auto text-zinc-400">this device</span>
              ) : (
                <button
                  type="button"
                  disabled={busy === device.id}
                  className="ml-auto rounded border border-red-800 px-2 py-0.5 text-red-200 disabled:opacity-40"
                  onClick={() => {
                    void revoke(device);
                  }}
                >
                  Revoke
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {error !== "" ? <p className="text-sm text-red-300">{error}</p> : null}
    </section>
  );
}
