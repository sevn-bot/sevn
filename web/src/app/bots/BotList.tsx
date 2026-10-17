import { QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { createQueryClient, useCall } from "../../client/hooks.ts";
import { call } from "../../client/index.ts";
import { go } from "../routes.ts";

type RuntimeName = "pydantic_ai" | "claude";

export function BotList() {
  const [client] = useState(() => createQueryClient());
  return (
    <QueryClientProvider client={client}>
      <BotListView />
    </QueryClientProvider>
  );
}

function BotListView() {
  const list = useCall("bots.list", {});
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [runtime, setRuntime] = useState<RuntimeName>("pydantic_ai");
  const [error, setError] = useState("");
  const bots = list.data?.bots ?? [];

  async function create(): Promise<void> {
    setError("");
    try {
      const created = await call("bots.create", { name, runtime });
      setOpen(false);
      setName("");
      if (created.id !== "") {
        go(`/bots/${created.id}`);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "create failed");
    }
  }

  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-medium">Bots</h1>
        {open ? null : (
          <button
            type="button"
            className="rounded bg-zinc-100 px-3 py-1.5 text-sm font-medium text-zinc-950"
            onClick={() => {
              setOpen(true);
            }}
          >
            Create bot
          </button>
        )}
      </div>
      <ul className="space-y-2">
        {bots.map((bot) => (
          <li key={bot.id}>
            <button
              type="button"
              className="text-left text-base"
              onClick={() => {
                go(`/bots/${bot.id}`);
              }}
            >
              {bot.name}
            </button>
          </li>
        ))}
      </ul>
      {open ? (
        <div className="space-y-3 rounded border border-zinc-800 p-3">
          <label className="block text-sm">
            Name
            <input
              className="mt-1 block w-full rounded bg-zinc-900 px-2 py-1"
              value={name}
              onChange={(event) => {
                setName(event.target.value);
              }}
            />
          </label>
          <label className="block text-sm">
            Runtime
            <select
              className="mt-1 block rounded bg-zinc-900 px-2 py-1"
              value={runtime}
              onChange={(event) => {
                setRuntime(
                  event.target.value === "claude" ? "claude" : "pydantic_ai",
                );
              }}
            >
              <option value="pydantic_ai">pydantic_ai</option>
              <option value="claude">claude</option>
            </select>
          </label>
          {error !== "" ? (
            <p className="text-sm text-red-300">{error}</p>
          ) : null}
          <button
            type="button"
            className="rounded bg-zinc-100 px-3 py-1.5 text-sm font-medium text-zinc-950"
            onClick={() => {
              void create();
            }}
          >
            Create
          </button>
        </div>
      ) : null}
    </section>
  );
}
