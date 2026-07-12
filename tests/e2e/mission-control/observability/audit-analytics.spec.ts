// Mission Control — Audit & Analytics tab (MC W3a).
// @mc-e2e-contract

import { expect, test } from "../fixtures";

import { ensureAuth, installErrorGate, openDashboard } from "../_helpers";
import { runTabSpec } from "../_runTab";

test("audit-analytics — read-only panels", async ({ page }) => {
  const gate = installErrorGate(page);
  await openDashboard(page);
  await ensureAuth(page);
  await runTabSpec(page, "audit-analytics", {
    skipSnapshot: true,
    afterPanel: async (p) => {
      await expect(p.getByRole("heading", { name: /Audit timeline/i })).toBeVisible();
      await expect(p.getByRole("heading", { name: /Tool frequency/i })).toBeVisible();
      await expect(p.getByRole("heading", { name: /Daily volume/i })).toBeVisible();
      await expect(p.getByRole("heading", { name: /Approval timeline/i })).toBeVisible();
    },
  });
  gate.assertNoErrors();
});
