import { createElement } from "react";
import { afterEach, expect, test } from "vitest";
import { loadDashboard, requestParams, startHarness } from "../chat/host.ts";

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
    metrics: [],
    host: {
      as_of: now.toISOString(),
      version: "0.0.0",
      queued_jobs: 0,
      running_turns: 0,
      max_running_turns: 3,
      ollama: {
        configured: false,
        reachable: null,
        models: [],
        loaded: [],
        error: null,
        checked_at: null,
      },
    },
    upcoming: [],
    projection_7d_usd: 0,
    projection_unpriced: 0,
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
      options: [
        { id: "opt_1", label: "Is your fleet out of control?" },
        { id: "opt_2", label: "Three dashboards" },
      ],
      priority: "high",
      due_by: new Date(now.getTime() + 3 * hour).toISOString(),
      blocking: true,
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
      options: [],
      priority: "normal",
      due_by: null,
      blocking: true,
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

function question(extra: Record<string, unknown>) {
  return {
    id: "pend_q",
    kind: "question",
    text: "Which day?",
    name: "user.ask",
    args: {},
    options: [],
    priority: "normal",
    due_by: null,
    blocking: true,
    bot_id: "bot_nimbus",
    bot_name: "Nimbus",
    agent_id: "agent_news",
    agent_title: "Newsletter",
    turn_id: "turn_news",
    created_at: iso(60_000),
    ...extra,
  };
}

test("a question card answers with one click on an option", async () => {
  const harness = await startHarness({
    "fleet.overview": full,
    "pending.answer": { id: "pend_old", status: "resolved", job_id: "job_1" },
  });
  const testing = await import("@testing-library/react");
  try {
    const Dashboard = await loadDashboard();
    testing.render(createElement(Dashboard));
    const option = await testing.screen.findByRole("button", {
      name: "Three dashboards",
    });
    option.click();
    await testing.waitFor(() => {
      expect(requestParams(harness.requests, "pending.answer").length).toBe(1);
    });
    const sent = requestParams(harness.requests, "pending.answer")[0];
    expect(sent?.pending_id).toBe("pend_old");
    expect(sent?.option_id).toBe("opt_2");
    expect(sent?.answer).toBeUndefined();
    expect(sent?.text).toBeUndefined();
  } finally {
    harness.stop();
  }
});

test("a question card answers with typed text", async () => {
  const harness = await startHarness({
    "fleet.overview": overview({ waiting: [question({})] }),
    "pending.answer": { id: "pend_q", status: "resolved", job_id: "job_1" },
  });
  const testing = await import("@testing-library/react");
  try {
    const Dashboard = await loadDashboard();
    testing.render(createElement(Dashboard));
    const field = await testing.screen.findByRole("textbox", {
      name: "Answer Which day?",
    });
    testing.fireEvent.change(field, { target: { value: "Tuesday at 10" } });
    (
      await testing.screen.findByRole("button", { name: "Send answer" })
    ).click();
    await testing.waitFor(() => {
      expect(requestParams(harness.requests, "pending.answer").length).toBe(1);
    });
    const sent = requestParams(harness.requests, "pending.answer")[0];
    expect(sent?.pending_id).toBe("pend_q");
    expect(sent?.text).toBe("Tuesday at 10");
    expect(sent?.option_id).toBeUndefined();
  } finally {
    harness.stop();
  }
});

test("question cards show priority, due time and non-blocking", async () => {
  const harness = await startHarness({
    "fleet.overview": overview({
      waiting: [
        question({
          id: "pend_due",
          text: "Due soon",
          priority: "high",
          due_by: new Date(now.getTime() + 3 * hour + 60_000).toISOString(),
        }),
        question({
          id: "pend_late",
          text: "Overdue",
          due_by: new Date(now.getTime() - 2 * hour - 60_000).toISOString(),
        }),
        question({
          id: "pend_fyi",
          text: "Just checking",
          priority: "low",
          blocking: false,
        }),
      ],
    }),
  });
  const testing = await import("@testing-library/react");
  try {
    const Dashboard = await loadDashboard();
    testing.render(createElement(Dashboard));
    const due = (await testing.screen.findByText("Due soon")).closest("li");
    expect(due?.textContent).toContain("high");
    expect(due?.textContent).toContain("due in 3h");
    expect(due?.getAttribute("data-priority")).toBe("high");
    const late = (await testing.screen.findByText("Overdue")).closest("li");
    expect(late?.textContent).toContain("overdue 2h");
    expect(late?.getAttribute("data-overdue")).toBe("true");
    const fyi = (await testing.screen.findByText("Just checking")).closest(
      "li",
    );
    expect(fyi?.textContent).toContain("not blocking");
    expect(fyi?.textContent).toContain("low");
    const order = [...document.querySelectorAll("li[data-pending]")].map(
      (node) => node.getAttribute("data-pending"),
    );
    expect(order).toEqual(["pend_due", "pend_late", "pend_fyi"]);
  } finally {
    harness.stop();
  }
});

function routine(extra: Record<string, unknown>) {
  return {
    id: "rtn_scan",
    bot_id: "bot_atlas",
    bot_name: "Atlas",
    name: "Mentions scan",
    schedule: "0 */2 * * *",
    timezone: "UTC",
    status: "active",
    paused_reason: null,
    next_run: new Date(now.getTime() + 2 * hour).toISOString(),
    last_run: iso(2 * hour),
    last_outcome: "ok",
    last_useful_at: iso(3 * 24 * hour),
    runs_30d: 12,
    cost_30d_usd: 0.48,
    cost_per_run_usd: 0.04,
    unpriced_runs_30d: 0,
    runs_next_7d: 84,
    candidate_to_cancel: false,
    ...extra,
  };
}

const withRoutines = overview({
  bots: [bot("bot_atlas", "Atlas", "idle")],
  upcoming: [
    routine({}),
    routine({
      id: "rtn_weekly",
      name: "Weekly report",
      next_run: new Date(now.getTime() + 3 * 24 * hour).toISOString(),
    }),
    routine({
      id: "rtn_stale",
      name: "Stale scan",
      next_run: new Date(now.getTime() + 5 * hour).toISOString(),
      last_outcome: "noop",
      last_useful_at: null,
      cost_per_run_usd: null,
      cost_30d_usd: 0,
      unpriced_runs_30d: 3,
      candidate_to_cancel: true,
    }),
    routine({
      id: "rtn_paused",
      name: "Budget victim",
      status: "paused",
      paused_reason: "budget",
      next_run: null,
    }),
  ],
  projection_7d_usd: 3.36,
  projection_unpriced: 1,
});

test("Upcoming shows the next 24 hours, costs and cancel candidates", async () => {
  const harness = await startHarness({ "fleet.overview": withRoutines });
  const testing = await import("@testing-library/react");
  try {
    const Dashboard = await loadDashboard();
    testing.render(createElement(Dashboard));
    const scan = (await testing.screen.findByText("Mentions scan")).closest(
      "li",
    );
    expect(scan?.textContent).toContain("next in 2h");
    expect(scan?.textContent).toContain("$0.04/run");
    expect(scan?.textContent).toContain("$0.48 in 30 days");
    expect(scan?.textContent).toContain("0 */2 * * * UTC");
    expect(scan?.textContent).toContain("useful 3d ago");
    const stale = (await testing.screen.findByText("Stale scan")).closest("li");
    expect(stale?.getAttribute("data-candidate")).toBe("true");
    expect(stale?.textContent).toContain("candidate to cancel");
    expect(stale?.textContent).toContain("3 unpriced");
    expect(stale?.textContent).toContain("nothing useful in 30 days");
    expect(testing.screen.queryByText("Weekly report")).toBeNull();
    const paused = (await testing.screen.findByText("Budget victim")).closest(
      "li",
    );
    expect(paused?.textContent).toContain("paused by budget");
    const footer = await testing.screen.findByTestId("projection");
    expect(footer.textContent).toContain("Next 7 days");
    expect(footer.textContent).toContain("$3.36");
    expect(footer.textContent).toContain("1 routine unpriced");
    (
      await testing.screen.findByRole("button", { name: "Show all (4)" })
    ).click();
    await testing.screen.findByText("Weekly report");
  } finally {
    harness.stop();
  }
});

test("pause, resume and a confirmed cancel", async () => {
  const harness = await startHarness({
    "fleet.overview": withRoutines,
    "routines.pause": routine({ status: "paused" }),
    "routines.resume": routine({}),
    "routines.cancel": routine({ status: "cancelled" }),
  });
  const testing = await import("@testing-library/react");
  try {
    const Dashboard = await loadDashboard();
    testing.render(createElement(Dashboard));
    const scan = (await testing.screen.findByText("Mentions scan")).closest(
      "li",
    );
    const within = testing.within(scan as HTMLElement);
    within.getByRole("button", { name: "Pause" }).click();
    await testing.waitFor(() => {
      expect(
        requestParams(harness.requests, "routines.pause")[0]?.routine_id,
      ).toBe("rtn_scan");
    });
    const paused = (await testing.screen.findByText("Budget victim")).closest(
      "li",
    );
    testing
      .within(paused as HTMLElement)
      .getByRole("button", { name: "Resume" })
      .click();
    await testing.waitFor(() => {
      expect(
        requestParams(harness.requests, "routines.resume")[0]?.routine_id,
      ).toBe("rtn_paused");
    });
    within.getByRole("button", { name: "Cancel" }).click();
    (await within.findByRole("button", { name: "Keep it" })).click();
    await within.findByRole("button", { name: "Cancel" });
    expect(within.queryByRole("button", { name: "Yes, cancel" })).toBeNull();
    expect(requestParams(harness.requests, "routines.cancel")).toEqual([]);
    within.getByRole("button", { name: "Cancel" }).click();
    (await within.findByRole("button", { name: "Yes, cancel" })).click();
    await testing.waitFor(() => {
      expect(
        requestParams(harness.requests, "routines.cancel")[0]?.routine_id,
      ).toBe("rtn_scan");
    });
  } finally {
    harness.stop();
  }
});

test("a new routine is created from the form", async () => {
  const harness = await startHarness({
    "fleet.overview": withRoutines,
    "routines.create": routine({ id: "rtn_new", name: "Morning brief" }),
  });
  const testing = await import("@testing-library/react");
  try {
    const Dashboard = await loadDashboard();
    testing.render(createElement(Dashboard));
    (await testing.screen.findByText("New routine")).click();
    const change = (label: string, value: string) => {
      testing.fireEvent.change(testing.screen.getByLabelText(label), {
        target: { value },
      });
    };
    change("Bot", "bot_atlas");
    change("Name", "Morning brief");
    change("Schedule", "30 7 * * 1-5");
    change("Timezone", "Europe/Amsterdam");
    change("Prompt", "Summarize what needs me today.");
    (
      await testing.screen.findByRole("button", { name: "Create routine" })
    ).click();
    await testing.waitFor(() => {
      expect(requestParams(harness.requests, "routines.create").length).toBe(1);
    });
    const sent = requestParams(harness.requests, "routines.create")[0];
    expect(sent).toMatchObject({
      bot_id: "bot_atlas",
      name: "Morning brief",
      schedule: "30 7 * * 1-5",
      timezone: "Europe/Amsterdam",
      text: "Summarize what needs me today.",
    });
  } finally {
    harness.stop();
  }
});

test("the spend tile shows the budget level", async () => {
  const harness = await startHarness({
    "fleet.overview": overview({
      kpis: [
        {
          key: "spend_today",
          label: "Spend today",
          value: 0.85,
          unit: "USD",
          source: "turn usage",
          note: "",
          budget_usd: 1,
          level: "warn",
        },
      ],
    }),
  });
  const testing = await import("@testing-library/react");
  try {
    const Dashboard = await loadDashboard();
    testing.render(createElement(Dashboard));
    const spend = await testing.screen.findByTestId("kpi-spend_today");
    expect(spend.getAttribute("data-level")).toBe("warn");
    expect(spend.textContent).toContain("of $1.00 a day");
  } finally {
    harness.stop();
  }
});

test("a routine event refreshes the overview", async () => {
  const harness = await startHarness({ "fleet.overview": overview() });
  const testing = await import("@testing-library/react");
  try {
    const Dashboard = await loadDashboard();
    testing.render(createElement(Dashboard));
    await testing.screen.findByText("Nothing needs you right now");
    const before = requestParams(harness.requests, "fleet.overview").length;
    harness.event("routine.updated", { routine_id: "rtn_scan" });
    await testing.waitFor(() => {
      expect(
        requestParams(harness.requests, "fleet.overview").length,
      ).toBeGreaterThan(before);
    });
  } finally {
    harness.stop();
  }
});
