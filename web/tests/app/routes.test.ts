import { expect, test } from "vitest";
import { agentPath, routeFromPath } from "../../src/app/routes.ts";

test("home, bot and agent routes", () => {
  expect(routeFromPath("/")).toEqual({ botId: null, agentId: null });
  expect(routeFromPath("/bots/bot_a")).toEqual({
    botId: "bot_a",
    agentId: null,
  });
  expect(routeFromPath("/bots/bot_a/agents/agent_b")).toEqual({
    botId: "bot_a",
    agentId: "agent_b",
  });
  expect(routeFromPath("/bots/")).toEqual({ botId: null, agentId: null });
  expect(routeFromPath("/bots/bot_a/agents/")).toEqual({
    botId: null,
    agentId: null,
  });
});

test("agent paths are encoded", () => {
  expect(agentPath("bot a", "agent/b")).toBe("/bots/bot%20a/agents/agent%2Fb");
  expect(routeFromPath(agentPath("bot a", "agent/b"))).toEqual({
    botId: "bot a",
    agentId: "agent/b",
  });
});
