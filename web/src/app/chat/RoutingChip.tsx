import { useState } from "react";
import { call } from "../../client/index.ts";
import { MoveDialog } from "./MoveDialog.tsx";

type LaneRef = {
  id: string;
  title: string;
};

export function RoutingChip({
  messageId,
  intent,
  title,
  agents,
}: {
  messageId: string;
  intent: string;
  title: string;
  agents: readonly LaneRef[];
}) {
  const [open, setOpen] = useState(false);
  const label = routingLabel(intent, title);
  if (label === null) {
    return null;
  }
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm">
      <span>{label}</span>
      <button
        type="button"
        className="rounded border border-zinc-700 px-2 py-1"
        onClick={() => {
          setOpen(true);
        }}
      >
        Move to…
      </button>
      <button
        type="button"
        className="rounded border border-zinc-700 px-2 py-1"
        onClick={() => {
          startNew(messageId);
        }}
      >
        Start new
      </button>
      {open ? (
        <MoveDialog
          agents={agents}
          onMove={(agentId) => {
            setOpen(false);
            moveTo(messageId, agentId);
          }}
        />
      ) : null}
    </div>
  );
}

export function AskChips({
  messageId,
  agents,
  choices,
}: {
  botId: string;
  messageId: string;
  agents: readonly LaneRef[];
  choices: string;
}) {
  const items = routeChoices(choices, agents);
  if (items.length === 0) {
    return null;
  }
  const choose = (choice: RouteChoice): void => {
    void call(
      "messages.reroute",
      choice.agentId === null
        ? { message_id: messageId, new: true }
        : { message_id: messageId, agent_id: choice.agentId },
    ).catch(() => undefined);
  };
  return (
    <div className="flex flex-wrap gap-2">
      {items.map((choice) => (
        <button
          key={choice.agentId ?? "new"}
          type="button"
          className="rounded border border-zinc-700 px-2 py-1 text-sm"
          onClick={() => {
            choose(choice);
          }}
        >
          {choice.label}
        </button>
      ))}
    </div>
  );
}

type RouteChoice = { label: string; agentId: string | null };

function routeChoices(raw: string, agents: readonly LaneRef[]): RouteChoice[] {
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.flatMap((item: unknown): RouteChoice[] => {
      if (
        typeof item !== "object" ||
        item === null ||
        !("label" in item) ||
        !("agent_id" in item)
      )
        return [];
      if (
        typeof item.label !== "string" ||
        (item.agent_id !== null && typeof item.agent_id !== "string")
      )
        return [];
      return [{ label: item.label, agentId: item.agent_id }];
    });
  } catch {
    // Old stored chips have titles only. Offer a choice only when it identifies
    // exactly one lane; ambiguity must not send a new message or choose a sibling.
    return raw.split("|").flatMap((label): RouteChoice[] => {
      if (label === "New task") return [{ label, agentId: null }];
      if (!label.startsWith("Continue: ")) return [];
      const matches = agents.filter((agent) => agent.title === label.slice(10));
      return matches.length === 1 ? [{ label, agentId: matches[0].id }] : [];
    });
  }
}

function routingLabel(intent: string, title: string): string | null {
  if (intent === "new_request") {
    return `→ new task: ${title}`;
  }
  if (intent === "follow_up") {
    return `→ continues: ${title}`;
  }
  if (intent === "steer") {
    return "→ steer";
  }
  if (intent === "answer") {
    return "→ answer";
  }
  return null;
}

function startNew(messageId: string): void {
  void call("messages.reroute", { message_id: messageId, new: true }).catch(
    () => undefined,
  );
}

function moveTo(messageId: string, agentId: string): void {
  void call("messages.reroute", {
    message_id: messageId,
    agent_id: agentId,
  }).catch(() => undefined);
}
