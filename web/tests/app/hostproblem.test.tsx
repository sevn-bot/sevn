import { createElement } from "react";
import { afterEach, expect, test, vi } from "vitest";
import {
  type DirectHost,
  directHost,
  type Frame,
  type HostProfile,
  makeProfile,
  newHostKey,
  stubSockets,
} from "../support/direct.ts";

/**
 * Plan 0055 WV advisory A1: a direct dial whose `host_sig` fails stays the hard error
 * `HostIdentityChanged` ("Host identity changed — re-pair to continue", D6), but the sidebar
 * also says the host may not list this address in `http.allowed_hosts` (a decoy challenge
 * looks exactly like a changed key).
 */

afterEach(async () => {
  const testing = await import("@testing-library/react");
  testing.cleanup();
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/");
});

async function servingHost(
  mock: Awaited<ReturnType<typeof stubSockets>>,
): Promise<{ stop: () => void }> {
  const server = new mock.Server("ws://localhost:3000/ws");
  const replies: Record<string, Record<string, unknown>> = {
    "system.info": {
      host_id: "host_local",
      version: "0.0.0",
      proto: 1,
      caps: { allow_all: false },
      host_pubkey_fp: "local_fp",
    },
    "bots.list": { bots: [] },
    "fleet.overview": { waiting: [] },
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
      if (frame.t === "req") {
        const result = replies[String(frame.m)] ?? {};
        socket.send(JSON.stringify({ t: "res", id: frame.id, r: result }));
      }
    });
  });
  return { stop: () => server.stop() };
}

test("a failed host signature names http.allowed_hosts next to the re-pair message", async () => {
  const mock = await stubSockets();
  const pinned = await newHostKey();
  const decoy = await newHostKey();
  const url = "ws://100.101.102.2:8787/ws";
  const made = await makeProfile(
    { host_id: "host_b", name: "Omarchy", direct_url: url },
    pinned,
  );
  const profile: HostProfile = made.profile;
  let remote: DirectHost | undefined;
  let local: { stop: () => void } | undefined;
  const testing = await import("@testing-library/react");
  try {
    remote = await directHost(mock, {
      url,
      hostId: "host_b",
      key: pinned,
      devicePubkey: made.devicePubkey,
      signWith: decoy.pair.privateKey,
    });
    local = await servingHost(mock);
    const { profileStore } = (await import(
      "../../src/app/hosts/useHosts.ts"
    )) as { profileStore: () => { put: (p: HostProfile) => Promise<void> } };
    await profileStore().put(profile);
    const app = (await import("../../src/app/App.tsx")) as {
      default: () => unknown;
    };
    testing.render(createElement(app.default as never));
    const region = await testing.screen.findByRole(
      "region",
      { name: "Omarchy" },
      { timeout: 4000 },
    );
    await testing.waitFor(
      () => {
        const text = region.textContent ?? "";
        expect(text).toContain("Host identity changed — re-pair to continue");
        expect(text).toContain("http.allowed_hosts");
      },
      { timeout: 4000 },
    );
    expect(
      testing.within(region).getByRole("img", { name: "unreachable" }),
    ).toBeTruthy();
    // No auth was sent to a host whose signature failed.
    expect(
      (remote.connections.flat() ?? []).some((frame) => frame.t === "auth"),
    ).toBe(false);
  } finally {
    remote?.stop();
    local?.stop();
  }
});
