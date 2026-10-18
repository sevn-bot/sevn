import { QueryClientProvider } from "@tanstack/react-query";
import { type UIEvent, useEffect, useRef, useState } from "react";
import {
  call,
  type MethodResult,
  type ProtocolEvent,
} from "../../client/connection.ts";
import {
  createQueryClient,
  useCall,
  useEvents,
  useTicks,
} from "../../client/hooks.ts";
import { ApprovalCard } from "../approvals/ApprovalCard.tsx";
import { MemoriesPanel } from "../bots/MemoriesPanel.tsx";
import { SandboxSettings } from "../bots/SandboxSettings.tsx";
import { ModelPicker } from "../models/ModelPicker.tsx";
import { go } from "../routes.ts";
import { type LaneAgent, Lanes, toLane } from "./Lanes.tsx";
import { AskChips, RoutingChip } from "./RoutingChip.tsx";

type ListedMessage = MethodResult["messages.list"]["messages"][number];
type LaneRef = { id: string; title: string };

const refreshKinds = new Set([
  "message.created",
  "agent.updated",
  "pending.created",
  "pending.resolved",
  "turn.started",
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
  const infoQuery = useCall("system.info", {});
  const ticks = useTicks("turn.delta");
  const events = useEvents();
  const seenEvents = useRef(0);
  const olderCursor = useRef<string | null | undefined>(undefined);
  const loadingOlder = useRef(false);
  const logRef = useRef<HTMLDivElement>(null);
  const followTail = useRef(true);
  const [older, setOlder] = useState<ListedMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const page = messagesQuery.data?.messages ?? [];
  const messages = [...older, ...chronological(page)];
  const agents = agentsQuery.data?.agents ?? [];
  const laneAgents = lanesFor(agents, aheadByAgent(events));
  const agentIds = new Set(agents.map((agent) => agent.id));
  const pending = (pendingQuery.data?.pending ?? []).filter((item) =>
    agentIds.has(item.agent_id),
  );
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
    const node = logRef.current;
    const count = (messagesQuery.data?.messages.length ?? 0) + ticks.length;
    if (
      node === null ||
      !followTail.current ||
      count === 0 ||
      node.scrollHeight <= node.clientHeight
    ) {
      return;
    }
    node.scrollTop = node.scrollHeight;
  }, [messagesQuery.data, ticks]);

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
      setOlder((current) => [...chronological(next.messages), ...current]);
    } catch {
      // The log stays on the page that loaded. Another scroll can retry.
    } finally {
      loadingOlder.current = false;
    }
  }

  function onScroll(event: UIEvent<HTMLDivElement>): void {
    const node = event.currentTarget;
    const fromTail = node.scrollHeight - node.scrollTop - node.clientHeight;
    followTail.current = node.scrollTop !== 0 && fromTail <= 1;
    if (node.scrollTop !== 0) {
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
      {allowAllOn(infoQuery.data) ? (
        <p className="rounded border border-amber-700 bg-amber-950 px-3 py-2 text-sm">
          Sandbox allow all is on
        </p>
      ) : null}
      <Lanes agents={laneAgents} />
      <div
        ref={logRef}
        role="log"
        className="max-h-80 space-y-2 overflow-y-auto rounded border border-zinc-800 px-3 py-2"
        onScroll={onScroll}
      >
        {messages.map((message) => (
          <MessageBody
            key={message.id}
            message={message}
            botId={botId}
            agents={laneAgents}
          />
        ))}
        {groupedTicks(botTicks(ticks, agentIds)).map(([turnId, text]) =>
          persisted.has(turnId) ? null : <p key={turnId}>{text}</p>,
        )}
      </div>
      <div className="space-y-2">
        {pending.map((item) => (
          <ApprovalCard
            key={item.id}
            pendingId={item.id}
            kind={item.kind}
            name={item.name}
            args={item.args}
          />
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
          <div className="space-y-3 pt-2">
            <ModelPicker botId={botId} model={model} />
            <MemoriesPanel botId={botId} />
            <SandboxSettings botId={botId} />
          </div>
        ) : null}
      </details>
    </section>
  );
}

function MessageBody({
  message,
  botId,
  agents,
}: {
  message: ListedMessage;
  botId: string;
  agents: readonly LaneRef[];
}) {
  const text = messageText(message.parts);
  return (
    <div>
      {text !== "" ? <p>{text}</p> : null}
      {partViews(message, botId, agents)}
    </div>
  );
}

function partViews(
  message: ListedMessage,
  botId: string,
  agents: readonly LaneRef[],
) {
  const seen = new Map<string, number>();
  return message.parts.map((part) => {
    const base = [
      part.type,
      part.intent,
      part.code,
      part.title,
      part.choices,
      part.text,
    ].join(":");
    const nth = seen.get(base) ?? 0;
    seen.set(base, nth + 1);
    return (
      <PartView
        key={`${message.id}:${base}:${nth}`}
        part={part}
        messageId={message.id}
        botId={botId}
        agents={agents}
      />
    );
  });
}

function PartView({
  part,
  messageId,
  botId,
  agents,
}: {
  part: Record<string, string>;
  messageId: string;
  botId: string;
  agents: readonly LaneRef[];
}) {
  if (part.type === "routing") {
    return (
      <RoutingChip
        messageId={messageId}
        intent={part.intent ?? ""}
        title={part.title ?? ""}
        agents={agents}
      />
    );
  }
  if (part.type === "routing_ask") {
    return <AskChips botId={botId} choices={part.choices ?? ""} />;
  }
  if (part.type === "error" && part.code === "path_locked") {
    const holder = part.holder_title ?? "";
    if (holder === "") {
      return null;
    }
    return <p>{`Locked by ${holder}`}</p>;
  }
  if (part.type === "injection") {
    return <span>Possible injection</span>;
  }
  return null;
}

function lanesFor(
  agents: MethodResult["agents.list"]["agents"],
  queued: ReadonlyMap<string, number>,
): LaneAgent[] {
  return agents.map((agent) => {
    const lane = toLane(agent);
    if (typeof lane.ahead === "number") {
      return lane;
    }
    const ahead = queued.get(agent.id);
    if (ahead === undefined) {
      return lane;
    }
    return { ...lane, ahead };
  });
}

function aheadByAgent(events: ProtocolEvent[]): ReadonlyMap<string, number> {
  const found = new Map<string, number>();
  for (const event of events) {
    if (event.k !== "job.queued") {
      continue;
    }
    const agentId = event.d.agent_id;
    const ahead = event.d.ahead;
    if (typeof agentId !== "string" || typeof ahead !== "number") {
      continue;
    }
    found.set(agentId, ahead);
  }
  return found;
}

function allowAllOn(
  info: { caps?: { allow_all?: boolean } } | undefined,
): boolean {
  return info?.caps?.allow_all === true;
}

function chronological(rows: ListedMessage[]): ListedMessage[] {
  return [...rows].reverse();
}

function messageText(parts: Record<string, string>[]): string {
  return parts.map((part) => part.text ?? "").join("");
}

function botTicks(
  ticks: Record<string, unknown>[],
  agentIds: ReadonlySet<string>,
): Record<string, unknown>[] {
  return ticks.filter((tick) => {
    const agentId = tick.agent_id;
    return typeof agentId === "string" && agentIds.has(agentId);
  });
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
