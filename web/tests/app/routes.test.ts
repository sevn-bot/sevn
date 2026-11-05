import { expect, test } from "vitest";
import { agentPath, routeFromPath } from "../../src/app/routes.ts";

test("home, bot and agent routes", () => {
  expect(routeFromPath("/")).toEqual({
    hostId: null,
    botId: null,
    agentId: null,
  });
  expect(routeFromPath("/bots/bot_a")).toEqual({
    hostId: null,
    botId: "bot_a",
    agentId: null,
  });
  expect(routeFromPath("/bots/bot_a/agents/agent_b")).toEqual({
    hostId: null,
    botId: "bot_a",
    agentId: "agent_b",
  });
  expect(routeFromPath("/bots/")).toEqual({
    hostId: null,
    botId: null,
    agentId: null,
  });
  expect(routeFromPath("/bots/bot_a/agents/")).toEqual({
    hostId: null,
    botId: null,
    agentId: null,
  });
});

test("agent paths are encoded", () => {
  expect(agentPath("bot a", "agent/b")).toBe("/bots/bot%20a/agents/agent%2Fb");
  expect(routeFromPath(agentPath("bot a", "agent/b"))).toEqual({
    hostId: null,
    botId: "bot a",
    agentId: "agent/b",
  });
});

test("brief and share routes", async () => {
  const routes = await import("../../src/app/routes.ts");
  expect(routes.isBriefPath("/brief")).toBe(true);
  expect(routes.isBriefPath("/briefing")).toBe(false);
  expect(routes.shareFromPath("/share/shr_1/abc-DEF_9")).toEqual({
    shareId: "shr_1",
    secret: "abc-DEF_9",
  });
  expect(routes.shareFromPath("/share/shr_1")).toBeNull();
  expect(routes.shareFromPath("/share/shr_1/x/data")).toBeNull();
  expect(routes.shareFromPath("/bots/x")).toBeNull();
});
