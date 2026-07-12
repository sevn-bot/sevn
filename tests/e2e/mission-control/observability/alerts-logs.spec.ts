// Mission Control — Alerts & Logs tab (MC W3a).
// @mc-e2e-contract — G6 alert rules (data-path: E1)

import { expect, test } from "../fixtures";

import { ensureAuth, installErrorGate, openDashboard } from "../_helpers";
import { runTabSpec } from "../_runTab";

test("alerts-logs — rollup, proxy log refresh (no logging PUT on tab)", async ({ page }) => {
  const gate = installErrorGate(page);
  await openDashboard(page);
  await ensureAuth(page);
  await runTabSpec(page, "alerts-logs", {
    actionHooks: {
      "refresh-logs": async (p) => {
        await p.locator("#alerts-refresh-logs").click();
        await expect(p.locator(".log-tail")).toBeVisible({ timeout: 15_000 });
      },
    },
  });
  gate.assertNoErrors();
});
