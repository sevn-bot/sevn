import { createElement } from "react";
import { afterEach, expect, test } from "vitest";
import {
  loadDashboard,
  requestParams,
  rpcError,
  startHarness,
} from "../chat/host.ts";

const now = new Date();
const today = now.toISOString().slice(0, 10);

function iso(offsetMs: number): string {
  return new Date(now.getTime() - offsetMs).toISOString();
}

function days(): string[] {
  const out: string[] = [];
  for (let offset = 13; offset >= 0; offset -= 1) {
    out.push(
      new Date(now.getTime() - offset * 86_400_000).toISOString().slice(0, 10),
    );
  }
  return out;
}

const hour = 3_600_000;

function bot(id: string, name: string, status: string, extra = {}) {
  return {
    id,
    name,
    title: "",
    avatar: "",
    paused: false,
    status,
    open_agents: status === "quiet" ? 0 : 1,
    waiting: 0,
    ...extra,
  };
}

function overview(extra: Record<string, unknown> = {}) {
  return {
    as_of: now.toISOString(),
    days: days(),
    kpis: [],
    bots: [],
    waiting: [],
    finished: [],
    activity: [],
    ...extra,
  };
}

const full = overview({
  bots: [
    bot("bot_atlas", "Atlas", "running"),
    bot("bot_nimbus", "Nimbus", "waiting", { waiting: 2 }),
    bot("bot_quiet", "Quiet", "quiet"),
  ],
  waiting: [
    {
      id: "pend_old",
      kind: "question",
      text: "Which subject line?",
      name: "user.ask",
      args: { question: "Which subject line?" },
      bot_id: "bot_nimbus",
      bot_name: "Nimbus",
      agent_id: "agent_news",
      agent_title: "Newsletter",
      turn_id: "turn_news",
      created_at: iso(30 * hour),
    },
    {
      id: "pend_new",
      kind: "approval",
      text: "shell.run",
      name: "shell.run",
      args: { command: "make test" },
      bot_id: "bot_nimbus",
      bot_name: "Nimbus",
      agent_id: "agent_build",
      agent_title: "Fix the build",
      turn_id: "turn_build",
      created_at: iso(5 * 60_000),
    },
  ],
  finished: [
    {
      turn_id: "turn_failed",
      status: "failed",
      preview: "This turn failed.",
      bot_id: "bot_atlas",
      bot_name: "Atlas",
      agent_id: "agent_scan",
      agent_title: "Pricing scan",
      finished_at: iso(60_000),
    },
    {
      turn_id: "turn_done",
      status: "done",
      preview: "3 competitors changed prices",
      bot_id: "bot_nimbus",
      bot_name: "Nimbus",
      agent_id: "agent_news",
      agent_title: "Newsletter",
      finished_at: iso(2 * hour),
    },
  ],
  kpis: [
    {
      key: "spend_today",
      label: "Spend today",
      value: 0.8,
      unit: "USD",
      source: "turn usage priced with genai-prices",
      note: "turns finished since 00:00 UTC; routing calls not included",
      unpriced: 1,
      subscription: 2,
    },
    {
      key: "tokens_today",
      label: "Tokens today",
      value: 15400,
      unit: "tokens",
      source: "turn usage (input + output)",
      note: "turns finished since 00:00 UTC",
    },
    {
      key: "waiting",
      label: "Waiting on you",
      value: 2,
      unit: "",
      source: "pending requests",
      note: "approvals and questions",
    },
    {
      key: "running",
      label: "Running turns",
      value: 1,
      unit: "",
      source: "turns",
      note: "host limit 3",
      limit: 3,
    },
  ],
  activity: [
    { bot_id: "bot_atlas", day: today, turns: 3, cost_usd: 0.5, unpriced: 1 },
  ],
});

afterEach(async () => {
  const testing = await import("@testing-library/react");
  testing.cleanup();
  window.history.pushState(null, "", "/");
  try {
    window.localStorage.clear();
  } catch {
    // Storage can be unavailable; the dashboard works without it.
  }
});

test("empty fleet says nothing needs you", async () => {
  const harness = await startHarness({ "fleet.overview": overview() });
  const testing = await import("@testing-library/react");
  try {
    const Dashboard = await loadDashboard();
    testing.render(createElement(Dashboard));
    await testing.screen.findByText("Nothing needs you right now");
    await testing.screen.findByText(/^Updated \d{2}:\d{2}$/);
    await testing.screen.findByText("No finished turns yet");
  } finally {
    harness.stop();
  }
});

test("waiting cards show the question, age and an approval", async () => {
  const harness = await startHarness({ "fleet.overview": full });
  const testing = await import("@testing-library/react");
  try {
    const Dashboard = await loadDashboard();
    testing.render(createElement(Dashboard));
    const question = await testing.screen.findByText("Which subject line?");
    const card = question.closest("li");
    expect(card?.getAttribute("data-stale")).toBe("true");
    expect(card?.textContent).toContain("Nimbus");
    expect(card?.textContent).toContain("Newsletter");
    expect(card?.textContent).toContain("waiting 1d");
    await testing.screen.findByRole("button", { name: "Approve" });
    const approval = (await testing.screen.findByText("Fix the build")).closest(
      "li",
    );
    expect(approval?.getAttribute("data-stale")).toBe("false");
    expect(approval?.textContent).toContain("waiting 5m");
  } finally {
    harness.stop();
  }
});

test("open goes to the agent thread", async () => {
  const harness = await startHarness({ "fleet.overview": full });
  const testing = await import("@testing-library/react");
  try {
    const Dashboard = await loadDashboard();
    testing.render(createElement(Dashboard));
    const question = await testing.screen.findByText("Which subject line?");
    const card = question.closest("li");
    const open = card?.querySelector("button[data-open]");
    expect(open).not.toBeNull();
    (open as HTMLButtonElement).click();
    expect(window.location.pathname).toBe("/bots/bot_nimbus/agents/agent_news");
  } finally {
    harness.stop();
  }
});

test("finished marks failures and filters by bot", async () => {
  const harness = await startHarness({ "fleet.overview": full });
  const testing = await import("@testing-library/react");
  try {
    const Dashboard = await loadDashboard();
    testing.render(createElement(Dashboard));
    const failed = (
      await testing.screen.findByText("This turn failed.")
    ).closest("li");
    expect(failed?.getAttribute("data-status")).toBe("failed");
    expect(failed?.textContent).toContain("Failed");
    const filter = await testing.screen.findByRole("button", {
      name: "Only Atlas",
    });
    filter.click();
    await testing.waitFor(() => {
      const calls = requestParams(harness.requests, "fleet.overview");
      expect(calls.at(-1)?.bot_id).toBe("bot_atlas");
    });
  } finally {
    harness.stop();
  }
});

test("activity grid shades turns and marks idle bots", async () => {
  const harness = await startHarness({ "fleet.overview": full });
  const testing = await import("@testing-library/react");
  try {
    const Dashboard = await loadDashboard();
    testing.render(createElement(Dashboard));
    const cell = await testing.screen.findByTitle(`Atlas ${today}: 3 turns`);
    expect(cell.getAttribute("data-turns")).toBe("3");
    const rows = document.querySelectorAll("tr[data-bot]");
    expect(rows.length).toBe(3);
    const quiet = document.querySelector('tr[data-bot="bot_quiet"]');
    expect(quiet?.getAttribute("data-idle")).toBe("true");
    const atlas = document.querySelector('tr[data-bot="bot_atlas"]');
    expect(atlas?.getAttribute("data-idle")).toBe("false");
  } finally {
    harness.stop();
  }
});

test("header shows bot status and can be hidden", async () => {
  const harness = await startHarness({ "fleet.overview": full });
  const testing = await import("@testing-library/react");
  try {
    const Dashboard = await loadDashboard();
    const first = testing.render(createElement(Dashboard));
    const atlas = await testing.screen.findByLabelText("Atlas: running");
    expect(atlas.getAttribute("data-status")).toBe("running");
    await testing.screen.findByLabelText("Nimbus: waiting");
    const hide = await testing.screen.findByRole("button", {
      name: "Hide header",
    });
    hide.click();
    await testing.screen.findByRole("button", { name: "Show header" });
    expect(testing.screen.queryByLabelText("Atlas: running")).toBeNull();
    first.unmount();
    testing.render(createElement(Dashboard));
    await testing.screen.findByRole("button", { name: "Show header" });
  } finally {
    harness.stop();
  }
});

test("a fleet event refreshes the overview", async () => {
  const harness = await startHarness({ "fleet.overview": overview() });
  const testing = await import("@testing-library/react");
  try {
    const Dashboard = await loadDashboard();
    testing.render(createElement(Dashboard));
    await testing.screen.findByText("Nothing needs you right now");
    const before = requestParams(harness.requests, "fleet.overview").length;
    harness.event("pending.created", { pending_id: "pend_x" });
    await testing.waitFor(() => {
      expect(
        requestParams(harness.requests, "fleet.overview").length,
      ).toBeGreaterThan(before);
    });
    const settled = requestParams(harness.requests, "fleet.overview").length;
    harness.event("memory.changed", { id: "mem_x" });
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(requestParams(harness.requests, "fleet.overview").length).toBe(
      settled,
    );
  } finally {
    harness.stop();
  }
});

test("KPI strip shows spend, tokens, waiting and running with sources", async () => {
  const harness = await startHarness({ "fleet.overview": full });
  const testing = await import("@testing-library/react");
  try {
    const Dashboard = await loadDashboard();
    testing.render(createElement(Dashboard));
    const spend = await testing.screen.findByTestId("kpi-spend_today");
    expect(spend.textContent).toContain("Spend today");
    expect(spend.textContent).toContain("$0.80");
    expect(spend.textContent).toContain("1 unpriced");
    expect(spend.textContent).toContain("2 on subscription");
    expect(spend.getAttribute("title")).toContain("genai-prices");
    expect(spend.getAttribute("title")).toContain("routing calls not included");
    const tokens = await testing.screen.findByTestId("kpi-tokens_today");
    expect(tokens.textContent).toContain("15.4k");
    const running = await testing.screen.findByTestId("kpi-running");
    expect(running.textContent).toContain("1 / 3");
    const waiting = await testing.screen.findByTestId("kpi-waiting");
    expect(waiting.textContent).toContain("2");
  } finally {
    harness.stop();
  }
});

test("a KPI with no value says unavailable", async () => {
  const harness = await startHarness({
    "fleet.overview": overview({
      kpis: [
        {
          key: "spend_today",
          label: "Spend today",
          value: null,
          unit: "USD",
          source: "turn usage",
          note: "",
        },
      ],
    }),
  });
  const testing = await import("@testing-library/react");
  try {
    const Dashboard = await loadDashboard();
    testing.render(createElement(Dashboard));
    const spend = await testing.screen.findByTestId("kpi-spend_today");
    expect(spend.textContent).toContain("unavailable");
    expect(spend.textContent).not.toContain("$");
  } finally {
    harness.stop();
  }
});

test("activity grid switches to cost", async () => {
  const harness = await startHarness({ "fleet.overview": full });
  const testing = await import("@testing-library/react");
  try {
    const Dashboard = await loadDashboard();
    testing.render(createElement(Dashboard));
    await testing.screen.findByTitle(`Atlas ${today}: 3 turns`);
    const cost = await testing.screen.findByRole("button", { name: "Cost" });
    cost.click();
    const cell = await testing.screen.findByTitle(
      `Atlas ${today}: $0.50, 1 unpriced`,
    );
    expect(cell.getAttribute("data-cost")).toBe("0.5");
    expect(cost.getAttribute("aria-pressed")).toBe("true");
  } finally {
    harness.stop();
  }
});

test("a failed refresh keeps the data and says so", async () => {
  const harness = await startHarness({
    "fleet.overview": (_params, nth) =>
      nth === 1 ? full : rpcError("internal", "host busy"),
  });
  const testing = await import("@testing-library/react");
  try {
    const Dashboard = await loadDashboard();
    testing.render(createElement(Dashboard));
    await testing.screen.findByText("Which subject line?");
    expect(testing.screen.queryByText("refresh failed")).toBeNull();
    harness.event("turn.finished", { turn_id: "turn_x" });
    await testing.screen.findByText("refresh failed");
    expect(testing.screen.getByText("Which subject line?")).not.toBeNull();
  } finally {
    harness.stop();
  }
});

test("the bot filter clears when that bot is gone", async () => {
  const withoutAtlas = {
    ...full,
    bots: full.bots.filter((item) => item.id !== "bot_atlas"),
  };
  const harness = await startHarness({
    "fleet.overview": (params) =>
      params.bot_id === "bot_atlas" ? withoutAtlas : full,
  });
  const testing = await import("@testing-library/react");
  try {
    const Dashboard = await loadDashboard();
    testing.render(createElement(Dashboard));
    (await testing.screen.findByRole("button", { name: "Only Atlas" })).click();
    await testing.waitFor(() => {
      const calls = requestParams(harness.requests, "fleet.overview");
      expect(calls.at(-1)?.bot_id).toBeUndefined();
      expect(calls.some((call) => call.bot_id === "bot_atlas")).toBe(true);
    });
    const all = await testing.screen.findByRole("button", { name: "All bots" });
    await testing.waitFor(() => {
      expect(all.getAttribute("aria-pressed")).toBe("true");
    });
  } finally {
    harness.stop();
  }
});
