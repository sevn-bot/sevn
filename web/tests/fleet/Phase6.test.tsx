import { createElement } from "react";
import { afterEach, expect, test, vi } from "vitest";
import {
  loadBriefPage,
  loadDashboard,
  loadSharePage,
  requestParams,
  startHarness,
} from "../chat/host.ts";

const now = new Date();
const hour = 3_600_000;

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

function host(extra: Record<string, unknown> = {}) {
  return {
    as_of: now.toISOString(),
    version: "0.0.0",
    queued_jobs: 2,
    running_turns: 1,
    max_running_turns: 3,
    ollama: {
      configured: false,
      reachable: null,
      models: [],
      loaded: [],
      error: null,
      checked_at: null,
    },
    ...extra,
  };
}

function metric(extra: Record<string, unknown>) {
  return {
    key: "subscribers",
    label: "Subscribers",
    value: 3210,
    unit: "",
    source: "Buttondown API",
    as_of: iso(10 * 60_000),
    bot_id: "bot_news",
    bot_name: "Newsletter",
    status: "ok",
    delta_24h: 110,
    freshness_minutes: 1440,
    shareable: true,
    reports: [],
    ...extra,
  };
}

function overview(extra: Record<string, unknown> = {}) {
  return {
    as_of: now.toISOString(),
    days: days(),
    kpis: [],
    bots: [
      {
        id: "bot_news",
        name: "Newsletter",
        title: "",
        avatar: "",
        paused: false,
        status: "idle",
        open_agents: 1,
        waiting: 0,
      },
    ],
    metrics: [],
    host: host(),
    upcoming: [],
    projection_7d_usd: 0,
    projection_unpriced: 0,
    waiting: [],
    finished: [],
    activity: [],
    ...extra,
  };
}

afterEach(async () => {
  const testing = await import("@testing-library/react");
  testing.cleanup();
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/");
});

test("metric tiles show value, change, time, source and their state", async () => {
  const harness = await startHarness({
    "fleet.overview": overview({
      metrics: [
        metric({}),
        metric({
          key: "visits",
          label: "Visits",
          value: 1100,
          unit: "/day",
          status: "stale",
          delta_24h: null,
          source: "Plausible",
        }),
        metric({
          key: "revenue",
          label: "Revenue",
          value: null,
          status: "error",
          delta_24h: null,
          source: "Stripe",
        }),
        metric({
          key: "followers",
          label: "Followers",
          value: 12400,
          status: "conflict",
          delta_24h: -20,
          reports: [
            {
              bot_id: "a",
              bot_name: "Social",
              value: 12400,
              as_of: iso(60_000),
              source: "X",
            },
            {
              bot_id: "b",
              bot_name: "Research",
              value: 12380,
              as_of: iso(60_000),
              source: "scrape",
            },
          ],
        }),
      ],
    }),
  });
  const testing = await import("@testing-library/react");
  try {
    const Dashboard = await loadDashboard();
    testing.render(createElement(Dashboard));
    const subscribers = await testing.screen.findByTestId("metric-subscribers");
    expect(subscribers.textContent).toContain("Subscribers");
    expect(subscribers.textContent).toContain("3.2k");
    expect(subscribers.textContent).toContain("+110 in 24h");
    expect(subscribers.textContent).toMatch(/as of \d{2}:\d{2}/);
    expect(subscribers.getAttribute("title")).toContain("Buttondown API");
    expect(subscribers.getAttribute("data-status")).toBe("ok");
    const visits = await testing.screen.findByTestId("metric-visits");
    expect(visits.textContent).toContain("stale");
    expect(visits.textContent).toContain("/day");
    const revenue = await testing.screen.findByTestId("metric-revenue");
    expect(revenue.textContent).toContain("unavailable");
    const followers = await testing.screen.findByTestId("metric-followers");
    expect(followers.textContent).toContain("bots disagree");
    expect(followers.textContent).toContain("Research 12.4k");
    expect(followers.textContent).toContain("-20 in 24h");
  } finally {
    harness.stop();
  }
});

test("the host panel shows Ollama and the queue", async () => {
  const harness = await startHarness({
    "fleet.overview": overview({
      host: host({
        ollama: {
          configured: true,
          reachable: true,
          models: ["llama3.2:3b", "qwen3:8b"],
          loaded: [{ name: "llama3.2:3b", vram_bytes: 2_400_000_000 }],
          error: null,
          checked_at: now.toISOString(),
        },
      }),
    }),
  });
  const testing = await import("@testing-library/react");
  try {
    const Dashboard = await loadDashboard();
    testing.render(createElement(Dashboard));
    const panel = await testing.screen.findByTestId("host-panel");
    expect(panel.textContent).toContain("Ollama reachable");
    expect(panel.textContent).toContain("llama3.2:3b (2.4 GB)");
    expect(panel.textContent).toContain("2 models");
    expect(panel.textContent).toContain("2 queued");
    expect(panel.textContent).toContain("1 / 3 running");
  } finally {
    harness.stop();
  }
});

test("the host panel says when Ollama is down or not set up", async () => {
  const harness = await startHarness({
    "fleet.overview": overview({
      host: host({
        ollama: {
          configured: true,
          reachable: false,
          models: [],
          loaded: [],
          error: "unreachable",
          checked_at: now.toISOString(),
        },
      }),
    }),
  });
  const testing = await import("@testing-library/react");
  try {
    const Dashboard = await loadDashboard();
    testing.render(createElement(Dashboard));
    const panel = await testing.screen.findByTestId("host-panel");
    expect(panel.textContent).toContain("Ollama unreachable");
    expect(panel.getAttribute("data-ollama")).toBe("down");
  } finally {
    harness.stop();
  }
});

test("share links are created once, listed and revoked", async () => {
  const harness = await startHarness({
    "fleet.overview": overview(),
    "shares.list": {
      shares: [
        {
          id: "shr_old",
          label: "For the editor",
          bot_id: "bot_news",
          status: "active",
          created_at: iso(2 * hour),
          expires_at: new Date(now.getTime() + 5 * 24 * hour).toISOString(),
          revoked_at: null,
          last_opened_at: iso(hour),
          opens: 4,
        },
      ],
    },
    "shares.create": {
      share: {
        id: "shr_new",
        label: "Weekly",
        bot_id: null,
        status: "active",
        created_at: now.toISOString(),
        expires_at: new Date(now.getTime() + 7 * 24 * hour).toISOString(),
        revoked_at: null,
        last_opened_at: null,
        opens: 0,
      },
      path: "/share/shr_new/s3cret",
    },
    "shares.revoke": { id: "shr_old", status: "revoked" },
  });
  const testing = await import("@testing-library/react");
  try {
    const Dashboard = await loadDashboard();
    testing.render(createElement(Dashboard));
    (await testing.screen.findByText("Share links")).click();
    const old = (await testing.screen.findByText("For the editor")).closest(
      "li",
    );
    expect(old?.textContent).toContain("Newsletter only");
    expect(old?.textContent).toContain("opened 4 times");
    testing.fireEvent.change(
      await testing.screen.findByLabelText("Link label"),
      {
        target: { value: "Weekly" },
      },
    );
    testing.fireEvent.change(
      await testing.screen.findByLabelText("Expires in"),
      {
        target: { value: "168" },
      },
    );
    (
      await testing.screen.findByRole("button", { name: "Create link" })
    ).click();
    await testing.waitFor(() => {
      expect(requestParams(harness.requests, "shares.create").length).toBe(1);
    });
    const sent = requestParams(harness.requests, "shares.create")[0];
    expect(sent).toMatchObject({ label: "Weekly", expires_in_hours: 168 });
    expect(sent?.bot_id ?? null).toBeNull();
    const link = await testing.screen.findByTestId("new-share-link");
    expect(link.textContent).toContain(
      `${window.location.origin}/share/shr_new/s3cret`,
    );
    expect(link.textContent).toContain("shown once");
    testing
      .within(old as HTMLElement)
      .getByRole("button", { name: "Revoke" })
      .click();
    await testing.waitFor(() => {
      expect(
        requestParams(harness.requests, "shares.revoke")[0]?.share_id,
      ).toBe("shr_old");
    });
  } finally {
    harness.stop();
  }
});

const brief = {
  built_at: now.toISOString(),
  since: iso(24 * hour),
  kpis: [
    {
      key: "spend_today",
      label: "Spend today",
      value: 0.42,
      unit: "USD",
      source: "turn usage",
      note: "",
    },
  ],
  metric_changes: [metric({})],
  decisions: [
    {
      id: "pend_1",
      kind: "question",
      text: "Which subject line?",
      name: "user.ask",
      args: {},
      options: [],
      priority: "high",
      due_by: null,
      blocking: true,
      bot_id: "bot_news",
      bot_name: "Newsletter",
      agent_id: "agent_1",
      agent_title: "Tuesday issue",
      turn_id: "turn_1",
      created_at: iso(3 * hour),
    },
  ],
  decisions_total: 4,
  finished_done: 7,
  finished_failed: 1,
  finished_top: [
    {
      turn_id: "turn_2",
      status: "done",
      preview: "3 competitors changed prices",
      bot_id: "bot_news",
      bot_name: "Research",
      agent_id: "agent_2",
      agent_title: "Pricing scan",
      finished_at: iso(5 * hour),
    },
  ],
  routines_today: [
    {
      id: "rtn_1",
      name: "Mentions scan",
      bot_name: "Social",
      next_run: new Date(now.getTime() + 2 * hour).toISOString(),
      runs: 12,
      cost_per_run_usd: 0.04,
    },
  ],
  routines_today_usd: 0.48,
  routines_today_unpriced: 0,
  broken: [
    {
      kind: "failed_turns",
      text: "1 failed turn in the last 24 hours (Builder)",
    },
    { kind: "ollama_down", text: "Ollama is unreachable" },
  ],
};

test("the daily brief reads in one screen", async () => {
  const harness = await startHarness({ "fleet.brief": brief });
  const testing = await import("@testing-library/react");
  try {
    const BriefPage = await loadBriefPage();
    testing.render(createElement(BriefPage));
    await testing.screen.findByText(/^Built \d{2}:\d{2}$/);
    const decisions = await testing.screen.findByTestId("brief-decisions");
    expect(decisions.textContent).toContain("Which subject line?");
    expect(decisions.textContent).toContain("1 of 4");
    const finished = await testing.screen.findByTestId("brief-finished");
    expect(finished.textContent).toContain("7 done");
    expect(finished.textContent).toContain("1 failed");
    expect(finished.textContent).toContain("3 competitors changed prices");
    const today = await testing.screen.findByTestId("brief-today");
    expect(today.textContent).toContain("Mentions scan");
    expect(today.textContent).toContain("12 runs");
    expect(today.textContent).toContain("$0.48");
    const broken = await testing.screen.findByTestId("brief-broken");
    expect(broken.textContent).toContain("Ollama is unreachable");
    const changes = await testing.screen.findByTestId("brief-metrics");
    expect(changes.textContent).toContain("+110 in 24h");
  } finally {
    harness.stop();
  }
});

test("a quiet brief says nothing is broken", async () => {
  const harness = await startHarness({
    "fleet.brief": {
      ...brief,
      decisions: [],
      decisions_total: 0,
      broken: [],
      routines_today: [],
      routines_today_usd: 0,
    },
  });
  const testing = await import("@testing-library/react");
  try {
    const BriefPage = await loadBriefPage();
    testing.render(createElement(BriefPage));
    await testing.screen.findByText("Nothing is broken");
    await testing.screen.findByText("Nothing needs you");
  } finally {
    harness.stop();
  }
});

const shared = {
  as_of: now.toISOString(),
  label: "For the editor",
  scope_bot_name: "Newsletter",
  expires_at: new Date(now.getTime() + 2 * 24 * hour).toISOString(),
  kpis: [],
  bots: [{ id: "bot_news", name: "Newsletter", status: "idle" }],
  metrics: [
    {
      key: "subscribers",
      label: "Subscribers",
      value: 3210,
      unit: "",
      source: "Buttondown",
      as_of: iso(60_000),
      status: "ok",
      delta_24h: 12,
    },
  ],
  days: days(),
  activity: [],
  upcoming: [
    {
      name: "Weekly digest",
      bot_name: "Newsletter",
      schedule: "0 16 * * 5",
      timezone: "UTC",
      status: "active",
      paused_reason: null,
      next_run: new Date(now.getTime() + 3 * hour).toISOString(),
      cost_per_run_usd: 0.12,
      runs_next_7d: 1,
    },
  ],
  projection_7d_usd: null,
  waiting: 2,
  finished_24h: { done: 5, failed: 0 },
};

test("a share page fetches its snapshot and never opens the socket", async () => {
  const socket = vi.fn(() => {
    throw new Error("a share page must not open a WebSocket");
  });
  vi.stubGlobal("WebSocket", socket);
  const fetched = vi.fn(async () => ({
    ok: true,
    status: 200,
    json: async () => shared,
  }));
  vi.stubGlobal("fetch", fetched);
  const testing = await import("@testing-library/react");
  const SharePage = await loadSharePage();
  testing.render(
    createElement(SharePage, { shareId: "shr_1", secret: "s3cret" }),
  );
  await testing.screen.findByText("For the editor");
  await testing.screen.findByText("Newsletter only");
  await testing.screen.findByText("Weekly digest");
  await testing.screen.findByText("2 waiting on the owner");
  await testing.screen.findByText("5 finished in 24 hours");
  const tile = await testing.screen.findByTestId("metric-subscribers");
  expect(tile.textContent).toContain("+12 in 24h");
  expect(fetched).toHaveBeenCalledWith("/share/shr_1/s3cret/data", {
    cache: "no-store",
    credentials: "omit",
  });
  expect(socket).not.toHaveBeenCalled();
});

test("an invalid share link says so", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({ ok: false, status: 404, json: async () => ({}) })),
  );
  const testing = await import("@testing-library/react");
  const SharePage = await loadSharePage();
  testing.render(createElement(SharePage, { shareId: "shr_1", secret: "bad" }));
  await testing.screen.findByText("This link is not valid or has expired");
});
