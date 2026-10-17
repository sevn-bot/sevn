import { createElement } from "react";
import { expect } from "vitest";
import { red } from "../support/red.ts";
import { loadChat, requestParams, startHarness } from "./host.ts";

const test = red("W6");
const botId = "bot_nimbus";

function textMessage(id: string, text: string): Record<string, unknown> {
  return {
    id,
    role: "user",
    parts: [{ type: "text", text }],
  };
}

test("streams ticks into the current assistant bubble", async () => {
  const harness = await startHarness({
    "messages.list": {
      messages: [textMessage("msg_user", "hi")],
      next_cursor: null,
    },
    "agents.list": { agents: [] },
    "pending.list": { pending: [] },
  });
  const testing = await import("@testing-library/react");
  try {
    const Chat = await loadChat();
    testing.render(createElement(Chat, { botId }));
    await testing.screen.findByText("hi");
    harness.tick("turn.delta", {
      turn_id: "turn_1",
      agent_id: "agent_1",
      text: "hel",
    });
    harness.tick("turn.delta", {
      turn_id: "turn_1",
      agent_id: "agent_1",
      text: "lo",
    });
    await testing.screen.findByText("hello", { exact: false });
  } finally {
    testing.cleanup();
    harness.stop();
  }
});

test("shows approval card and sends approve", async () => {
  const harness = await startHarness({
    "messages.list": { messages: [], next_cursor: null },
    "agents.list": { agents: [] },
    "pending.list": {
      pending: [{ id: "pend_1", kind: "approval", tool: "shell" }],
    },
    "pending.answer": {},
  });
  const testing = await import("@testing-library/react");
  try {
    const Chat = await loadChat();
    testing.render(createElement(Chat, { botId }));
    await testing.screen.findByRole("button", { name: "Deny" });
    const approve = await testing.screen.findByRole("button", {
      name: "Approve",
    });
    approve.click();
    await testing.waitFor(() => {
      const params = requestParams(harness.requests, "pending.answer");
      expect(params.length).toBeGreaterThan(0);
    });
    const params = requestParams(harness.requests, "pending.answer").at(-1);
    expect(params?.pending_id).toBe("pend_1");
    expect(params?.answer).toBe("approve");
    expect(typeof params?.op_id).toBe("string");
    expect(String(params?.op_id).length).toBeGreaterThan(0);
  } finally {
    testing.cleanup();
    harness.stop();
  }
});

test("shows lanes with title and status", async () => {
  const harness = await startHarness({
    "messages.list": { messages: [], next_cursor: null },
    "pending.list": { pending: [] },
    "agents.list": {
      agents: [
        { id: "agent_1", title: "Invoice fix", status: "idle" },
        { id: "agent_2", title: "Trip plan", status: "running" },
      ],
    },
  });
  const testing = await import("@testing-library/react");
  try {
    const Chat = await loadChat();
    testing.render(createElement(Chat, { botId }));
    await testing.screen.findByText("Invoice fix");
    await testing.screen.findByText("idle");
    await testing.screen.findByText("Trip plan");
    await testing.screen.findByText("running");
  } finally {
    testing.cleanup();
    harness.stop();
  }
});

test("loads older messages on scroll", async () => {
  const page = Array.from({ length: 50 }, (_item, index) =>
    textMessage(
      `msg_${index}`,
      index === 0 ? "newest-note" : `filler-${index}`,
    ),
  );
  const harness = await startHarness({
    "agents.list": { agents: [] },
    "pending.list": { pending: [] },
    "messages.list": (params) => {
      if (params.cursor === "page-2") {
        return {
          messages: [textMessage("msg_old", "older-note")],
          next_cursor: null,
        };
      }
      return { messages: page, next_cursor: "page-2" };
    },
  });
  const testing = await import("@testing-library/react");
  try {
    const Chat = await loadChat();
    testing.render(createElement(Chat, { botId }));
    await testing.screen.findByText("newest-note");
    const log = await testing.screen.findByRole("log");
    log.scrollTop = 0;
    testing.fireEvent.scroll(log);
    await testing.screen.findByText("older-note");
    const cursors = requestParams(harness.requests, "messages.list").map(
      (params) => params.cursor,
    );
    expect(cursors).toContain("page-2");
  } finally {
    testing.cleanup();
    harness.stop();
  }
});
