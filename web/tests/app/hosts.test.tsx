import { createElement } from "react";
import { afterEach, expect } from "vitest";
import { loadComponent } from "../support/components.ts";
import { red } from "../support/red.ts";

/**
 * Plan 0055 D9: one window across hosts.
 *
 * Pinned presentational components (props only, no socket):
 * - `web/src/app/hosts/HostSidebar.tsx` → `HostSidebar({ hosts })`, `hosts` =
 *   `{ host_id, name, reachable, bots: { id, name }[] }[]`: one `<section aria-label={name}>`
 *   per host with its bots and a dot `role="img"` named "reachable" or "unreachable".
 * - `web/src/app/hosts/Inbox.tsx` → `Inbox({ hosts })` and
 *   `web/src/app/hosts/Approvals.tsx` → `Approvals({ hosts })`, `hosts` =
 *   `{ host_id, name, available, waiting: FleetWaiting[] }[]`: one list item per waiting item
 *   with the host name in it; Approvals lists only `kind === "approval"`; an unavailable
 *   host shows "<name> unavailable".
 */
const w6 = red("W6");

afterEach(async () => {
  const testing = await import("@testing-library/react");
  testing.cleanup();
});

function waiting(
  id: string,
  kind: "question" | "approval",
  text: string,
): Record<string, unknown> {
  return {
    id,
    kind,
    text,
    name: kind === "approval" ? "shell" : "user.ask",
    args: {},
    options: [],
    priority: "normal",
    due_by: null,
    blocking: true,
    bot_id: `bot_${id}`,
    bot_name: "Builder",
    agent_id: `agent_${id}`,
    agent_title: "Lane",
    turn_id: `turn_${id}`,
    created_at: new Date().toISOString(),
  };
}

const hosts = [
  {
    host_id: "host_mac",
    name: "Mac mini",
    available: true,
    waiting: [
      waiting("q1", "question", "Which subject line?"),
      waiting("a1", "approval", "Run make deploy"),
    ],
  },
  {
    host_id: "host_linux",
    name: "Omarchy",
    available: true,
    waiting: [waiting("a2", "approval", "Delete build cache")],
  },
  { host_id: "host_pi", name: "Pi", available: false, waiting: [] },
];

w6("the sidebar groups bots by host with a reachability dot", async () => {
  const testing = await import("@testing-library/react");
  const HostSidebar = await loadComponent(
    "../../src/app/hosts/HostSidebar.tsx",
    "HostSidebar",
  );
  testing.render(
    createElement(HostSidebar, {
      hosts: [
        {
          host_id: "host_mac",
          name: "Mac mini",
          reachable: true,
          bots: [
            { id: "bot_1", name: "Newsletter" },
            { id: "bot_2", name: "Research" },
          ],
        },
        {
          host_id: "host_linux",
          name: "Omarchy",
          reachable: false,
          bots: [{ id: "bot_3", name: "Builder" }],
        },
      ],
    }),
  );
  const mac = testing.screen.getByRole("region", { name: "Mac mini" });
  const linux = testing.screen.getByRole("region", { name: "Omarchy" });
  expect(testing.within(mac).getByText("Newsletter")).toBeTruthy();
  expect(testing.within(mac).getByText("Research")).toBeTruthy();
  expect(testing.within(mac).queryByText("Builder")).toBeNull();
  expect(testing.within(linux).getByText("Builder")).toBeTruthy();
  expect(
    testing.within(mac).getByRole("img", { name: "reachable" }),
  ).toBeTruthy();
  expect(
    testing.within(linux).getByRole("img", { name: "unreachable" }),
  ).toBeTruthy();
});

w6("one inbox lists every host's waiting items with a host label", async () => {
  const testing = await import("@testing-library/react");
  const Inbox = await loadComponent("../../src/app/hosts/Inbox.tsx", "Inbox");
  testing.render(createElement(Inbox, { hosts }));
  const question = (
    await testing.screen.findByText("Which subject line?")
  ).closest("li");
  const linuxItem = (
    await testing.screen.findByText("Delete build cache")
  ).closest("li");
  expect(question?.textContent).toContain("Mac mini");
  expect(linuxItem?.textContent).toContain("Omarchy");
  expect(testing.screen.getByText("Run make deploy")).toBeTruthy();
  expect(testing.screen.getByText("Pi unavailable")).toBeTruthy();
});

w6("one approvals view shows only approvals, each with its host", async () => {
  const testing = await import("@testing-library/react");
  const Approvals = await loadComponent(
    "../../src/app/hosts/Approvals.tsx",
    "Approvals",
  );
  testing.render(createElement(Approvals, { hosts }));
  const deploy = (await testing.screen.findByText("Run make deploy")).closest(
    "li",
  );
  const cache = (await testing.screen.findByText("Delete build cache")).closest(
    "li",
  );
  expect(deploy?.textContent).toContain("Mac mini");
  expect(cache?.textContent).toContain("Omarchy");
  expect(testing.screen.queryByText("Which subject line?")).toBeNull();
});
