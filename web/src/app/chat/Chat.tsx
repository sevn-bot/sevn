import { QueryClientProvider } from "@tanstack/react-query";
import { type UIEvent, useEffect, useRef, useState } from "react";
import { call, type MethodResult } from "../../client/connection.ts";
import {
  createQueryClient,
  useCall,
  useEvents,
  useTicks,
} from "../../client/hooks.ts";
import { ApprovalCard } from "../approvals/ApprovalCard.tsx";
import { ModelPicker } from "../models/ModelPicker.tsx";
import { go } from "../routes.ts";

type ListedMessage = MethodResult["messages.list"]["messages"][number];

const refreshKinds = new Set([
  "message.created",
  "agent.updated",
  "pending.created",
  "pending.resolved",
  "turn.finished",
]);

export function Chat({ botId }: { botId: string }) {
  const [client] = useState(() => createQueryClient());
  return (
    <QueryClientProvider client={client}>
      <ChatView botId={botId} />
    </QueryClientProvider>
  );
}

function ChatView({ botId }: { botId: string }) {
  const messagesQuery = useCall("messages.list", { bot_id: botId });
  const agentsQuery = useCall("agents.list", { bot_id: botId });
  const pendingQuery = useCall("pending.list", {});
  const botQuery = useCall("bots.get", { bot_id: botId });
  const ticks = useTicks("turn.delta");
  const events = useEvents();
  const seenEvents = useRef(0);
  const olderCursor = useRef<string | null | undefined>(undefined);
  const loadingOlder = useRef(false);
  const [older, setOlder] = useState<ListedMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const page = messagesQuery.data?.messages ?? [];
  const messages = [...page, ...older];
  const agents = agentsQuery.data?.agents ?? [];
  const pending = pendingQuery.data?.pending ?? [];
  const botName = botQuery.data?.name ?? "";
  const model = botQuery.data?.model ?? "";
  const persisted = new Set(
    messages
      .filter((message) => message.role === "assistant")
      .map((message) => message.turn_id),
  );

  useEffect(() => {
    if (olderCursor.current === undefined && messagesQuery.data !== undefined) {
      olderCursor.current = messagesQuery.data.next_cursor;
    }
  }, [messagesQuery.data]);

  useEffect(() => {
    if (events.length === seenEvents.current) {
      return;
    }
    const fresh = events.slice(seenEvents.current);
    seenEvents.current = events.length;
    if (!fresh.some((event) => refreshKinds.has(event.k))) {
      return;
    }
    void messagesQuery.refetch();
    void agentsQuery.refetch();
    void pendingQuery.refetch();
  }, [agentsQuery, events, messagesQuery, pendingQuery]);

  async function loadOlder(): Promise<void> {
    const cursor = olderCursor.current;
    if (cursor == null || loadingOlder.current) {
      return;
    }
    loadingOlder.current = true;
    try {
      const next = await call("messages.list", { bot_id: botId, cursor });
      olderCursor.current = next.next_cursor;
      setOlder((current) => [...current, ...next.messages]);
    } catch {
      // The log stays on the page that loaded. Another scroll can retry.
    } finally {
      loadingOlder.current = false;
    }
  }

  function onScroll(event: UIEvent<HTMLDivElement>): void {
    if (event.currentTarget.scrollTop !== 0) {
      return;
    }
    void loadOlder();
  }

  async function send(): Promise<void> {
    const text = draft;
    if (text === "") {
      return;
    }
    setDraft("");
    try {
      await call("messages.send", { bot_id: botId, text });
    } catch {
      setDraft(text);
    }
  }

  return (
    <section className="space-y-3">
      <div className="flex items-baseline gap-3">
        <button
          type="button"
          className="text-sm text-zinc-400"
          onClick={() => {
            go("/");
          }}
        >
          Bots
        </button>
        {botName !== "" ? (
          <h1 className="text-lg font-medium">{botName}</h1>
        ) : null}
      </div>
      <div className="space-y-2">
        {agents.map((agent) => (
          <details
            key={agent.id}
            open
            className="rounded border border-zinc-800 px-3 py-2"
          >
            <summary>{agent.title !== "" ? agent.title : agent.id}</summary>
            <p className="text-sm text-zinc-400">{agent.status}</p>
          </details>
        ))}
      </div>
      <div
        role="log"
        className="max-h-80 space-y-2 overflow-y-auto rounded border border-zinc-800 px-3 py-2"
        onScroll={onScroll}
      >
        {messages.map((message) => (
          <p key={message.id}>{messageText(message.parts)}</p>
        ))}
        {groupedTicks(ticks).map(([turnId, text]) =>
          persisted.has(turnId) ? null : <p key={turnId}>{text}</p>,
        )}
      </div>
      <div className="space-y-2">
        {pending.map((item) => (
          <ApprovalCard key={item.id} pendingId={item.id} kind={item.kind} />
        ))}
      </div>
      <label className="block text-sm">
        Message
        <input
          className="mt-1 block w-full rounded bg-zinc-900 px-2 py-1"
          value={draft}
          onChange={(event) => {
            setDraft(event.target.value);
          }}
        />
      </label>
      <button
        type="button"
        className="rounded bg-zinc-100 px-3 py-1.5 text-sm font-medium text-zinc-950"
        onClick={() => {
          void send();
        }}
      >
        Send
      </button>
      <details
        className="rounded border border-zinc-800 px-3 py-2"
        onToggle={(event) => {
          setSettingsOpen(event.currentTarget.open);
        }}
      >
        <summary>Settings</summary>
        {settingsOpen ? (
          <div className="pt-2">
            <ModelPicker botId={botId} model={model} />
          </div>
        ) : null}
      </details>
    </section>
  );
}

function messageText(parts: Record<string, string>[]): string {
  return parts.map((part) => part.text ?? "").join("");
}

function groupedTicks(
  ticks: Record<string, unknown>[],
): Array<[string, string]> {
  const order: string[] = [];
  const text = new Map<string, string>();
  for (const tick of ticks) {
    const turnId = typeof tick.turn_id === "string" ? tick.turn_id : "";
    const delta = typeof tick.text === "string" ? tick.text : "";
    if (!text.has(turnId)) {
      order.push(turnId);
    }
    text.set(turnId, (text.get(turnId) ?? "") + delta);
  }
  return order.map((turnId) => [turnId, text.get(turnId) ?? ""]);
}
