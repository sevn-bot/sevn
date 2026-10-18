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
  botId,
  choices,
}: {
  botId: string;
  choices: string;
}) {
  const items = choices.split("|").filter((item) => item !== "");
  if (items.length === 0) {
    return null;
  }
  return (
    <div className="flex flex-wrap gap-2">
      {items.map((choice) => (
        <button
          key={choice}
          type="button"
          className="rounded border border-zinc-700 px-2 py-1 text-sm"
          onClick={() => {
            void call("messages.send", { bot_id: botId, text: choice }).catch(
              () => undefined,
            );
          }}
        >
          {choice}
        </button>
      ))}
    </div>
  );
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
