import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import type { FleetWaiting } from "../../src/client/connection.ts";
import { makeProfile } from "../support/direct.ts";

const fake = vi.hoisted(() => ({
  event: (_host: string, _event: { k: string }) => {},
  status: "connecting",
  fleet: (): Promise<{ waiting: FleetWaiting[] }> =>
    Promise.resolve({ waiting: [] }),
}));

vi.mock("../../src/client/hosts.ts", () => ({
  createHosts: () => ({
    start: () => {},
    stop: () => {},
    status: () => fake.status,
    onStatus: (handler: (host: string, status: string) => void) => {
      fake.status = "connected";
      handler("host_remote", "connected");
      return () => {};
    },
    onEvent: (handler: typeof fake.event) => {
      fake.event = handler;
      return () => {};
    },
    call: (_host: string, method: string) =>
      method === "fleet.overview"
        ? fake.fleet()
        : Promise.resolve({ bots: [] }),
    client: () => null,
    error: () => null,
  }),
}));

afterEach(cleanup);

test("a connected host stays available while fleet data is loading or refreshing", async () => {
  const { profileStore, useMultiHost } = await import(
    "../../src/app/hosts/useHosts.ts"
  );
  const { profile } = await makeProfile({
    host_id: "host_remote",
    direct_url: "wss://remote.example/ws",
  });
  await profileStore().put(profile);
  const waiting: FleetWaiting[] = [
    {
      id: "pending_1",
      kind: "approval",
      text: "Run command",
      name: "shell",
      args: {},
      options: [],
      priority: "normal",
      due_by: null,
      blocking: true,
      bot_id: "bot_1",
      bot_name: "Builder",
      agent_id: "agent_1",
      agent_title: "Lane",
      turn_id: "turn_1",
      created_at: "2026-01-01T00:00:00Z",
    },
  ];
  let answer: ((value: { waiting: FleetWaiting[] }) => void) | undefined;
  fake.fleet = () =>
    new Promise((resolve) => {
      answer = resolve;
    });
  const { result } = renderHook(() =>
    useMultiHost(
      {
        hostId: "host_local",
        status: "reconnecting",
        url: "ws://localhost/ws",
      },
      0,
      () => {},
    ),
  );
  const remote = () =>
    result.current.views.find((view) => view.host_id === profile.host_id);
  await waitFor(() => expect(remote()?.reachable).toBe(true));
  expect(remote()?.available).toBe(true);
  await act(async () => {
    answer?.({ waiting });
  });
  expect(remote()?.available).toBe(true);
  expect(remote()?.waiting).toEqual(waiting);
  act(() => {
    fake.event(profile.host_id, { k: "pending.created" });
  });
  expect(remote()?.available).toBe(true);
  await act(async () => {
    answer?.({ waiting });
  });
  expect(remote()?.available).toBe(true);
});
