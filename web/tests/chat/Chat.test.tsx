import { createElement } from "react";
import { expect, test } from "vitest";
import { loadChat, requestParams, startHarness } from "./host.ts";

const botId = "bot_nimbus";

function textMessage(id: string, text: string): Record<string, unknown> {
  return {
    id,
    role: "user",
    parts: [{ type: "text", text }],
  };
}

function logTexts(log: HTMLElement): string[] {
  return [...log.querySelectorAll("p")].map((node) => node.textContent ?? "");
}

test("streams ticks into the current assistant bubble", async () => {
  const harness = await startHarness({
    "messages.list": {
      messages: [textMessage("msg_user", "hi")],
      next_cursor: null,
    },
    "agents.list": {
      agents: [{ id: "agent_1", title: "Nimbus", status: "running" }],
    },
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
    "agents.list": {
      agents: [{ id: "agent_1", title: "Nimbus", status: "waiting" }],
    },
    "pending.list": {
      pending: [
        {
          id: "pend_1",
          kind: "approval",
          tool: "shell",
          agent_id: "agent_1",
        },
      ],
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

test("shows newest-first pages oldest-first and prepends older pages", async () => {
  const harness = await startHarness({
    "agents.list": { agents: [] },
    "pending.list": { pending: [] },
    "bots.get": { name: "Nimbus", model: "echo" },
    "messages.list": (params) => {
      if (params.cursor === "page-2") {
        return {
          messages: [
            textMessage("msg_b", "second-oldest"),
            textMessage("msg_a", "oldest-note"),
          ],
          next_cursor: null,
        };
      }
      return {
        messages: [
          textMessage("msg_d", "newest-note"),
          textMessage("msg_c", "middle-note"),
        ],
        next_cursor: "page-2",
      };
    },
  });
  const testing = await import("@testing-library/react");
  try {
    const Chat = await loadChat();
    testing.render(createElement(Chat, { botId }));
    await testing.screen.findByText("newest-note");
    const log = await testing.screen.findByRole("log");
    expect(logTexts(log)).toEqual(["middle-note", "newest-note"]);
    log.scrollTop = 0;
    testing.fireEvent.scroll(log);
    await testing.screen.findByText("oldest-note");
    expect(logTexts(log)).toEqual([
      "oldest-note",
      "second-oldest",
      "middle-note",
      "newest-note",
    ]);
  } finally {
    testing.cleanup();
    harness.stop();
  }
});

test("keeps the latest line in view until the user scrolls up", async () => {
  const harness = await startHarness({
    "agents.list": {
      agents: [{ id: "agent_1", title: "Nimbus", status: "running" }],
    },
    "pending.list": { pending: [] },
    "bots.get": { name: "Nimbus", model: "echo" },
    "messages.list": {
      messages: [textMessage("msg_d", "newest-note")],
      next_cursor: null,
    },
  });
  const testing = await import("@testing-library/react");
  try {
    const Chat = await loadChat();
    testing.render(createElement(Chat, { botId }));
    await testing.screen.findByText("newest-note");
    const log = await testing.screen.findByRole("log");
    Object.defineProperty(log, "scrollHeight", {
      configurable: true,
      get: () => 400,
    });
    Object.defineProperty(log, "clientHeight", {
      configurable: true,
      get: () => 80,
    });
    harness.tick("turn.delta", {
      turn_id: "turn_1",
      agent_id: "agent_1",
      text: "tail",
    });
    await testing.waitFor(() => {
      expect(log.scrollTop).toBe(400);
    });
    log.scrollTop = 10;
    testing.fireEvent.scroll(log);
    harness.tick("turn.delta", {
      turn_id: "turn_1",
      agent_id: "agent_1",
      text: " more",
    });
    await testing.screen.findByText("tail more", { exact: false });
    expect(log.scrollTop).toBe(10);
  } finally {
    testing.cleanup();
    harness.stop();
  }
});

test("does not show or answer another bot's approval", async () => {
  const harness = await startHarness({
    "messages.list": { messages: [], next_cursor: null },
    "agents.list": {
      agents: [{ id: "agent_nimbus", title: "Nimbus lane", status: "waiting" }],
    },
    "pending.list": {
      pending: [
        { id: "pend_own", kind: "own-shell", agent_id: "agent_nimbus" },
        { id: "pend_other", kind: "other-bot", agent_id: "agent_other" },
      ],
    },
    "pending.answer": {},
  });
  const testing = await import("@testing-library/react");
  try {
    const Chat = await loadChat();
    testing.render(createElement(Chat, { botId }));
    await testing.screen.findByText("Nimbus lane");
    await testing.screen.findByText("own-shell");
    const buttons = testing.screen.getAllByRole("button", { name: "Approve" });
    for (const button of buttons) {
      button.click();
    }
    await testing.waitFor(() => {
      expect(requestParams(harness.requests, "pending.answer")).toHaveLength(
        buttons.length,
      );
    });
    const answered = requestParams(harness.requests, "pending.answer").map(
      (params) => params.pending_id,
    );
    expect({
      otherBotVisible: testing.screen.queryByText("other-bot") !== null,
      answered,
    }).toEqual({
      otherBotVisible: false,
      answered: ["pend_own"],
    });
  } finally {
    testing.cleanup();
    harness.stop();
  }
});

test("does not show another bot's streaming tick", async () => {
  const harness = await startHarness({
    "messages.list": { messages: [], next_cursor: null },
    "agents.list": {
      agents: [{ id: "agent_nimbus", title: "Nimbus lane", status: "running" }],
    },
    "pending.list": { pending: [] },
  });
  const testing = await import("@testing-library/react");
  try {
    const Chat = await loadChat();
    testing.render(createElement(Chat, { botId }));
    await testing.screen.findByText("Nimbus lane");
    const log = await testing.screen.findByRole("log");
    harness.tick("turn.delta", {
      turn_id: "turn_other",
      agent_id: "agent_other",
      text: "other-bot-tick",
    });
    harness.tick("turn.delta", {
      turn_id: "turn_own",
      agent_id: "agent_nimbus",
      text: "own-tick",
    });
    await testing.waitFor(() => {
      expect(logTexts(log)).toContain("own-tick");
    });
    expect(logTexts(log)).toEqual(["own-tick"]);
  } finally {
    testing.cleanup();
    harness.stop();
  }
});

test("shows the tool name and arguments on the approval card", async () => {
  const harness = await startHarness({
    "messages.list": { messages: [], next_cursor: null },
    "agents.list": {
      agents: [{ id: "agent_1", title: "Nimbus", status: "waiting" }],
    },
    "pending.list": {
      pending: [
        {
          id: "pend_1",
          turn_id: "turn_1",
          agent_id: "agent_1",
          kind: "approval",
          tool_call_id: "call_0",
          status: "waiting",
          name: "shell",
          args: { command: "echo hi" },
        },
      ],
    },
  });
  const testing = await import("@testing-library/react");
  try {
    const Chat = await loadChat();
    testing.render(createElement(Chat, { botId }));
    const approve = await testing.screen.findByRole("button", {
      name: "Approve",
    });
    const text = approve.closest("div")?.textContent ?? "";
    expect({
      tool: text.includes("shell"),
      args: text.includes("echo hi"),
      text,
    }).toEqual({
      tool: true,
      args: true,
      text,
    });
  } finally {
    testing.cleanup();
    harness.stop();
  }
});

test("an agent link focuses that lane and sends to it", async () => {
  const harness = await startHarness({
    "messages.list": { messages: [], next_cursor: null },
    "agents.list": {
      agents: [
        { id: "agent_1", title: "Newsletter", status: "waiting" },
        { id: "agent_2", title: "Fix the build", status: "idle" },
      ],
    },
    "pending.list": { pending: [] },
    "messages.send": { job_id: "job_1", agent_id: "agent_1" },
  });
  const testing = await import("@testing-library/react");
  try {
    const Chat = await loadChat();
    testing.render(createElement(Chat, { botId, agentId: "agent_1" }));
    await testing.screen.findByText("Sending to Newsletter");
    const lane = document.querySelector('[data-lane="agent_1"]');
    expect(lane?.getAttribute("data-focused")).toBe("true");
    const other = document.querySelector('[data-lane="agent_2"]');
    expect(other?.getAttribute("data-focused")).toBe("false");
    const input = await testing.screen.findByRole("textbox", {
      name: "Message",
    });
    testing.fireEvent.change(input, { target: { value: "Option A" } });
    (await testing.screen.findByRole("button", { name: "Send" })).click();
    await testing.waitFor(() => {
      expect(requestParams(harness.requests, "messages.send").length).toBe(1);
    });
    const sent = requestParams(harness.requests, "messages.send")[0];
    expect(sent?.agent_id).toBe("agent_1");
    expect(sent?.text).toBe("Option A");
  } finally {
    testing.cleanup();
    harness.stop();
  }
});
