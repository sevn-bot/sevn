import { QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import type { MethodResult } from "../../client/connection.ts";
import { createQueryClient, useCall } from "../../client/hooks.ts";
import { call } from "../../client/index.ts";

type Memory = MethodResult["memories.list"]["memories"][number];

export function MemoriesPanel({ botId }: { botId: string }) {
  const [client] = useState(() => createQueryClient());
  return (
    <QueryClientProvider client={client}>
      <MemoriesView botId={botId} />
    </QueryClientProvider>
  );
}

function MemoriesView({ botId }: { botId: string }) {
  const query = useCall("memories.list", { bot_id: botId });
  const memories = query.data?.memories ?? [];

  return (
    <section className="space-y-2">
      <h2 className="text-sm font-medium">Memories</h2>
      <ul className="space-y-2">
        {memories.map((memory) => (
          <MemoryRow
            key={memory.id}
            memory={memory}
            onChanged={() => {
              void query.refetch();
            }}
          />
        ))}
      </ul>
    </section>
  );
}

function MemoryRow({
  memory,
  onChanged,
}: {
  memory: Memory;
  onChanged: () => void;
}) {
  const [text, setText] = useState(memory.text);
  const pinned = memory.tier === "pinned";

  function pin(): void {
    const tier = pinned ? "recall" : undefined;
    void call(
      "memories.pin",
      tier === undefined ? { id: memory.id } : { id: memory.id, tier },
    )
      .then(onChanged)
      .catch(() => undefined);
  }

  function remove(): void {
    void call("memories.delete", { id: memory.id })
      .then(onChanged)
      .catch(() => undefined);
  }

  function save(): void {
    void call("memories.update", { id: memory.id, text })
      .then(onChanged)
      .catch(() => undefined);
  }

  return (
    <li className="space-y-2 rounded border border-zinc-800 px-3 py-2">
      <p>{memory.text}</p>
      <p className="text-sm text-zinc-400">{memory.tier}</p>
      <label className="block text-sm">
        Edit
        <input
          className="mt-1 block w-full rounded bg-zinc-900 px-2 py-1"
          value={text}
          onChange={(event) => {
            setText(event.target.value);
          }}
        />
      </label>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className="rounded border border-zinc-700 px-2 py-1 text-sm"
          onClick={save}
        >
          Save
        </button>
        <button
          type="button"
          className="rounded border border-zinc-700 px-2 py-1 text-sm"
          onClick={pin}
        >
          {pinned ? "Unpin" : "Pin"}
        </button>
        <button
          type="button"
          className="rounded border border-zinc-700 px-2 py-1 text-sm"
          onClick={remove}
        >
          Delete
        </button>
      </div>
    </li>
  );
}
