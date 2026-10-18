import { createElement } from "react";
import { expect } from "vitest";
import {
  loadMemoriesPanel,
  requestParams,
  startHarness,
} from "../chat/host.ts";
import { red } from "../support/red.ts";

const test = red("W8");
const botId = "bot_nimbus";

const listed = {
  memories: [
    {
      id: "mem_1",
      text: "Prefers morning meetings",
      tier: "recall",
      origin: "user",
    },
  ],
};

function replies(
  extra: Record<string, Record<string, unknown>>,
): Record<string, Record<string, unknown>> {
  return { "memories.list": listed, ...extra };
}

test("lists", async () => {
  const harness = await startHarness(replies({}));
  const testing = await import("@testing-library/react");
  try {
    const Panel = await loadMemoriesPanel();
    testing.render(createElement(Panel, { botId }));
    await testing.screen.findByText("Prefers morning meetings");
    expect(
      requestParams(harness.requests, "memories.list").length,
    ).toBeGreaterThan(0);
  } finally {
    testing.cleanup();
    harness.stop();
  }
});

test("pins", async () => {
  const harness = await startHarness(replies({ "memories.pin": {} }));
  const testing = await import("@testing-library/react");
  try {
    const Panel = await loadMemoriesPanel();
    testing.render(createElement(Panel, { botId }));
    const pin = await testing.screen.findByRole("button", { name: "Pin" });
    pin.click();
    await testing.waitFor(() => {
      expect(
        requestParams(harness.requests, "memories.pin").length,
      ).toBeGreaterThan(0);
    });
    const params = requestParams(harness.requests, "memories.pin").at(-1);
    expect(params?.id).toBe("mem_1");
  } finally {
    testing.cleanup();
    harness.stop();
  }
});

test("deletes", async () => {
  const harness = await startHarness(replies({ "memories.delete": {} }));
  const testing = await import("@testing-library/react");
  try {
    const Panel = await loadMemoriesPanel();
    testing.render(createElement(Panel, { botId }));
    const remove = await testing.screen.findByRole("button", {
      name: "Delete",
    });
    remove.click();
    await testing.waitFor(() => {
      expect(
        requestParams(harness.requests, "memories.delete").length,
      ).toBeGreaterThan(0);
    });
    const params = requestParams(harness.requests, "memories.delete").at(-1);
    expect(params?.id).toBe("mem_1");
  } finally {
    testing.cleanup();
    harness.stop();
  }
});
