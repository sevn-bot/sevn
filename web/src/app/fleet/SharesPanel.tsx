import { useState } from "react";
import { call, type FleetBot } from "../../client/connection.ts";
import { useCall } from "../../client/hooks.ts";
import { age, stamp } from "./time.ts";

const expiries = [
  { hours: 24, label: "1 day" },
  { hours: 168, label: "7 days" },
  { hours: 720, label: "30 days" },
];

/** Owner controls for read-only share links. Lists only once opened. */
export function SharesPanel({
  bots,
  asOf,
}: {
  bots: FleetBot[];
  asOf: string;
}) {
  const [open, setOpen] = useState(false);
  return (
    <details
      className="rounded border border-zinc-800 px-3 py-2 text-sm"
      onToggle={(event) => {
        setOpen(event.currentTarget.open);
      }}
    >
      <summary>Share links</summary>
      {open ? <SharesBody bots={bots} asOf={asOf} /> : null}
    </details>
  );
}

function SharesBody({ bots, asOf }: { bots: FleetBot[]; asOf: string }) {
  const list = useCall("shares.list", {});
  const [label, setLabel] = useState("");
  const [scope, setScope] = useState("");
  const [hours, setHours] = useState(168);
  const [created, setCreated] = useState("");
  const [error, setError] = useState("");
  const names = new Map(bots.map((bot) => [bot.id, bot.name]));
  const shares = list.data?.shares ?? [];

  async function create() {
    setError("");
    try {
      const result = await call("shares.create", {
        label,
        bot_id: scope === "" ? null : scope,
        expires_in_hours: hours,
      });
      setCreated(`${window.location.origin}${result.path}`);
      setLabel("");
      void list.refetch();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "could not create");
    }
  }

  async function revoke(shareId: string) {
    try {
      await call("shares.revoke", { share_id: shareId });
      void list.refetch();
    } catch {
      setError("could not revoke");
    }
  }

  const field = "mt-1 block w-full rounded bg-zinc-900 px-2 py-1 text-sm";
  return (
    <div className="space-y-3 pt-2">
      <p className="text-xs text-zinc-500">
        A link shows counts, statuses, schedules and shareable metrics, never
        messages, questions or prompts. It needs this host to be reachable by
        whoever opens it.
      </p>
      <form
        className="grid gap-2 sm:grid-cols-4"
        onSubmit={(event) => {
          event.preventDefault();
          void create();
        }}
      >
        <label className="block sm:col-span-2">
          Link label
          <input
            className={field}
            value={label}
            onChange={(event) => {
              setLabel(event.target.value);
            }}
          />
        </label>
        <label className="block">
          Scope
          <select
            className={field}
            value={scope}
            onChange={(event) => {
              setScope(event.target.value);
            }}
          >
            <option value="">All bots</option>
            {bots.map((bot) => (
              <option key={bot.id} value={bot.id}>
                {bot.name}
              </option>
            ))}
          </select>
        </label>
        <label className="block">
          Expires in
          <select
            className={field}
            value={hours}
            onChange={(event) => {
              setHours(Number(event.target.value));
            }}
          >
            {expiries.map((item) => (
              <option key={item.hours} value={item.hours}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <button
          type="submit"
          disabled={label.trim() === ""}
          className="rounded bg-zinc-100 px-3 py-1 text-sm font-medium text-zinc-950 disabled:opacity-40 sm:col-span-4 sm:justify-self-start"
        >
          Create link
        </button>
      </form>
      {created !== "" ? (
        <div
          data-testid="new-share-link"
          className="space-y-1 rounded border border-amber-700 px-3 py-2"
        >
          <p className="break-all font-mono text-xs">{created}</p>
          <p className="text-xs text-amber-400">
            Copy it now: it is shown once.
          </p>
          <button
            type="button"
            className="rounded border border-zinc-700 px-2 py-0.5 text-xs"
            onClick={() => {
              void navigator.clipboard
                ?.writeText(created)
                .catch(() => undefined);
            }}
          >
            Copy
          </button>
        </div>
      ) : null}
      {error !== "" ? <p className="text-red-400">{error}</p> : null}
      <ul className="space-y-1">
        {shares.map((share) => (
          <li
            key={share.id}
            data-status={share.status}
            className="flex flex-wrap items-baseline gap-x-2 rounded border border-zinc-800 px-3 py-2"
          >
            <span className="text-zinc-200">{share.label}</span>
            <span className="text-zinc-400">
              {share.bot_id === null
                ? "All bots"
                : `${names.get(share.bot_id) ?? "a bot"} only`}
            </span>
            <span className="text-zinc-400">
              {share.status === "active"
                ? `expires in ${age(asOf, share.expires_at)}`
                : share.status}
            </span>
            <span className="text-zinc-500">
              {share.opens === 0
                ? "never opened"
                : `opened ${share.opens} ${share.opens === 1 ? "time" : "times"}, last ${stamp(share.last_opened_at ?? asOf, asOf)}`}
            </span>
            {share.status === "active" ? (
              <button
                type="button"
                className="ml-auto rounded border border-zinc-700 px-2 py-0.5 text-xs"
                onClick={() => {
                  void revoke(share.id);
                }}
              >
                Revoke
              </button>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}
