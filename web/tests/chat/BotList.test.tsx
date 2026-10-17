import { createElement } from "react";
import { expect } from "vitest";
import { red } from "../support/red.ts";
import { loadBotList, requestParams, startHarness } from "./host.ts";

const test = red("W6");

test("lists bots", async () => {
  const harness = await startHarness({
    "bots.list": {
      bots: [
        { id: "bot_nimbus", name: "Nimbus", runtime: "pydantic_ai" },
        { id: "bot_echo", name: "Echo", runtime: "pydantic_ai" },
      ],
    },
  });
  const testing = await import("@testing-library/react");
  try {
    const BotList = await loadBotList();
    testing.render(createElement(BotList));
    await testing.screen.findByText("Nimbus");
    await testing.screen.findByText("Echo");
  } finally {
    testing.cleanup();
    harness.stop();
  }
});

test("create bot dialog submits name and runtime", async () => {
  const harness = await startHarness({
    "bots.list": { bots: [] },
    "bots.create": {
      id: "bot_created",
      name: "Nimbus",
      runtime: "pydantic_ai",
    },
  });
  const testing = await import("@testing-library/react");
  try {
    const BotList = await loadBotList();
    testing.render(createElement(BotList));
    const open = await testing.screen.findByRole("button", {
      name: "Create bot",
    });
    open.click();
    const name = await testing.screen.findByRole("textbox", { name: "Name" });
    testing.fireEvent.change(name, { target: { value: "Nimbus" } });
    const runtime = await testing.screen.findByRole("combobox", {
      name: "Runtime",
    });
    testing.fireEvent.change(runtime, { target: { value: "pydantic_ai" } });
    const submit = await testing.screen.findByRole("button", {
      name: "Create",
    });
    submit.click();
    await testing.waitFor(() => {
      const params = requestParams(harness.requests, "bots.create");
      expect(params.length).toBeGreaterThan(0);
    });
    const params = requestParams(harness.requests, "bots.create").at(-1);
    expect(params?.name).toBe("Nimbus");
    expect(params?.runtime).toBe("pydantic_ai");
    expect(typeof params?.op_id).toBe("string");
    expect(String(params?.op_id).length).toBeGreaterThan(0);
  } finally {
    testing.cleanup();
    harness.stop();
  }
});
