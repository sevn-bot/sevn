// Mission Control — Traces tab (MC W3a).
// @mc-e2e-contract — G7 replay execution (data-path: E3)

import { expect, test } from "../fixtures";

import { ensureAuth, installErrorGate, mcE2ePanelTimeout, openDashboard } from "../_helpers";
import { acceptConfirmDialog } from "../_dialog";
import { runTabSpec } from "../_runTab";

test("traces — filters, detail, replay turn", async ({ page }) => {
  test.setTimeout(60_000);
  const gate = installErrorGate(page);
  await openDashboard(page);
  await ensureAuth(page);
  await runTabSpec(page, "traces", {
    skipSnapshot: true,
    skipKeySelectors: [
      "#trace-replay-status",
      "#trace-replay-turn",
      ".trace-row[data-span-id]",
      "#trace-detail",
      "#trace-filters",
    ],
    viewHooks: {
      list: async (p) => {
        await expect(p.locator("#trace-filters")).toBeVisible();
      },
      detail: async (p) => {
        const row = p.locator(".trace-row[data-span-id]").first();
        await expect(row).toBeVisible({ timeout: 15_000 });
        await row.click();
        await expect(p.locator("#trace-detail")).not.toContainText("Select a span");
      },
    },
    actionHooks: {
      "replay-turn": async (p) => {
        const replay = p.locator("#trace-replay-turn");
        if ((await replay.count()) === 0) {
          await expect(p.locator("#trace-detail")).toContainText(/Replay requires|Re-run this turn/i);
          return;
        }
        if (!(await replay.isVisible())) {
          return;
        }
        await acceptConfirmDialog(p, () => replay.click());
        await expect(p.locator("#trace-replay-status")).toBeVisible({ timeout: mcE2ePanelTimeout() });
      },
    },
  });
  gate.assertNoErrors();
});
