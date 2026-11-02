import { createElement } from "react";
import { afterEach, expect, test, vi } from "vitest";
import { requestParams, startHarness } from "../chat/host.ts";
import {
  type DirectHost,
  directHost,
  type Frame,
  type HostProfile,
  makeProfile,
  newHostKey,
  stubSockets,
  until,
} from "../support/direct.ts";

/**
 * Plan 0055 W6 follow-up (WV.1 "chat with a bot on each host from one window"): a remote
 * host's bot opens from the sidebar and its chat talks only to that host.
 *
 * Pinned:
 * - Route `/hosts/:hostId/bots/:botId[/agents/:agentId]`; `web/src/app/routes.ts` exports
 *   `hostBotPath(hostId, botId)` and `routeFromPath(path)` returns `{ hostId, botId, agentId }`
 *   (`hostId: null` for the serving host's `/bots/...` routes, unchanged).
 * - `web/src/app/hosts/HostClient.tsx` exports `HostClientProvider({ client, children })` and
 *   `useHostClient()`. `HostClient = { call(method, params), onEvent(handler) -> off,
 *   onTick(kind, handler) -> off }`. Every chat hook and child (`useCall`, `useEvents`,
 *   `useTicks`, sends, approvals, settings) uses the client from context; with no provider it
 *   is the serving host's connection, so single-host behaviour is unchanged.
 * - `Hosts.client(hostId)` (`web/src/client/hosts.ts`) gives that host's `HostClient`; the
 *   app wraps a remote chat in `HostClientProvider` with it. Remote bots in the sidebar are
 *   pickable and open `hostBotPath(...)`.
 */

type ProtocolEvent = { s: number; k: string; d: Record<string, unknown> };
type HostClient = {
  call: (method: string, params: Record<string, unknown>) => Promise<unknown>;
  onEvent: (handler: (event: ProtocolEvent) => void) => () => void;
  onTick: (
    kind: string,
    handler: (data: Record<string, unknown>) => void,
  ) => () => void;
};
type Component = (props: Record<string, unknown>) => unknown;

async function load<T>(specifier: string): Promise<T> {
  return (await import(specifier)) as T;
}

afterEach(async () => {
  const testing = await import("@testing-library/react");
  testing.cleanup();
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/");
});

function message(id: string, text: string): Record<string, unknown> {
  return {
    id,
    thread_id: "thr_1",
    turn_id: `turn_${id}`,
    agent_id: "agent_1",
    role: "user",
    author: "owner",
    parts: [{ type: "text", text }],
    created_at: new Date().toISOString(),
  };
}

function bot(id: string, name: string): Record<string, unknown> {
  return {
    id,
    name,
    title: "",
    scope: "",
    instructions: "",
    avatar: "",
    runtime: "pydantic_ai",
    model: "test",
    effort: null,
    access: "workspace",
    approval_policy: "ask",
    network: "off",
    workspace_path: "",
    folder_id: null,
    paused: false,
    can_create_bots: false,
    created_by: "owner",
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
}

/** A fake remote host client: records calls, answers from `replies`, emits on demand. */
function fakeClient(replies: Record<string, Record<string, unknown>>): {
  client: HostClient;
  calls: { method: string; params: Record<string, unknown> }[];
  emit: (event: ProtocolEvent) => void;
  tick: (kind: string, data: Record<string, unknown>) => void;
} {
  const calls: { method: string; params: Record<string, unknown> }[] = [];
  const events: ((event: ProtocolEvent) => void)[] = [];
  const ticks: {
    kind: string;
    handler: (data: Record<string, unknown>) => void;
  }[] = [];
  return {
    calls,
    client: {
      call(method, params) {
        calls.push({ method, params });
        return Promise.resolve(replies[method] ?? {});
      },
      onEvent(handler) {
        events.push(handler);
        return () => {
          events.splice(events.indexOf(handler), 1);
        };
      },
      onTick(kind, handler) {
        const entry = { kind, handler };
        ticks.push(entry);
        return () => {
          ticks.splice(ticks.indexOf(entry), 1);
        };
      },
    },
    emit(event) {
      for (const handler of [...events]) {
        handler(event);
      }
    },
    tick(kind, data) {
      for (const entry of [...ticks]) {
        if (entry.kind === kind) {
          entry.handler(data);
        }
      }
    },
  };
}

const remoteReplies = {
  "messages.list": {
    messages: [message("msg_b1", "hello from B")],
    next_cursor: null,
  },
  "agents.list": {
    agents: [{ id: "agent_1", title: "B lane", status: "idle" }],
  },
  "pending.list": { pending: [] },
  "bots.get": bot("bot_remote", "Beta on B"),
  "messages.send": { job_id: "job_b", seq: 2 },
};

test("routes name the host for a remote bot", async () => {
  const routes = await load<{
    hostBotPath: (hostId: string, botId: string) => string;
    routeFromPath: (path: string) => {
      hostId: string | null;
      botId: string | null;
      agentId: string | null;
    };
  }>("../../src/app/routes.ts");
  expect(routes.hostBotPath("host_b", "bot_remote")).toBe(
    "/hosts/host_b/bots/bot_remote",
  );
  expect(routes.routeFromPath("/hosts/host_b/bots/bot_remote")).toEqual({
    hostId: "host_b",
    botId: "bot_remote",
    agentId: null,
  });
  expect(
    routes.routeFromPath("/hosts/host_b/bots/bot_remote/agents/agent_1"),
  ).toEqual({ hostId: "host_b", botId: "bot_remote", agentId: "agent_1" });
  expect(routes.routeFromPath("/bots/bot_local")).toEqual({
    hostId: null,
    botId: "bot_local",
    agentId: null,
  });
});

test("a chat inside HostClientProvider fetches, sends and listens on that host only", async () => {
  // The serving host is connected too: nothing from the remote chat may reach it.
  const local = await startHarness({
    "messages.list": {
      messages: [message("msg_local", "local only")],
      next_cursor: null,
    },
    "pending.list": { pending: [] },
  });
  const testing = await import("@testing-library/react");
  const remote = fakeClient(remoteReplies);
  try {
    const { HostClientProvider } = await load<{
      HostClientProvider: Component;
    }>("../../src/app/hosts/HostClient.tsx");
    const { Chat } = await load<{ Chat: Component }>(
      "../../src/app/chat/Chat.tsx",
    );
    testing.render(
      createElement(
        HostClientProvider as never,
        { client: remote.client },
        createElement(Chat as never, { botId: "bot_remote" }),
      ),
    );
    await testing.screen.findByText("hello from B");
    expect(testing.screen.queryByText("local only")).toBeNull();
    const listed = remote.calls.filter((c) => c.method === "messages.list");
    expect(listed[0]?.params.bot_id).toBe("bot_remote");
    expect(requestParams(local.requests, "messages.list")).toEqual([]);
    expect(requestParams(local.requests, "bots.get")).toEqual([]);

    testing.fireEvent.change(await testing.screen.findByLabelText("Message"), {
      target: { value: "hi B" },
    });
    (await testing.screen.findByRole("button", { name: "Send" })).click();
    await testing.waitFor(() => {
      expect(
        remote.calls.filter((c) => c.method === "messages.send").length,
      ).toBe(1);
    });
    const sent = remote.calls.find((c) => c.method === "messages.send");
    expect(sent?.params).toMatchObject({
      bot_id: "bot_remote",
      text: "hi B",
    });
    expect(requestParams(local.requests, "messages.send")).toEqual([]);

    // Live events from B refresh the open chat; events from the serving host do not.
    const fetches = () =>
      remote.calls.filter((c) => c.method === "messages.list").length;
    const before = fetches();
    local.event("message.created", { bot_id: "bot_remote" });
    await new Promise((resolve) => setTimeout(resolve, 200));
    expect(fetches()).toBe(before);
    remote.emit({ s: 3, k: "message.created", d: { bot_id: "bot_remote" } });
    await testing.waitFor(() => {
      expect(fetches()).toBeGreaterThan(before);
    });

    // Streaming ticks come from B too.
    remote.tick("turn.delta", {
      turn_id: "turn_live",
      agent_id: "agent_1",
      text: "streamed from B",
    });
    await testing.screen.findByText("streamed from B", { exact: false });
  } finally {
    local.stop();
  }
});

test("without a provider the chat still uses the serving host", async () => {
  const local = await startHarness({
    "messages.list": {
      messages: [message("msg_local", "local only")],
      next_cursor: null,
    },
    "pending.list": { pending: [] },
  });
  const testing = await import("@testing-library/react");
  try {
    const { useHostClient } = await load<{ useHostClient: () => HostClient }>(
      "../../src/app/hosts/HostClient.tsx",
    );
    expect(typeof useHostClient).toBe("function");
    const { Chat } = await load<{ Chat: Component }>(
      "../../src/app/chat/Chat.tsx",
    );
    testing.render(createElement(Chat as never, { botId: "bot_local" }));
    await testing.screen.findByText("local only");
    expect(requestParams(local.requests, "messages.list")[0]?.bot_id).toBe(
      "bot_local",
    );
  } finally {
    local.stop();
  }
});

type LocalHost = { requests: Frame[]; stop: () => void };

/** The serving host at the page's own origin, answering without a token like a cookie session. */
async function servingHost(
  mock: Awaited<ReturnType<typeof stubSockets>>,
): Promise<LocalHost> {
  const server = new mock.Server("ws://localhost:3000/ws");
  const requests: Frame[] = [];
  const replies: Record<string, Record<string, unknown>> = {
    "system.info": {
      host_id: "host_local",
      version: "0.0.0",
      proto: 1,
      caps: { allow_all: false },
      host_pubkey_fp: "local_fp",
    },
    "bots.list": { bots: [bot("bot_local", "Alpha on A")] },
    "fleet.overview": { waiting: [] },
    "messages.list": {
      messages: [message("msg_a1", "hello from A")],
      next_cursor: null,
    },
    "agents.list": { agents: [] },
    "pending.list": { pending: [] },
    "bots.get": bot("bot_local", "Alpha on A"),
    "sync.since": { host_seq: 0, next_seq: 0, more: false },
  };
  server.on("connection", (socket) => {
    socket.on("message", (data) => {
      const frame = JSON.parse(String(data)) as Frame;
      if (frame.t === "hello") {
        setTimeout(() => {
          socket.send(
            JSON.stringify({ t: "welcome", proto: 1, host_seq: 0, caps: [] }),
          );
        }, 0);
        return;
      }
      if (frame.t !== "req") {
        return;
      }
      requests.push(frame);
      const result = replies[String(frame.m)] ?? {};
      socket.send(JSON.stringify({ t: "res", id: frame.id, r: result }));
    });
  });
  return { requests, stop: () => server.stop() };
}

test("the app opens a remote host's bot from the sidebar and talks to that host", async () => {
  const mock = await stubSockets();
  const key = await newHostKey();
  const url = "ws://100.101.102.2:8787/ws";
  const made = await makeProfile(
    { host_id: "host_b", name: "Omarchy", direct_url: url },
    key,
  );
  const remoteProfile: HostProfile = made.profile;
  let remote: DirectHost | undefined;
  let local: LocalHost | undefined;
  const testing = await import("@testing-library/react");
  try {
    remote = await directHost(mock, {
      url,
      hostId: "host_b",
      key,
      devicePubkey: made.devicePubkey,
      replies: {
        ...remoteReplies,
        "bots.list": { bots: [bot("bot_remote", "Beta on B")] },
        "fleet.overview": { waiting: [] },
      },
    });
    local = await servingHost(mock);
    const { profileStore } = await load<{
      profileStore: () => { put: (profile: HostProfile) => Promise<void> };
    }>("../../src/app/hosts/useHosts.ts");
    await profileStore().put(remoteProfile);
    const app = await load<{ default: Component }>("../../src/app/App.tsx");
    testing.render(createElement(app.default as never));

    const region = await testing.screen.findByRole(
      "region",
      { name: "Omarchy" },
      { timeout: 4000 },
    );
    const open = await testing
      .within(region)
      .findByRole("button", { name: "Beta on B" }, { timeout: 4000 });
    open.click();
    await testing.waitFor(() => {
      expect(window.location.pathname).toBe("/hosts/host_b/bots/bot_remote");
    });
    await testing.screen.findByText("hello from B", {}, { timeout: 4000 });

    const sentToB = (method: string) =>
      (remote?.connections.flat() ?? []).filter(
        (frame) => frame.t === "req" && frame.m === method,
      );
    const byBot = (frames: Frame[]) =>
      frames.filter(
        (frame) =>
          typeof frame.p === "object" &&
          frame.p !== null &&
          (frame.p as Record<string, unknown>).bot_id === "bot_remote",
      );
    expect(byBot(sentToB("messages.list")).length).toBeGreaterThan(0);
    expect(byBot(local.requests)).toEqual([]);

    testing.fireEvent.change(await testing.screen.findByLabelText("Message"), {
      target: { value: "hi B" },
    });
    (await testing.screen.findByRole("button", { name: "Send" })).click();
    await until(() => sentToB("messages.send").length === 1, 3000);
    const send = sentToB("messages.send")[0]?.p as Record<string, unknown>;
    expect(send).toMatchObject({ bot_id: "bot_remote", text: "hi B" });
    expect(typeof send.op_id).toBe("string");
    expect(String(send.op_id).length).toBeGreaterThan(0);
    expect(
      local.requests.filter((frame) => frame.m === "messages.send"),
    ).toEqual([]);

    // The serving host's own bot still opens on its own connection.
    const own = await testing.screen.findByRole("region", {
      name: "This host",
    });
    testing.within(own).getByRole("button", { name: "Alpha on A" }).click();
    await testing.screen.findByText("hello from A", {}, { timeout: 4000 });
    expect(window.location.pathname).toBe("/bots/bot_local");
  } finally {
    remote?.stop();
    local?.stop();
  }
});
